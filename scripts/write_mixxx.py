#!/usr/bin/env python3
"""Write cue points and playlists straight into Mixxx's SQLite library.

Mixxx must be CLOSED. It holds the library in memory and flushes on exit, so a
write made while it runs is overwritten without warning.

Input is a JSON set list:

    {"root_cut":  "/home/you/Music/Set-cut",
     "root_full": "/home/you/Music/Set",
     "playlists": {"MY SET": "queue", "MY SET - SPARES": "spares"},
     "queue":  [{"file": "a.mp3", "cue_in": 0, "cue_out": 142, "fade": 5}, ...],
     "spares": [{"file": "z.mp3"}, ...]}

cue_in/cue_out/fade are seconds. Every queue entry gets MainCue + Intro at
cue_in and Outro at cue_out with length `fade`. Spares are listed from
root_full and get no cues at all.
"""
import json, os, sqlite3, sys
from datetime import datetime

# src/track/cueinfo.h
HOTCUE, MAIN, INTRO, OUTRO = 1, 2, 6, 7
MANAGED_CUE_TYPES = (HOTCUE, MAIN, INTRO, OUTRO)
AUTODJ_PLAYLIST_ID = 1          # Mixxx's Auto DJ queue is the hidden playlist id 1
ENGINE_CHANNELS = 2             # mixxx::kEngineChannelOutputCount == stereo

def engine_pos(seconds, samplerate):
    """cues.position/length are engine sample positions: frames * channels."""
    return int(round(seconds * samplerate * ENGINE_CHANNELS))

def index_library(con):
    """location -> (track_id, duration, samplerate)"""
    rows = con.execute("""
        SELECT l.id, tl.location, l.duration, l.samplerate
        FROM library l JOIN track_locations tl ON tl.id = l.location
        WHERE COALESCE(l.mixxx_deleted, 0) = 0""").fetchall()
    return {loc: (tid, dur, sr or 44100) for tid, loc, dur, sr in rows}

def relocate(con, old_dir, new_dir, keep_filenames):
    """Repoint rows from a directory that was renamed or moved.

    Preserves each track's id, so BPM, beatgrid and play history survive.
    Files not in keep_filenames are flagged missing instead of deleted.
    """
    old_dir, new_dir = old_dir.rstrip("/"), new_dir.rstrip("/")
    moved = missing = 0
    for tl_id, fname in con.execute(
            "SELECT id, filename FROM track_locations WHERE directory = ?",
            (old_dir,)).fetchall():
        if fname in keep_filenames:
            con.execute("""UPDATE track_locations
                           SET location = ?, directory = ?, fs_deleted = 0,
                               needs_verification = 0
                           WHERE id = ?""",
                        (f"{new_dir}/{fname}", new_dir, tl_id))
            moved += 1
        else:
            con.execute("UPDATE track_locations SET fs_deleted = 1 WHERE id = ?", (tl_id,))
            missing += 1
    return moved, missing

def write_cues(con, lib, root, entries):
    ids = []
    for e in entries:
        loc = os.path.join(root, e["file"])
        if loc not in lib:
            raise KeyError(f"not in Mixxx library (scan the folder first): {loc}")
        ids.append(lib[loc][0])
    con.execute("DELETE FROM cues WHERE type IN (%s) AND track_id IN (%s)"
                % (",".join("?" * len(MANAGED_CUE_TYPES)), ",".join("?" * len(ids))),
                (*MANAGED_CUE_TYPES, *ids))

    written = 0
    for e in entries:
        tid, dur, sr = lib[os.path.join(root, e["file"])]
        cin, cout, fade = e["cue_in"], min(e["cue_out"], dur), e.get("fade", 0)
        if cout + fade > dur:                   # the outro must fit inside the file
            cout = max(dur - fade, 1)
        if not 0 <= cin < cout:
            raise ValueError(f"bad cue range for {e['file']}: {cin}..{cout}")
        rows = [(tid, MAIN,  engine_pos(cin, sr),  0,                     -1, ""),
                (tid, INTRO, engine_pos(cin, sr),  0,                     -1, ""),
                (tid, OUTRO, engine_pos(cout, sr), engine_pos(fade, sr),  -1, "")]
        con.executemany("""INSERT INTO cues(track_id, type, position, length, hotcue, label)
                           VALUES (?,?,?,?,?,?)""", rows)
        con.execute("UPDATE library SET cuepoint = ? WHERE id = ?",
                    (engine_pos(cin, sr), tid))
        written += len(rows)
    return ids, written

def put_playlist(con, name, track_ids, now):
    con.execute("""DELETE FROM PlaylistTracks WHERE playlist_id IN
                   (SELECT id FROM Playlists WHERE name = ? AND hidden = 0)""", (name,))
    con.execute("DELETE FROM Playlists WHERE name = ? AND hidden = 0", (name,))
    pos = (con.execute("SELECT COALESCE(MAX(position), 0) FROM Playlists").fetchone()[0] or 0) + 1
    cur = con.execute("""INSERT INTO Playlists(name, position, hidden, date_created,
                                               date_modified, locked)
                         VALUES (?,?,0,?,?,0)""", (name, pos, now, now))
    pid = cur.lastrowid
    con.executemany("""INSERT INTO PlaylistTracks(playlist_id, track_id, position,
                                                  pl_datetime_added)
                       VALUES (?,?,?,?)""",
                    [(pid, t, i + 1, now) for i, t in enumerate(track_ids)])
    return pid

def fill_autodj(con, track_ids, now):
    con.execute("DELETE FROM PlaylistTracks WHERE playlist_id = ?", (AUTODJ_PLAYLIST_ID,))
    con.executemany("""INSERT INTO PlaylistTracks(playlist_id, track_id, position,
                                                  pl_datetime_added)
                       VALUES (?,?,?,?)""",
                    [(AUTODJ_PLAYLIST_ID, t, i + 1, now) for i, t in enumerate(track_ids)])

def main(db_path, spec_path):
    spec = json.load(open(spec_path))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = OFF")

    for mv in spec.get("relocate", []):
        moved, missing = relocate(con, mv["from"], mv["to"], set(mv["files"]))
        print(f"relocated {moved}, flagged missing {missing}")

    lib = index_library(con)
    queue_ids, ncues = write_cues(con, lib, spec["root_cut"], spec["queue"])
    print(f"cues written: {ncues} over {len(queue_ids)} tracks")

    names = {v: k for k, v in spec["playlists"].items()}
    if "queue" in names:
        put_playlist(con, names["queue"], queue_ids, now)
    if "spares" in names and spec.get("spares"):
        spare_ids = [lib[os.path.join(spec["root_full"], e["file"])][0]
                     for e in spec["spares"]]
        put_playlist(con, names["spares"], spare_ids, now)
    fill_autodj(con, queue_ids, now)

    con.commit()
    print("integrity:", con.execute("PRAGMA integrity_check").fetchone()[0])
    for pid, nm in con.execute(
            "SELECT id, name FROM Playlists WHERE hidden = 0 OR id = 1 ORDER BY id"):
        n = con.execute("SELECT COUNT(*) FROM PlaylistTracks WHERE playlist_id = ?",
                        (pid,)).fetchone()[0]
        print(f"  {pid:3} {nm:<40} {n:4}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: write_mixxx.py path/to/mixxxdb.sqlite setlist.json")
    main(*sys.argv[1:])
