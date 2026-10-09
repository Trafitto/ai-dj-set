#!/usr/bin/env python3
"""Dump a folder's tracks out of the Mixxx library as a planning inventory.

Mixxx has already analysed your music: it knows the BPM and the exact duration
of every file. That is precisely the input a set list needs, so take it from
there rather than re-deriving it.

    python3 make_inventory.py ~/.mixxx/mixxxdb.sqlite ~/Music/Set > inventory.json

Output is one object per track. `energy` and `genre` are yours to fill in or
correct — Mixxx's genre tag is whatever the file came with, and it has no
opinion at all about energy.
"""
import json, os, sqlite3, sys

def inventory(db_path, directory):
    con = sqlite3.connect(db_path)
    rows = con.execute("""
        SELECT tl.filename, l.artist, l.title, l.genre, l.bpm, l.duration
        FROM library l JOIN track_locations tl ON tl.id = l.location
        WHERE tl.directory = ?
          AND COALESCE(l.mixxx_deleted, 0) = 0
          AND COALESCE(tl.fs_deleted, 0) = 0
        ORDER BY l.artist, l.title""", (directory.rstrip("/"),)).fetchall()
    out = []
    for fn, artist, title, genre, bpm, dur in rows:
        out.append({
            "file": fn,
            "artist": artist or "",
            "title": title or os.path.splitext(fn)[0],
            "genre": genre or "",
            "bpm": round(bpm) if bpm else None,
            "duration": round(dur, 1) if dur else None,
            "energy": None,          # 1-10, fill in by hand
        })
    missing = [t["file"] for t in out if not t["bpm"] or not t["duration"]]
    if missing:
        print(f"warning: {len(missing)} track(s) not analysed yet "
              f"(select them in Mixxx and run Analyze): {missing[:5]}",
              file=sys.stderr)
    return out

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: make_inventory.py path/to/mixxxdb.sqlite MUSIC_DIR")
    print(json.dumps(inventory(sys.argv[1], sys.argv[2]), indent=1, ensure_ascii=False))
