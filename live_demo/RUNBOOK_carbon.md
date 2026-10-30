# IRIS live demo — everything on Carbon, the Mac only records

One host, one filesystem, no stored data. IRIS runs on the Carbon login node inside a tmux session; the VASP
statics are PBS jobs submitted by IRIS's live executor; the Mac shows that tmux session over ssh and records the
screen. Every artefact of the run — chat transcript, `audit.jsonl`, `iris.sqlite`, the LLM calls, the ISODISTORT
responses, the VASP folders, the energies — is written under `IRIS_AGENT/` on Carbon and hashed at the end.

## 0. What "live" means in the code (build summary)

`run.mode: live` (new, next to `skeleton` and `replay`). The graph, gates and recovery are the same code as the
manuscript's replay; only the three places that touched stored data now compute:

| node | replay (manuscript) | live (this demo) |
|---|---|---|
| f₀ Intake | config file / frozen LLM intake | same LLM intake (`intake/`), then `engines/mp_fetch.py` downloads parent and child from the Materials Project (`MP_API_KEY`), writes `live_inputs/<campaign>/<path>/{parent,child}.cif` + `provenance.json` |
| f₁ Crystallographer | reads stored ISODISTORT responses | `engines/live_iso.py` runs the staged walkthrough steps 0–3 (FINDSYM + **live ISODISTORT**, `iris/lib`) into `live_runs/<campaign>/<path>/isodistort/`; f₁ then reads those responses with the unchanged code |
| f₂ Path planner | compares with the stored `path.json` | no comparison (there is nothing stored); G2 still checks child metric, λ=1 = child, space groups, d_min |
| f₃ Runner | matches frames to stored POSCARs, waits for simulated job-end events | `nodes/f3_live.py` writes POSCAR/INCAR/KPOINTS per frame and waits; **`iris_agent.live_executor`** (second process) writes POTCAR + PBS scripts, `qsub`s them, watches `qstat`, collects OSZICAR/OUTCAR → `result.json`, `energies.csv`, `energies_summary.json`, and sends the real job-end event |
| f₄–f₆, G3–G6 | — | unchanged (they read the same layout) |

Recovery: `recovery_live.yaml` = `recovery.yaml` + one change — a NELM failure resubmits **every** point with robust
mixing (one INCAR along the path keeps G4 `dft_consistent`). WALLTIME resubmits only the unfinished frames. Both
were tested with a fake scheduler (`tests/test_live_mode.py`, 4 tests, ~4 s), as was the DFT_INCONSISTENT human
interrupt you get with the old per-part NELM fix.

Guard rails kept: `allow_live_submission: true` is refused unless `run.mode: live` (schema + f₃); IRIS writes only
under `agent_root` (`Paths.out`); keys only from the environment; nothing stored is read in live mode.

## 1. One-time setup on Carbon (≈ 30 min)

```bash
# on Carbon
mkdir -p <your-scratch>/iris_live && cd $_
git clone <your imhafo2 repo> imhafo2           # must contain demo/staged_walkthrough AND the iris/ package (iris/lib, iris/perovskite)
cp /path/to/iris_live_demo/00_setup/iris_env.template ~/.iris_env && chmod 600 ~/.iris_env && nano ~/.iris_env   # keys + paths
bash 01_patch/apply_patch.sh $IRIS_AGENT          # dry run: lists 18 new / 6 modified files
bash 01_patch/apply_patch.sh $IRIS_AGENT --go     # applies; every replaced file is kept as *.pre_live
nano $IRIS_AGENT/configs/live/_template_live.yaml  # the two EDIT lines: PBS "nodes=…" line, potcar_dir
bash 00_setup/setup_carbon.sh                     # conda env iris
bash 00_setup/check_carbon.sh                     # must end with ALL CHECKS PASS
```

