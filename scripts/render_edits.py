#!/usr/bin/env python3
"""Render bar-quantised internal edits to audio files.

AutoDJ cannot skip a region in the middle of a track, so any such edit has to
exist in the audio itself. This renders one output file per edit:

    [cue_in .. jump_from] + [jump_to .. cue_out + fade]

`jump_to` is snapped so that the removed span is a whole number of bars at the
track's BPM. That keeps the beat phase identical across the splice: the first
beat after the join lands exactly where it would have landed without the cut.

Segment B starts XFADE *before* `jump_to`, not at it. ffmpeg's `acrossfade`
consumes `d` seconds of output (it overlaps the tail of A with the head of B),
so without that compensation everything after the join arrives `d` seconds
early and the bar quantisation is silently undone. Pulling B back by exactly
`d` restores sample-accurate phase.

The `fade` seconds kept past `cue_out` are the tail AutoDJ crossfades under the
incoming track; without them the outgoing track would be cut short by `fade`.
"""
import json, math, os, subprocess, sys

XFADE = 0.025   # join crossfade, below the audible threshold, kills the click
TAIL_FADE = 0.015

def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)

def snap_to_bars(jump_from, jump_to, bpm, beats_per_bar=4):
    """Return jump_to adjusted so the removed span is a whole number of bars."""
    bar = beats_per_bar * 60.0 / bpm
    bars = max(1, round((jump_to - jump_from) / bar))
    return jump_from + bars * bar, bars

def render(src, dst, cue_in, jump_from, jump_to, cue_out, bpm, fade):
    full = probe_duration(src)
    jump_to, bars = snap_to_bars(jump_from, jump_to, bpm)
    if not (cue_in < jump_from < jump_to < cue_out <= full):
        raise ValueError(f"edit points out of order for {src}")
    start_b = jump_to - XFADE            # compensa l'accorciamento di acrossfade
    end_b = min(cue_out + fade, full)
    if start_b <= cue_in:
        raise ValueError(f"jump_to too close to start for {src}")
    new_dur = (jump_from - cue_in) + (end_b - start_b) - XFADE
    out_at = (jump_from - cue_in) + (cue_out - jump_to)

    flt = (
        f"[0:a]asplit=2[x][y];"
        f"[x]atrim=start={cue_in}:end={jump_from},asetpts=N/SR/TB[A];"
        f"[y]atrim=start={start_b:.6f}:end={end_b:.6f},asetpts=N/SR/TB[B];"
        f"[A][B]acrossfade=d={XFADE}:c1=tri:c2=tri[m];"
        f"[m]afade=t=out:st={max(new_dur - TAIL_FADE, 0):.6f}:d={TAIL_FADE}[o]"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src,
         "-filter_complex", flt, "-map", "[o]",
         "-map_metadata", "0", "-id3v2_version", "3",
         "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100", "-ac", "2", dst],
        check=True)

    real = probe_duration(dst)
    return {"file": os.path.basename(dst), "bars_removed": bars,
            "duration": round(real, 3), "outro_at": round(out_at, 3),
            "tail": round(real - out_at, 3)}

def main(spec_path, src_dir, dst_dir):
    spec = json.load(open(spec_path))
    os.makedirs(dst_dir, exist_ok=True)
    report = []
    for e in spec:
        src = os.path.join(src_dir, e["file"])
        dst = os.path.join(dst_dir, e["file"])
        report.append(render(src, dst, e["cue_in"], e["jump_from"],
                             e["jump_to"], e["cue_out"], e["bpm"], e["fade"]))
    print(json.dumps(report, indent=2))
    return report

if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: render_edits.py edits.json SRC_DIR DST_DIR")
    main(*sys.argv[1:])
