#!/usr/bin/env python3
"""Check a set list against the music inventory before it touches Mixxx.

Written to be run on set lists produced by a language model, which will
confidently invent a filename, place a cue point past the end of a track, or
quietly lose four minutes against the target. None of that is visible by
reading the JSON; all of it is cheap to catch here.

    python3 check_setlist.py setlist.json inventory.json --start 17:00 --end 19:30

Exits non-zero if anything is wrong, so it can gate the write step.

One known looseness: for a `spliced` track the inventory still holds the
ORIGINAL duration, because that is what Mixxx analysed. The cue_out check is
therefore conservative for those rows — it will catch a cue past the original
end, but not one past the shorter edited file. `verify_mixxx.py` closes that gap
after the write, when the real duration is in the library.
"""
import argparse, json, sys
from datetime import datetime, timedelta

MAX_GENRE_RUN = 5          # longest allowed run of one genre
MIN_GENRE_RUN = 3          # shortest run worth committing to

def hhmm(s):
    return datetime.strptime(s, "%H:%M")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("setlist"); ap.add_argument("inventory")
    ap.add_argument("--start", default=None); ap.add_argument("--end", default=None)
    ap.add_argument("--tolerance", type=int, default=0,
                    help="seconds of slack allowed against the target end time")
    ap.add_argument("--first", default=None, help="filename that must come first")
    ap.add_argument("--last", default=None, help="filename that must come last")
    ap.add_argument("--banned", nargs="*", default=[],
                    help="artist names that must not appear")
    a = ap.parse_args()

    spec = json.load(open(a.setlist))
    inv = {t["file"]: t for t in json.load(open(a.inventory))}
    queue = spec["queue"]
    errors, warnings = [], []

    seen = set()
    total = 0.0
    for i, e in enumerate(queue):
        f = e["file"]
        t = inv.get(f)
        if t is None:
            errors.append(f"[{i}] not in inventory: {f}")
            continue
        if f in seen:
            errors.append(f"[{i}] duplicate: {f}")
        seen.add(f)

        dur = t["duration"]
        cin, cout, fade = e["cue_in"], e["cue_out"], e.get("fade", 0)
        if not 0 <= cin < cout:
            errors.append(f"[{i}] {f}: cue_in {cin} must be < cue_out {cout}")
        if cout > dur:
            errors.append(f"[{i}] {f}: cue_out {cout} past end of track ({dur}s)")
        elif cout + fade > dur:
            errors.append(f"[{i}] {f}: cue_out + fade ({cout + fade}) past end ({dur}s)")
        if fade <= 0:
            errors.append(f"[{i}] {f}: fade must be > 0 or AutoDJ ignores cue_out")
        if cout - cin < 45:
            warnings.append(f"[{i}] {f}: only {cout - cin:.0f}s on air")

        for b in a.banned:
            if b.lower() in (t.get("artist") or "").lower():
                errors.append(f"[{i}] banned artist present: {t['artist']}")
        total += cout - cin

    if a.first and (not queue or queue[0]["file"] != a.first):
        errors.append(f"first track must be {a.first}, got "
                      f"{queue[0]['file'] if queue else '(empty)'}")
    if a.last and (not queue or queue[-1]["file"] != a.last):
        errors.append(f"last track must be {a.last}, got "
                      f"{queue[-1]['file'] if queue else '(empty)'}")

    # genre rotation: runs of one genre should be MIN..MAX long
    genres = [(inv[e["file"]].get("genre") or "?") for e in queue if e["file"] in inv]
    run_start = 0
    for i in range(1, len(genres) + 1):
        if i == len(genres) or genres[i] != genres[run_start]:
            n = i - run_start
            if n > MAX_GENRE_RUN:
                warnings.append(f"run of {n} x {genres[run_start]!r} at position "
                                f"{run_start} (max {MAX_GENRE_RUN})")
            elif n < MIN_GENRE_RUN and genres[run_start] != "?":
                warnings.append(f"run of {n} x {genres[run_start]!r} at position "
                                f"{run_start} (min {MIN_GENRE_RUN})")
            run_start = i

    print(f"tracks       : {len(queue)}")
    print(f"running time : {total:.0f} s  ({timedelta(seconds=int(total))})")
    if a.start and a.end:
        target = (hhmm(a.end) - hhmm(a.start)).total_seconds()
        drift = total - target
        end_at = hhmm(a.start) + timedelta(seconds=total)
        print(f"target       : {target:.0f} s  -> ends {end_at.strftime('%H:%M:%S')} "
              f"({drift:+.0f} s)")
        if abs(drift) > a.tolerance:
            errors.append(f"off target by {drift:+.0f}s "
                          f"(tolerance {a.tolerance}s)")
    print("warnings     :", len(warnings))
    for w in warnings: print("   -", w)
    print("errors       :", len(errors))
    for e in errors: print("   !", e)
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