`check_carbon.sh` verifies: keys set, patch applied, `iris/` importable, HTTPS to api.anthropic.com / iso.byu.edu /
api.materialsproject.org from the login node, modules + `vasp_std`, `qsub`/`qstat`, the three POTCARs, template
edited, tmux, the live-mode tests and the full IRIS suite (unchanged: 137 passed, 17 skipped + 4 new).

If HTTPS to iso.byu.edu or api.anthropic.com is blocked from the login node, the demo cannot be all-on-Carbon as
planned; tell me which host fails and we fall back to chat-on-Mac + executor-on-Carbon.

## 2. Validate the DFT settings (≈ 1 h of queue time, unrecorded)

`02_validate/vasp_checks/` (unchanged from the first kit): one PBEsol static of cubic BaTiO3 with the template
INCAR (ENCUT 600, EDIFF 1e-7, 8×8×8), and the lattice scan. Expect PBEsol a₀ ≈ 3.98–3.99 Å and a converged run in
well under the 2 h walltime. Note the time per static: it sets `part_size` (default 5 statics per PBS job).

## 3. Rehearse (unrecorded)

```bash
bash 02_validate/dry_run.sh "Map the straight-line irrep path of BaTiO3 from cubic Pm-3m (221) to tetragonal P4mm (99), 10 points, PBEsol" rehearsal
```
This runs the real f₀ (Claude intake) → Materials Project → **live ISODISTORT** → f₂ → f₃ inputs, then the executor
in dry-run writes POTCAR and the PBS scripts without submitting. Open
`test_runs/batio3_T1_221_99_live/f3_jobs/live/r0_p0.sh` and `live_runs/rehearsal/T1_221-99__lin10/L00/` and
check them by eye (header, module line, POTCAR order Ba Ti O, KPOINTS 8 8 8). Then one real unrecorded run:

```bash
rm -r $IRIS_AGENT/test_runs/batio3_T1_221_99_live $IRIS_AGENT/live_runs/rehearsal     # the dry-run thread
bash 02_validate/rehearsal_real.sh "<same request>" rehearsal
```
It should end with `G6 … PASS` and `f6: N of N reported numbers re-derived and equal`. Read
`test_runs/batio3_T1_221_99_live/chat_transcript.md` — that is exactly what the recording will show.

## 4. Recording day

Two surfaces, same pipeline and same files. **Browser (recommended for the video):**
```bash
# Carbon
bash 03_record/start_demo_web.sh batio3_$(date +%Y%m%d)           # add --n-points 4 --part-size 4 for the short run, --network for T3
# Mac
ssh -L 8765:localhost:8765 carbon        # leave open; then http://localhost:8765 full-screen, start capture/snap_mac.sh
```
Left: chat bubbles (your request, IRIS, the expert menu as buttons). Right: f0–f6 board with G0–G6 badges and test
counts, run plan, PBS job parts (ids, status, WALLTIME/NELM codes), the dE(λ) profile with the barrier marked, the
f6 count, and every gate test. The terminal version below is the fallback (tmux, also recordable).

**Terminal:**

**On Carbon**
```bash
bash 03_record/start_demo.sh batio3_$(date +%Y%m%d)     # tmux session "iris": left pane chat, right pane qstat + executor log
```
**On the Mac**: full-screen Terminal, `ssh carbon -t 'tmux attach -t iris'`, start the screen recording
(QuickTime ▸ File ▸ New Screen Recording, or ⌘⇧5), then in the left pane type:

```bash
python -m iris_agent.chat --campaign batio3_20261103 --llm claude-sonnet --executor
```
and at the prompt type the request. What happens on screen, in order (times for 5-atom cells on one node):

