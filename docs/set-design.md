# Designing the running order

The other half of the project. [`mixxx-internals.md`](mixxx-internals.md) covers getting a set
into Mixxx; this covers deciding what the set *is* — and how to get a language
model to do the first draft of it for you, which is what actually happened here.

The worked example throughout is a wedding reception: 77 tracks, 17:00 to 19:30,
with the bar closing at 19:00.

---

## 1. Start from the clock, not from the music

Before choosing a single track, divide:

```
150 minutes available ÷ 77 tracks = 117 seconds per track
```

That number decides everything downstream. At 117 seconds, almost nothing plays
whole — a four-minute song loses half of itself. If that is not acceptable, the
track count is wrong, and it is far cheaper to find that out now than after
designing a running order.

Say the number out loud before you design. "117 seconds each" is a decision;
discovering it afterwards is a problem.

## 2. Anchors are constraints, not preferences

Some positions are fixed and everything else bends around them:

| Anchor | Why |
|---|---|
| first track | the first dance — it opens, nothing precedes it |
| last track | the one everyone should leave singing |
| a named clock time for the peak | agreed with the client in advance |
| anything the client insisted on | not yours to move |

Write these down before sequencing. Treat them as inputs to the problem.

## 3. The wall

If part of the audience leaves at a known time, that time is a wall, and
everything that matters goes before it.

Here the bar closed at 19:00 and the catering left: the older relatives,
families with children and anyone driving would go with them. So the group
dances, the peak and the heavy block were all placed before 19:00, and the
half hour after it was designed as a bonus rather than as part of the plan.

The test to apply: **if the music were switched off at the wall, would everyone
have had their moment?** If not, the order is wrong, however good it looks.

## 4. Rotate genres in runs of three to five

Not one block per genre, and not strict alternation.

- One genre for half an hour empties the floor of everyone who doesn't like it,
  and they do not come back.
- Alternating every track feels like a shuffle and never builds anything.
- **Three to five** is long enough to commit to a mood, short enough that nobody
  waits long for theirs.

With seven genres in rotation, nobody waits more than about ten minutes.

## 5. Energy is a shape, not a ramp

Rate every track 1–10. Then shape the sequence so it has:

- local dips, because you cannot rise from a plateau
- one designated peak, placed at the agreed clock time
- a slope into the peak that is built, not jumped to

A monotonic climb has nowhere left to go by the middle of the night, and the
last hour reads as decline.

## 6. BPM decides the transition, not the order

Order by energy and genre rotation. *Then* let the BPM gap between neighbours
decide how to get from one to the next — and how long the crossfade is, which is
the number written into the outro cue:

| \|Δ BPM\| | transition | fade |
|---|---|---|
| ≤ 4 | beatmatch and blend | 8 s |
| 5–12 | small pitch nudge, or a clean cut | 5 s |
| 13–35 | hard cut on the downbeat | 3 s |
| > 35 | full stop — let it end, then start | 2 s |

A 90 BPM gap is not a mixing problem to be solved; it is a moment of silence to
be used. Trying to blend across it is what sounds amateurish, not the gap.

Watch for double-time relationships: 85 and 170 BPM are a Δ of 85 by arithmetic
and a perfect blend by ear.

## 7. Per-track role decides the cut

Give every track a role, and let the role decide how it gets trimmed:

| Role | Treatment |
|---|---|
| `whole` | plays start to finish — anchors, and anything the client named |
| `short` | intro and first chorus, then out — typically 60–100 s |
| `spliced` | boring middle removed from the audio (see [mixxx-internals.md](mixxx-internals.md)) |
| `singalong` | cut so it ends *on* the chorus, never after it |
| `slow` | fades early; nobody notices a ballad ending 20 seconds sooner |

A useful rule: anything already under about 2:30 plays whole. Shaving 20 seconds
off a short rock'n'roll track buys nothing and costs the ending.

## 8. Freeze the cuts once a human has approved them

The single most valuable operational rule here.

Cue points get reviewed by someone who knows the music. The running order then
changes — six or seven times, in this case. If the cuts are recomputed on every
rebuild, a reorder silently moves a cut that somebody already signed off, and
nobody notices until it plays.

So: once approved, write the in/out points to their own file and **read them
back** rather than recomputing. Reordering can move tracks around freely; it can
never touch a cut.

```
design.py      running order, genres, roles      <- changes often
frozen_cuts.json   approved in/out points        <- changes only when asked
```

## 9. Land on the exact end time

Sum the on-air durations, compare to the target, and spread the difference over
several tracks rather than gutting one. Twenty seconds off six tracks is
invisible; two minutes off one is a different arrangement.

Take it from the places with the most slack: slow numbers near the end, and any
track where *you* chose the length rather than the client.

## 10. Keep a spares list

Not everything fits, and "cut from the set" should not mean "deleted". Tracks
that did not make the queue go into a second playlist, untrimmed. If nobody
leaves at the end, you load it and carry on.

---

## 11. Getting a language model to draft it

All of the above is a set of rules, and the tedious part — applying them across
a hundred tracks while keeping a running total — is exactly what a model is good
at. The draft it produces is worth having. What it produces *unchecked* is not.

**What it is good at:** holding the whole constraint set at once, keeping the
arithmetic honest, rotating genres without losing the energy shape, placing a
peak at a target time, and explaining why it ordered things the way it did.

**What it cannot do:** hear the music. Every cue point it gives you is inferred
from where choruses usually fall, not from your files. On this set, eight
cue-outs were placed at "the end of the first chorus" in a standard arrangement
— all eight needed checking by ear, and that was the single largest source of
error in the whole project.

**What it will do if you let it:** invent a filename that is almost right,
place a cue point past the end of a track, lose four minutes against the target
and not mention it. None of that is visible by reading the JSON. All of it is
caught in one second by [`check_setlist.py`](../scripts/check_setlist.py).

So the loop is:

```
make_inventory.py   ──>  inventory.json   (Mixxx already knows BPM and duration)
      │
      ├── you fill in genre and energy
      ▼
prompts/build-setlist.md  +  your constraints  ──>  model  ──>  setlist.json
      │
      ▼
check_setlist.py    ──>  errors? feed them back to the model, repeat
      │
      ▼
write_mixxx.py      ──>  mixxxdb.sqlite
```

The validator is not a formality. Treat a failing check as the model's output
being wrong, paste the errors back, and ask for a corrected set list. Two or
three rounds is normal, and it is much faster than reading 77 entries yourself.

This loop was tested end to end before publishing: a 40-track inventory and a
90-minute window handed to a model through the prompt unchanged, its JSON run
through `check_setlist.py` (0 errors, landing on the target to the second), then
through `write_mixxx.py` into a database and read back out again. It placed 29
tracks, held the anchors, kept the genre runs inside the limits, and flagged the
one constraint conflict it could not resolve instead of hiding it.

The prompt is in [`prompts/build-setlist.md`](../prompts/build-setlist.md).

---

## 12. What the model should never decide alone

- **Which tracks are in.** That is the client's taste, and a banned artist is
  banned for a reason you do not need to know.
- **The anchors.** First dance, last track, and anything named.
- **Whether a cut sounds right.** It is guessing at song structure. Listen.
- **Whether the arithmetic is acceptable.** 117 seconds a track is a fact; that
  it is *fine* is a judgement call, and a human makes it.
