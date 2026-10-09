# Scripting a Mixxx AutoDJ set

How to lay out a timed DJ set — running order, per-track in/out points, internal
edits, crossfade lengths — and write the whole thing into [Mixxx](https://mixxx.org)
so that AutoDJ plays it unattended from the first track to the last, start time
to end time, without anyone touching the laptop.

Written up after doing it for a wedding reception: 77 tracks, a hard stop
dictated by the caterer, and a bride and groom who were going to be busy
being married. The numbers below are from that set; everything else generalises.

There are two halves to it:

- **Deciding what the set is** — running order, cut points, where the peak goes.
  That is [`docs/set-design.md`](set-design.md), and the first draft of it
  can be done by a language model using
  [`prompts/build-setlist.md`](../prompts/build-setlist.md).
- **Getting it into Mixxx** — cue points, rendered edits, playlists, the AutoDJ
  queue. That is this document.

- **Mixxx**: 2.5.6, library schema v39, Linux
- **Also needed**: Python 3 (stdlib only), `ffmpeg`/`ffprobe`
- **Scripts**: [`scripts/`](../scripts/)

---

## 1. The problem

A DJ set under a wall clock is a scheduling problem with an audio problem inside it.

The scheduling half: the reception ran from 17:00, the bar closed at 19:00 and
the music had to stop at 19:30. Everything that mattered to the guests had to
happen before the room emptied at 19:00, and the last track had to land on
19:30, not 19:26 or 19:41.

The audio half: 77 tracks do not fit in 150 minutes at full length. They fit at
an average of 117 seconds each, which means most tracks need a cue-out somewhere
useful, and some need their boring middle removed entirely.

Doing that by hand in a GUI, for 77 tracks, and then redoing it every time the
running order changes, is not realistic. So: describe the set as data, generate
everything from it, and write the result into Mixxx's database directly.

```
 music folder
      │  make_inventory.py      Mixxx already knows every BPM and duration
      ▼
 inventory.json  (+ your genre and energy ratings)
      │  prompts/build-setlist.md  ──>  a language model
      ▼
 setlist.json ──> check_setlist.py ──> errors? back to the model
      │
      ├──> render_edits.py ──> edited audio files
      ├──> write_mixxx.py  ──> mixxxdb.sqlite (cues + playlists + AutoDJ queue)
      └──> verify_mixxx.py <── read back from disk and check
```

Every stage is checkable, which is the point: a set list is a few hundred
numbers, and you will not spot a wrong one by reading it.

Two folders, always:

```
~/Music/Set/         originals, never modified
~/Music/Set-cut/     copies — cue points and rendered edits live here
```

Cue points in Mixxx are a property of the **track**, not of the playlist. Trim a
track and you have trimmed it everywhere. Keeping an untouched original set is
what lets you rebuild from scratch when the running order changes, and is the
difference between an experiment and a one-way door.

---

## 2. What you need to know about Mixxx's database

Mixxx keeps its library in `~/.mixxx/mixxxdb.sqlite`. It is a plain SQLite file
with a readable schema, which makes it scriptable.

**Mixxx must be closed while you write to it.** It holds the library in memory
and flushes on exit, so a write made while it is running is silently overwritten
when the user quits. This cost me a configuration change before I learned it.

### The tables that matter

| Table | What it holds |
|---|---|
| `track_locations` | one row per file on disk: `location`, `directory`, `filename`, `fs_deleted` |
| `library` | one row per track: `duration`, `samplerate`, `bpm`, `cuepoint`, FK to `track_locations` |
| `cues` | `track_id`, `type`, `position`, `length`, `hotcue`, `label` |
| `Playlists` | `id`, `name`, `position`, `hidden` |
| `PlaylistTracks` | `playlist_id`, `track_id`, `position` |
| `directories` | the folders Mixxx scans |

Two things are not obvious:

- **The AutoDJ queue is just a playlist** — the hidden one with `id = 1`. Insert
  rows into `PlaylistTracks` with `playlist_id = 1` and you have loaded the
  queue. `hidden = 0` is a normal playlist, `1` is AutoDJ, `2` is a history entry.
- **`library.location` is a foreign key to `track_locations.id`**, not a path.

### Cue types

From [`src/track/cueinfo.h`](https://github.com/mixxxdj/mixxx/blob/main/src/track/cueinfo.h):

```
Invalid = 0   HotCue = 1   MainCue = 2   Beat = 3   Loop = 4
Jump = 5      Intro = 6    Outro = 7     N60dBSound = 8
```

For a scripted set you write three per track: `MainCue` and `Intro` at the
in-point, `Outro` at the out-point. `N60dBSound` is Mixxx's own silence
detection — leave it alone.

### Cue positions are engine sample positions

This is the detail that will cost you an afternoon. `position` and `length` are
**not** seconds, and not frames either. From
[`src/library/dao/cuedao.cpp`](https://github.com/mixxxdj/mixxx/blob/main/src/library/dao/cuedao.cpp):

```cpp
// reading
const auto position = mixxx::audio::FramePos::fromEngineSamplePosMaybeInvalid(
        row.value(row.indexOf("position")).toDouble());
double lengthFrames = row.value(row.indexOf("length")).toDouble() /
        mixxx::kEngineChannelOutputCount;

// writing
query.bindValue(":position", cue->getPosition().toEngineSamplePosMaybeInvalid());
query.bindValue(":length", cue->getLengthFrames() * mixxx::kEngineChannelOutputCount);
```

and `kEngineChannelOutputCount` is stereo, i.e. 2
([`src/engine/engine.h`](https://github.com/mixxxdj/mixxx/blob/main/src/engine/engine.h)).
So:

```python
position = seconds * samplerate * 2
```

You can confirm it against Mixxx's own data without reading any more source.
Mixxx writes a `N60dBSound` cue (type 8) spanning the audible part of each
track, so dividing its stored values by `samplerate * 2` should give you
"a fraction of a second in" and "just under the track duration":

```
track                           start    length    file duration
You Shook Me All Night Long      0.41s   209.57s        210.21s
T.N.T.                           0.58s   212.93s        214.70s
Breakin' Outta Hell              0.07s   230.51s        232.46s
```

That is the factor, verified against data you did not write.

### Mixxx will not overwrite cues you wrote

Worth knowing before you worry about re-analysis destroying your work. From
[`src/analyzer/analyzersilence.cpp`](https://github.com/mixxxdj/mixxx/blob/main/src/analyzer/analyzersilence.cpp):

```cpp
CuePointer pIntroCue = pTrack->findCueByType(mixxx::CueType::Intro);
...
if (pIntroCue == nullptr) {
    pIntroCue = pTrack->createAndAddCue(mixxx::CueType::Intro, ...);
}
```

and the same guard in `setupOutroCue`. The analyser only *creates* intro and
outro cues; it never moves existing ones. Running "Analyze" on a track whose
cues you wrote by hand is safe.

---

## 3. What AutoDJ actually does — and what it does not

This is the heart of it, and I got it wrong the first time.

AutoDJ has several transition modes
([`src/library/autodj/autodjprocessor.h`](https://github.com/mixxxdj/mixxx/blob/main/src/library/autodj/autodjprocessor.h)):

```cpp
enum class TransitionMode {
    FullIntroOutro,      // 0
    FadeAtOutroStart,    // 1
    FixedFullTrack,      // 2
    FixedSkipSilence,    // 3
    FixedStartCenterSkipSilence,
};
```

Set it in `~/.mixxx/mixxx.cfg` (Mixxx closed):

```ini
[Auto DJ]
TransitionMode 1
Transition 4
Requeue 0
```

`FadeAtOutroStart` is the one to use for a scripted set: the next track starts
at the current track's **outro cue**, which is exactly the control you want.
`FullIntroOutro` stretches transitions to cover both cues and is harder to
predict. The `Fixed*` modes ignore your cues entirely and crossfade over a fixed
number of seconds.

**Two traps.**

### An outro cue with `length = 0` is ignored

If the outro cue has no length, AutoDJ falls back to the fixed crossfade
spinbox and your out-point does nothing. Always write a real length. That length
*is* the crossfade duration, so it is also where you encode how each transition
should feel — a long blend between two tracks four BPM apart, a two-second cut
between tracks ninety apart.

### AutoDJ cannot skip a region inside a track

AutoDJ reads `Intro` and `Outro`. It does not read hotcues, and there is no
"jump" automation anywhere in it. Hotcues are a thing a human presses.

I had written `JUMP FROM` / `JUMP TO` hotcue pairs on seven tracks — skip the
guitar solo, land on the last chorus — and assumed AutoDJ would honour them.
It will not. It plays straight through. The hotcues are *annotations*; they tell
a person where to press a button, which during your own wedding is not a plan.

So: **an edit inside a track has to exist in the audio.** Which brings us to the
interesting part.

---

## 4. Rendering internal edits

For each edit we want:

```
[cue_in .. jump_from]  +  [jump_to .. cue_out + fade]
```

The `+ fade` matters: those extra seconds past the out-point are the tail AutoDJ
crossfades under the incoming track. Cut the file at `cue_out` exactly and the
outgoing track is `fade` seconds shorter than you planned, and the set drifts.

### Quantise the splice to whole bars

A butt-join between two arbitrary points in a song sounds like an edit, because
the beat after the join lands in the wrong place. Fix it by choosing *how much*
to remove rather than exactly where to land: snap the removed span to a whole
number of bars at the track's BPM.

```python
def snap_to_bars(jump_from, jump_to, bpm, beats_per_bar=4):
    bar = beats_per_bar * 60.0 / bpm
    bars = max(1, round((jump_to - jump_from) / bar))
    return jump_from + bars * bar, bars
```

Remove a whole number of bars and every beat after the join falls exactly where
it would have fallen in the original. You do not need to know where the
downbeats are in absolute terms — only that the two sides share a phase. On the
real set this moved each `jump_to` by at most 1.03 s, and changed the total
running time by 1.1 s across seven edits.

### The crossfade trap that undoes it

Join the two segments with a short crossfade so the splice does not click:

```
[A][B]acrossfade=d=0.025:c1=tri:c2=tri[out]
```

`acrossfade` overlaps the tail of A with the head of B, so the output is `d`
seconds **shorter** than A + B. Everything after the join therefore arrives `d`
seconds early — and the bar quantisation you just did is silently undone.

I only caught this by testing on a synthetic 120 BPM click track, detecting the
click onsets in the rendered output and measuring them against the beat grid:

```
before the fix:   phase error after the join = 24.9 ms (max 26.7)
                  interval across the join   = 0.977 s   (should be 0.500)
```

25 ms is the crossfade length, exactly. The fix is to start segment B `d`
earlier, so the overlap consumes material rather than time:

```python
start_b = jump_to - XFADE     # compensates acrossfade's shortening
```

```
after the fix:    phase error after the join = 0.0 ms (max 0.0)
                  interval across the join   = 0.500 s
```

The full filter:

```python
flt = (
    f"[0:a]asplit=2[x][y];"
    f"[x]atrim=start={cue_in}:end={jump_from},asetpts=N/SR/TB[A];"
    f"[y]atrim=start={start_b:.6f}:end={end_b:.6f},asetpts=N/SR/TB[B];"
    f"[A][B]acrossfade=d={XFADE}:c1=tri:c2=tri[m];"
    f"[m]afade=t=out:st={new_dur - 0.015:.6f}:d=0.015[o]"
)
```

Re-encode rather than stream-copy: MP3 frame boundaries are not sample accurate,
and `-c copy` will leave a gap or a click at every cut. The 15 ms fade at the end
stops the file ending mid-waveform.

### Check the result numerically

You cannot listen to 77 tracks every time you change the running order, but you
can measure. Two cheap checks catch most damage:

- **Level continuity across the join** — RMS over ~350 ms either side. A jump of
  a few dB is a chorus arriving after a verse and is fine; 10 dB means you
  spliced two unrelated sections. On the real set the worst was 4.1 dB.
- **Peak against the original** — decode both to float and compare. Modern
  masters already decode above 1.0; what you care about is that *your* re-encode
  did not make it worse. Mine moved peaks by at most +0.026 (1.7%).

---

## 5. Writing the database

[`scripts/write_mixxx.py`](../scripts/write_mixxx.py). The core is small:

```python
HOTCUE, MAIN, INTRO, OUTRO = 1, 2, 6, 7
ENGINE_CHANNELS = 2

def engine_pos(seconds, samplerate):
    return int(round(seconds * samplerate * ENGINE_CHANNELS))

# delete only the cue types we manage, then rewrite
con.execute("DELETE FROM cues WHERE type IN (?,?,?,?) AND track_id IN (...)",
            (HOTCUE, MAIN, INTRO, OUTRO, *ids))

rows = [(tid, MAIN,  engine_pos(cin, sr),  0,                    -1, ""),
        (tid, INTRO, engine_pos(cin, sr),  0,                    -1, ""),
        (tid, OUTRO, engine_pos(cout, sr), engine_pos(fade, sr), -1, "")]
```

Deleting by type rather than by track leaves Mixxx's own `N60dBSound` analysis
cues intact. Clamp the out-point so `cue_out + fade` fits inside the file, or
AutoDJ will try to crossfade past the end.

### Relocating instead of rescanning

If a folder gets renamed between sessions — and it will — do not delete the rows
and rescan. Repoint them:

```python
UPDATE track_locations
   SET location = ?, directory = ?, fs_deleted = 0, needs_verification = 0
 WHERE id = ?
```

This preserves each track's `library.id`, and with it the BPM, the beatgrid, the
waveform analysis and the play history. On the real set this recovered 118
already-analysed tracks that would otherwise have needed a full re-analysis.
Rows whose files are genuinely gone get `fs_deleted = 1` rather than a `DELETE`,
so nothing dangles.

### Loading the AutoDJ queue

```python
con.execute("DELETE FROM PlaylistTracks WHERE playlist_id = 1")
con.executemany(
    "INSERT INTO PlaylistTracks(playlist_id, track_id, position, pl_datetime_added)"
    " VALUES (1,?,?,?)",
    [(tid, i + 1, now) for i, tid in enumerate(queue_ids)])
```

Note that AutoDJ **consumes** its queue: tracks are removed as they play. After a
rehearsal the queue will be short. Re-running the writer refills it.

---

## 6. Verify from the file on disk

Not from the thing you just computed in memory — from the database as it sits on
disk, and again after Mixxx has opened and closed it.
[`scripts/verify_mixxx.py`](../scripts/verify_mixxx.py) recomputes the running time
from the stored cues:

```
tracks checked : 77
running time   : 9000 s  (2:30:00)
integrity      : ok
problems       : none
```

9000 seconds from 17:00 is 19:30:00. That number is the deliverable — it was
derived from the cues Mixxx will actually read, not from the spreadsheet that
produced them.

The checks worth having, each of which has caught something real:

| Check | Catches |
|---|---|
| hotcues present on a queue track | an edit you think is automated and is not |
| `outro.length == 0` | AutoDJ silently falling back to the fixed crossfade |
| `outro.position + length > duration` | crossfade running past the end of the file |
| `intro.position != planned cue_in` | Mixxx or a rescan having moved something |
| AutoDJ queue vs set list | a half-consumed queue from a rehearsal |
| `library.duration` vs real file duration | audio re-rendered without updating the row |

The last one is easy to miss. After replacing a file out of band, Mixxx still
holds the old duration and the old waveform until something triggers
re-analysis — one of my edited tracks sat in the library as 6:45 when the file
on disk was 2:41. Update `library.duration` when you write, and re-analyse the
edited tracks in the GUI so the waveform matches.

---

## 7. Gotchas, collected

| | |
|---|---|
| Mixxx open while you write | your changes are overwritten on exit, with no error |
| `position` in seconds | silently wrong cues — it is `seconds × samplerate × 2` |
| `outro.length = 0` | out-point ignored, fixed crossfade used instead |
| Hotcues as automation | AutoDJ never presses them; render the edit instead |
| `acrossfade` and quantisation | the join eats `d` seconds; start B `d` earlier |
| `-c copy` for cuts | MP3 frames are not sample accurate; re-encode |
| Rescan after renaming a folder | loses BPM, beatgrid and history; relocate instead |
| Editing audio behind Mixxx's back | stale duration and waveform until re-analysed |
| Trimming the originals | cue points are per *track*; always work on copies |

---

## 8. Running it

```bash
# 1. Point Mixxx at both folders and let it scan and analyse. Then quit Mixxx.

# 2. Pull the track inventory out of Mixxx, then fill in genre and energy
python3 scripts/make_inventory.py ~/.mixxx/mixxxdb.sqlite ~/Music/Set > inventory.json

# 3. Draft the running order — see prompts/build-setlist.md — then check it
python3 scripts/check_setlist.py setlist.json inventory.json \
        --start 17:00 --end 19:30 --first "first.mp3" --last "last.mp3"

# 4. Render any internal edits
python3 scripts/render_edits.py edits.json ~/Music/Set ~/Music/Set-cut

# 5. Write cues and playlists  (Mixxx still closed)
cp ~/.mixxx/mixxxdb.sqlite ~/.mixxx/mixxxdb.backup.sqlite
python3 scripts/write_mixxx.py ~/.mixxx/mixxxdb.sqlite setlist.json

# 6. Verify against the file on disk
python3 scripts/verify_mixxx.py ~/.mixxx/mixxxdb.sqlite setlist.json

# 7. Open Mixxx, re-analyse any re-rendered tracks, enable Auto DJ.
```

Three worked examples ship with the repo and describe the same ten imaginary
tracks, so they read as one pipeline: [`examples/inventory.json`](../examples/inventory.json)
is what comes out of `make_inventory.py` with genre and energy filled in,
[`examples/setlist.json`](../examples/setlist.json) is what a model should hand you
back, and [`examples/edits.json`](../examples/edits.json) is the internal edit it
refers to. The set list validates clean against the inventory — `0 errors,
0 warnings, lands on the target to the second` — so you can run the validator on
them first and see what a pass looks like:

```bash
python3 scripts/check_setlist.py examples/setlist.json examples/inventory.json \
        --start 17:00 --end 17:15 \
        --first aurora-boulevard.mp3 --last gold-telephone.mp3
```

**Your own `inventory.json`, `setlist.json` and `edits.json` are gitignored.**
They list the filenames of your music, which is personal and of no use to
anyone else; keep them in the repo root and git will leave them alone. Anything
under `examples/` is always committed. Audio files and `*.sqlite` are ignored
too, so a stray copy of your Mixxx library cannot be pushed by accident.

`edits.json`:

```json
[{"file": "track.mp3", "cue_in": 0, "jump_from": 145,
  "jump_to": 285, "cue_out": 300, "bpm": 100, "fade": 1}]
```

`setlist.json`:

```json
{"root_cut":  "/home/you/Music/Set-cut",
 "root_full": "/home/you/Music/Set",
 "playlists": {"MY SET": "queue", "MY SET - SPARES": "spares"},
 "relocate":  [{"from": "/home/you/Music/Set-OLD",
                "to":   "/home/you/Music/Set-cut",
                "files": ["track.mp3"]}],
 "queue":  [{"file": "track.mp3", "cue_in": 0, "cue_out": 160, "fade": 4}],
 "spares": [{"file": "other.mp3"}]}
```

Useful while it runs: `Shift+F12` toggles AutoDJ, `Shift+F10` skips to the next
track, `Shift+F11` forces the crossfade immediately
([`res/keyboard/en_US.kbd.cfg`](https://github.com/mixxxdj/mixxx/blob/main/res/keyboard/en_US.kbd.cfg)).

---

## 9. The running order itself

Everything above is mechanism. How the 77 tracks were actually ordered — the
wall, genre rotation in runs of three to five, energy as a shape rather than a
ramp, why BPM decides the transition and not the order, and the rule about
freezing cut points once a human has approved them — is in
[`docs/set-design.md`](set-design.md).

The first draft of that order was produced by a language model, and the prompt
that does it is in [`prompts/build-setlist.md`](../prompts/build-setlist.md),
along with how to feed the validator's complaints back to it. A model is good at
holding a hundred tracks and a running total at once; it cannot hear your music,
so every cue point it gives you is a guess at song structure and needs checking
by ear. `check_setlist.py` catches the rest.

## 10. What I would tell myself at the start

**Find out what the automation can actually do before designing around it.** The
single biggest rework in this project came from assuming AutoDJ would honour
hotcues. Ten minutes in the manual would have saved rebuilding seven tracks.

**Keep the design as data and regenerate everything.** The running order changed
six or seven times. Each change was a rebuild and a re-verify, not an afternoon
of clicking. The one thing worth freezing is the per-track in/out points: once
they are approved, store them and never recompute them, so that reordering the
set cannot quietly move a cut someone already signed off.

**Verify by reading back, not by trusting the write.** Every number stated above
was recomputed from the database as it sat on disk. Twice that caught something
the write path was sure it had got right.

**Test the audio maths on a signal you control.** The 25 ms phase error was
invisible in every spot-check of real music and obvious within seconds on a
click track. If you are doing arithmetic on time, build a fixture where you know
the right answer.

---

## Licence

MIT. The scripts carry no warranty and will happily write nonsense into your
music library if you feed them nonsense — back up `mixxxdb.sqlite` first.