1. `intake (claude-sonnet-5-5): system=new, formula=BaTiO3, parent_sg=221, child_sg=99, analysis=path …` + sources + `verdict: needs_new_dft` (≈ 5 s)
2. `fetching BaTiO3 #221 and #99 from the Materials Project` → two lines with mp-ids, cells, E above hull (≈ 5 s)
3. `config written …`, `plan: 10 frames T1 #221 -> #99, 1 f.u./cell, k-mesh [8, 8, 8], ENCUT 600, 5 statics per PBS job, submit with 'qsub'`, `run it? [y/N]` → **y**
4. `f0 Intake starts` … `G0 (intake): PASS, 11/11 tests`
5. `f1 Crystallographer starts` — FINDSYM + live ISODISTORT (≈ 1–3 min; the raw responses land in `live_runs/…/isodistort/`) → `G1 (decomposition): PASS, 5/5 tests`
6. `f2 Path Planner starts` → `G2 (path plan): PASS, 4/4 tests`
7. `f3 Runner starts` → `f3 waiting for 2 of 2 job parts` — right pane: two PBS jobs appear in `qstat`, then the executor log lines `round 0 part 0: 5 frames submitted as <id>`
8. queue + 10 statics (≈ 10–40 min) → `round 0 part 0 ended (all frames finished)` … `sent {"event": "job_end", …}`
9. `G3 PASS` → `f4 Reviewer` `G4 (energies): PASS, 4/4` → `f5` `G5 PASS` → `f6` `G6 PASS`
10. `profile dE(lambda) meV/f.u.: […]`, `barrier … meV/f.u. at lambda = …`, `f6: 6x of 6x reported numbers re-derived and equal`, `files: …`

Then, still recording, paths **T2** (→ Amm2 #38) and **T3** (→ R3m #160) with the same command plus `--network`
on T3: f₅ then checks that the cubic λ=0 energy per f.u. agrees across the three cells (`G5 (profile): PASS, 3/3`).

Branches you may see (all are IRIS doing its job, keep recording):
- a part killed by walltime → `G4 FAIL WALLTIME` → `recover (rule): f4_walltime_resubmit -> f3` → only the unfinished frames are resubmitted;
- NELM hit → `G4 FAIL NELM` → `recover (rule): f4_nelm_robust_mixing_all -> f3` → all 10 points resubmitted with AMIX/BMIX, G4 passes;
- anything the rules and sub-agent do not settle → `a decision is needed` + menu → you (the human expert) type the option id.

**After**: `Ctrl-b d` is NOT needed — leave the panes; on Carbon run
```bash
bash 03_record/stop_and_hash.sh batio3_20261103     # MANIFEST.sha256 of every produced file
bash 04_archive/archive.sh batio3_20261103          # one tarball + its sha256, scp to the Mac
```
Stop the Mac recording last.

## 5. Where everything is saved (all under `$IRIS_AGENT/`)

```
live_inputs/<campaign>/T1/{parent.cif, child.cif, system.json, provenance.json}   Materials Project download + provenance
live_runs/<campaign>/T1_221-99__lin10/isodistort/…/step3_isodistort/04_raw_isodistort/   raw FINDSYM/ISODISTORT responses, live_isodistort.log
live_runs/<campaign>/T1_221-99__lin10/L00..L09/{POSCAR,INCAR,KPOINTS,POTCAR,OSZICAR,OUTCAR,vasp.out,result.json,frame.json}
live_runs/<campaign>/{energies.csv, energies_summary.json, MANIFEST.sha256}
test_runs/batio3_T1_221_99_live/{config.yaml, chat_transcript.md, audit.jsonl, iris.sqlite, llm_calls.jsonl,
                                 f3_jobs/{submission*.json, live_state.json, live_executor.log, live/r*_p*.sh}}
```

## 6. Known limits (say them, don't hide them)

- Live mode covers the straight-line path analysis (the HfO2-type campaign); plane / 6D grids stay replay.
- f₁ live needs `iris/lib` + `iris/perovskite` on Carbon and HTTPS to iso.byu.edu; FINDSYM/ISODISTORT are external services.
- The chat's intake uses the frozen `intake/` library; a BaTiO3 request resolves to `needs_new_dft`, which is the live trigger (recorded in `config.intake.frozen_status`).
- The three cells (5, 10, 15 atoms) use different k-meshes; the cross-setting tolerance is 1 meV/f.u. (the stored HfO2 collector's value).
