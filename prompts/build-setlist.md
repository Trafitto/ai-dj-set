# The set-list prompt

Copy the block below into any capable chat model, fill in the four bracketed
sections, and attach your `inventory.json`. Output is a `setlist.json` that
[`check_setlist.py`](../scripts/check_setlist.py) can validate and
[`write_mixxx.py`](../scripts/write_mixxx.py) can write straight into Mixxx.

Produce the inventory first:

```bash
python3 scripts/make_inventory.py ~/.mixxx/mixxxdb.sqlite ~/Music/Set > inventory.json
# then fill in "genre" and "energy" (1-10) by hand — Mixxx guesses neither well
```

The reasoning behind every rule in the prompt is in
[`docs/set-design.md`](../docs/set-design.md). Read that before changing them,
because several look arbitrary and are not.

---

## The prompt

````text
You are helping me sequence a DJ set that will run unattended from a fixed start
time to a fixed end time. I will give you an inventory of tracks; you give me a
running order with per-track in/out points.

## My constraints

- Start: [17:00]              End: [19:30] — this is exact, not approximate
- Wall: at [19:00] [the bar closes and roughly half the guests leave]
- Occasion / room: [wedding reception, ~80 guests, mixed ages, daytime, indoors]
- First track must be: [exact filename from the inventory]
- Last track must be: [exact filename from the inventory]
- The peak of the night should land around: [18:00]
- Must play before the wall: [group dances; the heavy/metal block]
- Never include: [artist names, if any]
- Play whole, never cut: [filenames, if any]
- Cut hard to first-verse-plus-chorus only: [filenames, if any]

## The inventory

[paste inventory.json, or attach it]

Each entry has: file, artist, title, genre, bpm, duration (seconds), energy
(1-10). Use ONLY these files. Never invent a filename, and never alter one.

## How to sequence it

1. ARITHMETIC FIRST. Before proposing anything, state: total seconds available,
   number of tracks I have asked you to place, and the resulting average seconds
   per track. If that average means most tracks lose more than half their
   length, say so plainly and tell me how many tracks would be comfortable. Do
   not quietly drop tracks to make the numbers work.

2. ANCHORS ARE FIXED. First track, last track, anything I said to play whole,
   anything I said must fall before the wall. Build around them.

3. THE WALL. Everything that matters happens before it. Apply this test: if the
   music stopped at the wall, would every group of guests have had their moment?
   The time after the wall is a bonus, not part of the plan.

4. GENRE ROTATION. Runs of 3 to 5 tracks of one genre, then change. Never one
   long block per genre, and never alternate every track.

5. ENERGY IS A SHAPE. Build local dips so there is somewhere to rise from, and
   one designated peak at the time I named. Not a monotonic ramp.

6. BPM DECIDES THE TRANSITION, NOT THE ORDER. Order by energy and genre
   rotation. Then set each track's `fade` from the gap to the next track:

       |delta BPM| <= 4    blend          fade 8
       5 to 12             pitch or cut   fade 5
       13 to 35            hard cut       fade 3
       > 35                full stop      fade 2

   Treat a near 2:1 BPM relationship (e.g. 85 -> 170) as a blend, not a gap.

7. CUT POINTS. Give every track a role and cut accordingly:
       whole      - plays start to finish
       short      - intro plus first chorus, roughly 60-100 s
       singalong  - must END ON the chorus, never after it
       slow       - fade early, nobody misses the last 30 s of a ballad
   Anything already shorter than ~150 s plays whole.

8. LAND ON THE END TIME EXACTLY. Sum (cue_out - cue_in) across the queue. It
   must equal the available seconds. If you are over, take the difference from
   several tracks rather than gutting one, preferring slow numbers and tracks
   whose length you chose yourself. Show me the final sum.

9. SPARES. Any track from the inventory that did not make the queue goes in
   "spares". Nothing is silently discarded.

## What to give me

First, a short plan in prose: the acts of the night, where the peak falls, what
sits either side of the wall, and the arithmetic from step 1.

Then a JSON object in a fenced ```json block, in exactly this shape:

{
  "root_cut":  "[/home/me/Music/Set-cut]",
  "root_full": "[/home/me/Music/Set]",
  "playlists": {"[MY SET]": "queue", "[MY SET - SPARES]": "spares"},
  "queue": [
    {"file": "exact-name.mp3", "cue_in": 0, "cue_out": 142, "fade": 5,
     "role": "short", "genre": "Rock", "why": "one short line"}
  ],
  "spares": [{"file": "other.mp3"}]
}

cue_in, cue_out and fade are WHOLE SECONDS. cue_out must be <= that track's
duration, and cue_out + fade must also be <= its duration.

## Rules you must not break

- Use only filenames present in the inventory, spelled exactly.
- cue_out + fade never exceeds the track's duration.
- fade is never 0.
- No track appears twice.
- Every inventory track is either in "queue" or in "spares".
- The arithmetic in step 8 must actually add up. Compute it, do not estimate it.

## Be honest about the guessing

You cannot hear these files. Any cue point inside a track is inferred from where
sections usually fall, not from the audio. At the end, list every track whose
cue_out you are not confident about and say what you assumed — those are the
ones I will check by ear before anything plays.

## Before you answer

Re-read your own JSON and verify: the sum in step 8; no invented filenames; no
cue_out past a duration; no genre run longer than 5; the anchors in place. If
any check fails, fix it before replying.
````

---

## Feeding back the validator's output

`check_setlist.py` is the second half of the loop. When it reports problems,
paste them back verbatim:

```
The validator rejected the set list. Fix these and give me the corrected JSON:

[paste the errors block]
```

Two or three rounds is normal. Models are reliably bad at the running total and
reliably good at fixing it once they are shown the number.

## Changing the set later

Keep the conversation. Reordering is cheap — "move the group dances before
18:00 and rebalance" — but **cut points are not**, once a human has approved
them. Tell the model so:

```
Keep every cue_in and cue_out exactly as they are. Change only the order.
If that puts us off the end time, tell me and I will decide what to trim.
```

That one instruction is the conversational version of the frozen-cuts rule in
[`docs/set-design.md`](../docs/set-design.md#8-freeze-the-cuts-once-a-human-has-approved-them),
and it prevents the most expensive class of mistake: a reorder that quietly
moves a cut somebody already signed off.
