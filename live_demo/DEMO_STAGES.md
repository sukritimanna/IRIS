# Demo stages: mock → real (unrecorded) → real with frames → mp4

Every stage uses the same command and the same page; only the campaign name and two flags change. Nothing from an
earlier stage is deleted; each stage has its own campaign folder under `$IRIS_AGENT/live_runs/`.

| stage | command (Carbon) | what is real | what you check |
|---|---|---|---|
| **1 Mock** (minutes) | `bash 03_record/start_demo_web.sh mock_$(date +%Y%m%d) --mock` | Claude intake, Materials Project download, FINDSYM + ISODISTORT (f1), f2, the graph, every gate, the executor loop, the page | the whole flow on screen: cards, timeline, board, plot. The page shows a **MOCK · fake VASP** badge; energies are synthetic (`tests/live_fakes/fake_vasp`), so numbers mean nothing |
| **2 Short real** (≈ 30 min) | `… short_$(date +%Y%m%d) --n-points 4 --part-size 4` | everything, one PBS job with 4 statics | INCAR/KPOINTS/POTCAR as intended, time per static, G4 passes on real OSZICAR/OUTCAR, the ΔE(λ) sign and size |
| **3 Full real, unrecorded** (1–2 h) | `… rehearsal_$(date +%Y%m%d)` then `… rehearsal_… ` again for T2, then `--network --part-size 3` for T3 (15-atom cell, 1 h walltime) | everything, 10 points, 2 PBS jobs per path | the three-path overlay, cross-setting check, no surprises |
| **4 Full real, frames** | `… batio3_$(date +%Y%m%d)` (T1), (T2), `--network --part-size 3` (T3) with `capture/snap_mac.sh` running on the Mac and `capture/snap_tmux.sh` on Carbon | everything | — |
| **5 Video** (Mac, later) | `bash 03_record/capture/make_video.sh ~/iris_demo_frames ~/iris_demo.mp4 --fps 10` | — | watch it once end to end |

Skip stage 3 if stage 2 was clean and you are short on Carbon time; never skip stage 1 or 2.

## Stage 1 in detail (tonight)
```bash
# Carbon
cd <your-scratch>/iris_live_demo_v2 && bash 03_record/start_demo_web.sh mock_$(date +%Y%m%d) --mock
# Mac
ssh -L 8765:localhost:8765 carbon          # second terminal, leave open
open http://localhost:8765                  # Chrome/Safari
```
Type: `Map the straight-line irrep path of BaTiO3 from cubic Pm-3m (221) to tetragonal P4mm (99), 10 points, PBEsol`
then `y`. Expect, in order: Intake card (`claude-sonnet-5-5`), verdict `needs_new_dft`, parent/child cards with real
mp-ids, run plan chips, `f1 Crystallographer` (1–3 min: FINDSYM + ISODISTORT), `G1 PASS 5/5`, `G2 PASS 4/4`, two mock
job parts in the jobs panel, `G3…G6 PASS`, the profile, `f6 N of N`. Then run T2 (`--mock` again, child 38) and
T3 (`--mock --network`, child 160) in the same mock campaign to see the overlay.

What a failure at stage 1 means: at Intake → key/credit/HTTPS to api.anthropic.com; at fetching → MP key/HTTPS;
at f1 → `iris/` package or iso.byu.edu (read `live_runs/<campaign>/<path>/isodistort/live_isodistort.log`);
at G1/G2 → a real crystallographic issue with the MP structures (send me the log + `03_data/*.json`).

## Stage 4: frames
- Mac, before typing the request: `bash 03_record/capture/snap_mac.sh ~/iris_demo_frames 2` in its own terminal, browser full-screen on the main display.
- Carbon, in a second ssh: `nohup bash 03_record/capture/snap_tmux.sh $IRIS_LIVE/recordings/frames_$(date +%Y%m%d) 2 iris >/dev/null 2>&1 &`
  (only if you also keep the tmux session with `start_demo.sh`; with the browser alone the Mac photos are the record).
- Stop the photo loop (Ctrl-C) after `f6` of T3 and after `stop_and_hash.sh`; keep the frames folder as the raw record.

## Stage 5: mp4
`make_video.sh` = ffmpeg, `-framerate 10` over 2-s photos = 20× real time. For a quieter cut: `--fps 4`, or drop
duplicate frames (`ffmpeg -i in.mp4 -vf mpdecimate,setpts=N/FRAME_RATE/TB out.mp4`). Title/end cards and speed
changes are a later editing step; the frames are not touched.
