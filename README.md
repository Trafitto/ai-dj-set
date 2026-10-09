# How I saved money by using Claude as the DJ at my wedding

The "DJ" was a laptop running [Mixxx](https://mixxx.org) on AutoDJ.
Claude did the creative part: the running order, where to cut each song, and
how long each crossfade lasts. I made the taste calls and listened to the cuts.

The brief:

- 🎵 **77 tracks**
- ⏰ **17:00 → 19:30**, hard stop, because the caterer said so
- 💍 **nobody touches the laptop**, because the two people who cared most were busy getting married

The plan landed on 19:30:00, to the second.

This repo packages that up so **your** Claude can do the same for your party.

## What you need

- [Claude Code](https://claude.com/claude-code)
- [Mixxx](https://mixxx.org) 2.5, Python 3 and `ffmpeg`
- A folder of songs, and an idea of when the music starts and stops

## How to do it

**1. Clone the repo and open Claude in it.**

```bash
git clone <this repo> && cd ai-dj-set && claude
```

Claude reads [`CLAUDE.md`](CLAUDE.md) and already knows the workflow, the rules
and the scripts.

**2. Tell it about your party.** Something like:

> I'm getting married on June 14. Music runs from 17:00 to 19:30, and the bar
> closes at 19:00. My songs are in `~/Music/Wedding`. Open with "Aurora
> Boulevard", close with "Gold Telephone", group dances before 18:00, and no
> Coldplay, please.

Whatever you leave out, Claude will ask about.

**3. Check its homework.** Along the way Claude will:

- guess the **genre and energy** of every song. Correct anything it got wrong.
- tell you the **arithmetic**, e.g. "77 tracks in 150 minutes is 117 seconds
  each". If that's too brutal, cut tracks.
- give you a **plan in plain words**, then the full set list, already checked
  by [`check_setlist.py`](scripts/check_setlist.py).
- list the **cut points it isn't sure about**. Claude can't hear your music,
  so listen to those. This is the most important step.

**4. Change your mind as often as you like.**

> Move the group dances earlier, keep every cut you've already approved.

Reordering is cheap. Approved cuts never move unless you ask.

**5. Let it write the set into Mixxx.** Claude asks first, backs up your library,
writes the cue points and the AutoDJ queue, then reads everything back to check
it still ends on time.

**6. Open Mixxx, turn on AutoDJ, go get married.**

Panic buttons during the party: `Shift+F12` toggles AutoDJ, `Shift+F10` skips
a track, and `Shift+F11` crossfades right away.

## No Claude Code?

Use any chat with Claude. Paste the prompt from
[`prompts/build-setlist.md`](prompts/build-setlist.md) and attach your
`inventory.json`. You'll run the scripts yourself and paste the validator's
complaints back. That page explains how.

## Things I learned the hard way

- **Claude can't hear your music.** Every cut point it gives you is an educated guess, so listen before the big day.
- **Freeze the cuts you've approved.** Otherwise a reorder can quietly move a cut you already checked.
- **AutoDJ never presses hotcues.** To skip a guitar solo, cut it out of the audio file. Claude does that for you.
- **Close Mixxx before anything writes to its library.** If it's open, it overwrites your changes on exit and doesn't tell you.
- **Never touch the originals.** Everything happens on a copy of your music folder.

## The nerdy details

- [`docs/set-design.md`](docs/set-design.md): what makes a set work (the wall, genre runs, energy shape)
- [`prompts/build-setlist.md`](prompts/build-setlist.md): the rules Claude follows
- [`docs/mixxx-internals.md`](docs/mixxx-internals.md): Mixxx's database, AutoDJ quirks, bar-aligned edits, and the 25 ms bug
- [`examples/`](examples/): a ten-track inventory and set list that pass the checker

Your `inventory.json`, `setlist.json` and `edits.json` are gitignored, and so
are audio files and `*.sqlite`. Your music stays yours.

## Licence

MIT. Claude backs up your Mixxx library before writing, but keep your own
backup too.
