#!/usr/bin/env bash
# ON CARBON (inside or outside the session). Terminal-exact snapshots of the tmux session every N seconds:
# the visible text WITH colours (ANSI) of every pane, as .ans files. Independent of the Mac: survives an ssh drop,
# zero overhead, pixel-exact when rendered with render_frames.py -> PNG -> make_video.sh.
#   bash snap_tmux.sh <out_dir> [interval_s=2] [session=iris]      Ctrl-C to stop (or run under nohup)
OUT="${1:?output folder}"; DT="${2:-2}"; S="${3:-iris}"
mkdir -p "$OUT"; i=$(ls "$OUT"/*.ans 2>/dev/null | wc -l)
echo "snapshotting tmux session $S every ${DT}s into $OUT"
while tmux has-session -t "$S" 2>/dev/null; do
  f="$OUT/$(printf 'frame_%06d' "$i")"
  { for p in $(tmux list-panes -t "$S" -F '#{pane_id}'); do
      echo "@@PANE $p $(tmux display -p -t "$p" '#{pane_width} #{pane_height} #{pane_left} #{pane_top}')"
      tmux capture-pane -e -p -t "$p"
    done; } > "$f.ans"
  i=$((i+1)); sleep "$DT"
done
echo "session $S gone; $i frames in $OUT"
