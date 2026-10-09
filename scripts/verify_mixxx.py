#!/usr/bin/env python3
"""Read the set back out of the database and check it against the set list.

Run this against the database file as it sits on disk, after writing it and
again after Mixxx has opened and closed, so that anything Mixxx changed shows
up. Prints the total running time implied by the cues, which is the number
worth caring about: it is what the set will actually last.
"""
import json, os, sqlite3, sys
from datetime import timedelta

HOTCUE, MAIN, INTRO, OUTRO = 1, 2, 6, 7
ENGINE_CHANNELS = 2

def main(db_path, spec_path):
    spec = json.load(open(spec_path))
    con = sqlite3.connect(db_path)
    problems, total = [], 0.0

    for e in spec["queue"]:
        loc = os.path.join(spec["root_cut"], e["file"])
        row = con.execute("""SELECT l.id, l.duration, l.samplerate
                             FROM library l JOIN track_locations tl ON tl.id = l.location
                             WHERE tl.location = ?""", (loc,)).fetchone()
        if not row:
            problems.append(("missing from library", e["file"])); continue
        tid, dur, sr = row
        k = (sr or 44100) * ENGINE_CHANNELS
        cues = {t: (p / k, l / k) for t, p, l in con.execute(
            "SELECT type, position, length FROM cues WHERE track_id = ?", (tid,))}

        if INTRO not in cues or OUTRO not in cues:
            problems.append(("intro/outro missing", e["file"])); continue
        cin, _ = cues[INTRO]
        cout, fade = cues[OUTRO]
        if con.execute("SELECT COUNT(*) FROM cues WHERE track_id = ? AND type = ?",
                       (tid, HOTCUE)).fetchone()[0]:
            problems.append(("stray hotcue — AutoDJ will ignore it", e["file"]))
        if abs(cin - e["cue_in"]) > 0.01:
            problems.append(("intro moved", e["file"], round(cin, 2)))
        if cout + fade > dur + 0.02:
            problems.append(("outro + fade runs past end of file", e["file"]))
        if fade <= 0:
            problems.append(("outro length 0 — AutoDJ falls back to the fixed crossfade",
                             e["file"]))
        total += cout - cin

    order = [r[0] for r in con.execute("""
        SELECT tl.filename FROM PlaylistTracks pt
        JOIN library l ON l.id = pt.track_id
        JOIN track_locations tl ON tl.id = l.location
        WHERE pt.playlist_id = 1 ORDER BY pt.position""")]
    if order != [e["file"] for e in spec["queue"]]:
        problems.append(("Auto DJ queue does not match the set list",
                         f"{len(order)} vs {len(spec['queue'])}"))

    print(f"tracks checked : {len(spec['queue'])}")
    print(f"running time   : {total:.0f} s  ({timedelta(seconds=int(total))})")
    print(f"integrity      : {con.execute('PRAGMA integrity_check').fetchone()[0]}")
    print("problems       :", problems if problems else "none")
    return 1 if problems else 0

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: verify_mixxx.py path/to/mixxxdb.sqlite setlist.json")
    sys.exit(main(*sys.argv[1:]))
