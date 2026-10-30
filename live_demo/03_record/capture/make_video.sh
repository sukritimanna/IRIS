#!/usr/bin/env bash
# Frames -> mp4 (ffmpeg). 2 s photos played at 10 fps = 20x speed; use --fps 1 for 2x, etc.
#   bash make_video.sh <frames_dir> <out.mp4> [--fps 10] [--scale 1920]
#   brew install ffmpeg   (Mac)   |   module load ffmpeg / conda install -c conda-forge ffmpeg (Carbon)
set -e
IN="${1:?frames dir}"; OUT="${2:?out.mp4}"; shift 2
FPS=10; SCALE=1920
while [ $# -gt 0 ]; do case "$1" in --fps) FPS="$2"; shift 2;; --scale) SCALE="$2"; shift 2;; *) shift;; esac; done
ffmpeg -y -framerate "$FPS" -pattern_type glob -i "$IN/frame_*.png" \
  -vf "scale=$SCALE:-2:flags=lanczos,format=yuv420p" -c:v libx264 -crf 20 -movflags +faststart "$OUT"
echo "$(ls "$IN"/frame_*.png | wc -l) frames -> $OUT at $FPS fps"
