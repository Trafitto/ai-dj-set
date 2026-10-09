# Building a DJ set

This repo turns a folder of music into a Mixxx AutoDJ set that runs unattended
from a fixed start time to a fixed end time. The person you're talking to is
probably not a DJ and maybe not technical. You do the work; they make the taste
calls.

The rules for a good set are in [`prompts/build-setlist.md`](prompts/build-setlist.md),
and the reasoning behind them is in [`docs/set-design.md`](docs/set-design.md).
The Mixxx details are in [`docs/mixxx-internals.md`](docs/mixxx-internals.md).
Read whichever one the current step needs.

## The workflow

1. **Get the brief.** Ask for anything that's missing: the music folder, start
   and end time, the "wall" (when most people leave), first and last track,
   when the peak should land, must-plays, bans and tracks to play whole. Never
   guess an anchor.
2. **Set up the folders.** Copy the music folder to `<folder>-cut`. Only the
   copy is ever modified. Ask the user to point Mixxx at both folders, let it
   analyse them, then quit Mixxx.
3. **Build the inventory.** Run
   `python3 scripts/make_inventory.py ~/.mixxx/mixxxdb.sqlite <folder> > inventory.json`.
   Propose a genre and an energy level (1–10) for every track based on artist
   and title. Show the result as a table and let the user correct it.
4. **Do the arithmetic out loud.** Work out the average seconds per track
   before designing anything. If most tracks would lose more than half their
   length, say so and let the user decide.
5. **Draft `setlist.json`** following every rule in `prompts/build-setlist.md`.
   Show a short plan in prose first: the acts of the night, the peak, and what
   falls either side of the wall.
6. **Validate until it passes.** Run
   `python3 scripts/check_setlist.py setlist.json inventory.json --start HH:MM --end HH:MM --first <file> --last <file>`.
   Fix the set and re-run until it reports 0 errors. Never show the user a set
   that fails the check.
7. **Ear check.** List every `cue_out` you aren't confident about, with what you
   assumed. The user listens to those and approves them. **After approval the
   cuts are frozen.** On later reorders, keep `cue_in` and `cue_out` unchanged
   unless the user asks for a change.
8. **Internal edits.** Tracks whose middle should be removed get role `spliced`
   and an entry in `edits.json`. Render them with
   `python3 scripts/render_edits.py edits.json <folder> <folder>-cut`, then
   have the user open Mixxx, re-analyse those tracks and quit Mixxx again.
9. **Write to Mixxx, but ask first.** Confirm Mixxx is closed. Back up the
   library with `cp ~/.mixxx/mixxxdb.sqlite ~/.mixxx/mixxxdb.backup-$(date +%s).sqlite`.
   Then run `python3 scripts/write_mixxx.py ~/.mixxx/mixxxdb.sqlite setlist.json`
   and `python3 scripts/verify_mixxx.py ~/.mixxx/mixxxdb.sqlite setlist.json`.
   Report the running time `verify_mixxx.py` prints.
10. **AutoDJ settings.** With Mixxx closed, `~/.mixxx/mixxx.cfg` needs
    `TransitionMode 1` and `Requeue 0` under `[Auto DJ]`. Ask before editing it.

## Hard rules

- Never modify the original music folder.
- Never write to `mixxxdb.sqlite` while Mixxx is running, or without a fresh
  backup.
- Never invent a filename or change its spelling.
- The user decides which tracks are in, the anchors, whether a cut sounds right,
  and whether the arithmetic is acceptable.
- Keep `inventory.json`, `setlist.json` and `edits.json` in the repo root,
  where they are gitignored.
