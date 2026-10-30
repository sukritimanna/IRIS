#!/usr/bin/env bash
# ON THE MAC. Screen photos every N seconds -> PNG frames -> later one mp4 with ffmpeg (make_video.sh).
# Uses macOS screencapture (no extra software). Captures the whole main display; keep the Terminal full-screen.
#   bash snap_mac.sh <out_dir> [interval_s=2]        Ctrl-C to stop
#   -x  no shutter sound   -t png   -C  no cursor   -D 1  main display
OUT="${1:?output folder}"; DT="${2:-2}"
mkdir -p "$OUT"; i=$(ls "$OUT" 2>/dev/null | wc -l | tr -d ' ')
echo "capturing every ${DT}s into $OUT (Ctrl-C to stop); start at frame $i"
while true; do
  screencapture -x -C -D 1 -t png "$OUT/$(printf 'frame_%06d.png' "$i")" && i=$((i+1))
  sleep "$DT"
done
