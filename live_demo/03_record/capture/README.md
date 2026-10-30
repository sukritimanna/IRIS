# Capturing the demo as photos -> video

Two independent captures; run both. Either one alone is enough for the final video.

## 1. Mac: screen photos (what you asked for)
```bash
bash snap_mac.sh ~/iris_demo_frames 2        # one PNG every 2 s of the main display (Ctrl-C to stop)
bash make_video.sh ~/iris_demo_frames ~/iris_demo.mp4 --fps 10     # 2 s photos at 10 fps = 20x speed; --fps 2 for 4x
```
`screencapture` is built into macOS; `brew install ffmpeg` for the video step. Keep the browser (web chat) or Terminal full-screen on the
main display; for the terminal use 14-16 pt. The photos are the raw record (keep the folder); the mp4 is derived.

## 2. Carbon: terminal-exact snapshots (backup, survives an ssh drop, zero overhead)
```bash
# on Carbon, in a second ssh window, before you start the chat:
nohup bash snap_tmux.sh $IRIS_LIVE/recordings/frames_$(date +%Y%m%d) 2 iris > /dev/null 2>&1 &
```
It captures the text + colours of every pane of the tmux session `iris` every 2 s (`frame_000123.ans`) until the
session ends. Afterwards, on Carbon or the Mac:
```bash
python render_frames.py $IRIS_LIVE/recordings/frames_<date>          # .ans -> .png (Pillow)
bash make_video.sh $IRIS_LIVE/recordings/frames_<date> iris_demo_terminal.mp4 --fps 10
```
Tested here: a 4-point fake run with a walltime kill -> 15 frames -> mp4 (sample attached to the chat).

Speed: a real run has long quiet stretches (queue, VASP). Keep the 2 s cadence (small files) and choose the
playback speed at the ffmpeg step; or drop duplicate frames first: `ffmpeg -i in.mp4 -vf mpdecimate,setpts=N/FRAME_RATE/TB out.mp4`.
