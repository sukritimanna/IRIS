# IRIS — an agentic eye on symmetry-derived paths and energy landscapes of structural phase transitions

Code, evaluation set and results for the manuscript *IRIS: an agentic eye on symmetry-derived paths and energy
landscapes of structural phase transitions* (Manna, Agrawal, Ramesh, Ganesh, Darancet, Sankaranarayanan, 2026,
submitted). IRIS turns a plain-language request and two crystal structures into a symmetry-adapted energy
landscape, a fitted Landau model and an audit trail: seven nodes separated by deterministic gates, with a
language model used only to interpret the request and to choose among listed recovery actions.

The stored DFT campaigns (structures, frames, energies, audit logs) and the live BaTiO3 run directories are
deposited separately (see *Data availability* in the paper); this repository holds everything else.

## Layout

| Path | What it is |
|---|---|
| `iris_agent/` | the workflow: nodes f0–f6, gates G0–G6, recovery, replay and live engines, chat/web interface |
| `rules/`, `recovery.yaml`, `recovery_live.yaml` | mode-selection rules R1–R5 and the stored recovery rule table |
| `prompts/` | the intake and gate sub-agent prompts, verbatim as evaluated |
| `configs/` | the 13 run configurations of the paper (replay) and the BaTiO3 live configurations |
| `eval/` | the frozen evaluation set: 53 sub-agent cases, 53 faults, model list, FROZEN.sha256 |
| `policies/` | the deterministic deciders (rules only, decision tree, retrieval), frozen before scoring |
| `consequences/` | the option replay (every recovery option executed from its checkpoint; `fork.py`) |
| `intake/` | the plain-language intake, its 50 frozen requests, the keyword lookup and the rule-based parser |
| `eval_extra/` | leave-one-system-out transfer analysis (`loso.py`, `loso_llm.py`) |
| `tests/` | pytest suite (replay regression, gates, recovery, live mode) |
| `results/` | the CSVs behind every evaluation table and figure (see `results/README.md`) |
| `scripts/figures/` | the script that draws the evaluation figure from `results/` |
| `live_demo/` | scripts and runbook of the prospective BaTiO3 campaign on an HPC cluster (PBS); cluster identifiers are placeholders |
| `docs/` | `LIVE_RUN.md` (reproducing the live BaTiO3 campaign on PBS or Slurm), `CONFIG_SCHEMA.md` (every configuration, policy and recovery-table key; adding a new system), changelog, manual checks, API-key setup |

## Reproduce

```bash
python -m venv iris-env && source iris-env/bin/activate
pip install -r requirements.txt
export IRIS_CONFIGS=$PWD/configs                      # replay needs the stored campaigns (Data availability) at paths.repo_root of each config
python -m pytest tests -q                             # ~3 min
python -m policies.score_cases                        # deterministic deciders on the 53 cases
python -m eval_extra.loso                             # leave-one-system-out
python -m eval_extra.cost_summary                     # tokens, cost and latency of every model call
python -m eval_extra.decoy_remedy --models eval/models.yaml   # the three guidance-sentence remedies for the decoys (post-hoc)
python -m eval_extra.eligibility --models eval/models.yaml     # the benchmark with menus filtered by the eligibility conditions
python -m consequences.fork --c2 ...                  # option replay (see consequences/fork.py)
python -m intake.run_parser                           # rule-based intake parser
python -m iris_agent.subagent_bench --models eval/models.yaml   # language-model benchmark; API keys from the environment only
```

API keys are read from environment variables only (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`,
`MP_API_KEY`) and never reach state, logs or checkpoints (tested). `docs/API_KEYS_SETUP.md` has the details.

## Licence

MIT (see `LICENSE`). Please cite the paper (`CITATION.cff`).

---

## Original build notes


One LangGraph `StateGraph`:

```
START → f0 Intake ─G0→ f1 Crystallographer ─G1→ f2 Path Planner ─G2→ f3 Runner ─G3→
        f4 Reviewer ─G4→ f5 Analyst ─G5→ f6 Skeptic ─G6→ END
                     any gate fails → recover: recovery.yaml rule → gate sub-agent → human (interrupt)
```

- Gates G0–G6 are plain Python (pass/fail + code + detail). The LLM never computes, decides pass/fail, routes or writes numbers.
- Checkpoints: SqliteSaver, one `thread_id` per run, `test_runs/<thread_id>/iris.sqlite`. A thread that already ran is never restarted (use `--thread NEW`).
- Audit log: `test_runs/<thread_id>/audit.jsonl`, one JSON line per run / node / gate / fix / interrupt / resume / end.
- The API key is read only from `ANTHROPIC_API_KEY`; it never reaches state, the log or the checkpoint (tested).

## Safety rules built into the code

| Rule | Where it is enforced |
|---|---|
| Write only inside `IRIS_AGENT/` | `paths.Paths.out()` refuses any other path; existing scripts run as subprocesses on copies inside `test_runs/`; no bytecode is written when importing repo code (`sys.dont_write_bytecode`); `pytest.ini` keeps pytest's root and cache off the repo |
| Existing code and data are read-only | imported or read only (`engines/legacy.py`, `Paths.repo()`) |
| No DFT / VASP / MACE / Slurm | `run.allow_live_submission` must be `false`; f3 is replay-only (`engines/replay.py`) |
| No live ISODISTORT/FINDSYM calls | f1 reads the stored responses in `<reference_run>/step3_isodistort/04_raw_isodistort/` and `step1_standardize/step1_result.json` |
| A crashing node or check cannot pass | node exception → gate fails with `NODE_ERROR`; test exception → `TEST_ERROR` |
| All data paths in one file | `configs/cssni3.yaml` |

## Setup, test, run (on your Mac)

```bash
source iris-env/bin/activate
cd IRIS
python -m pytest -q                                   # 61 tests incl. the full replay, E2 faults and E7 kill/resume (~3 min)
python -m iris_agent.run --config configs/cssni3.yaml          # thread cssni3_221_62_wait: runs f0-f2, f3 submits and waits
python -m iris_agent.run --config configs/cssni3.yaml --status
python -m iris_agent.jobend --config configs/cssni3.yaml --parts 0-9    # simulated job-end for parts 0-9 -> resumes, waits on the rest
python -m iris_agent.jobend --config configs/cssni3.yaml                # remaining parts end -> f3..f6 -> END
python -m iris_agent.regression --config configs/cssni3.yaml   # -> test_runs/<thread>/regression_report.md
# other job-end events:  --fail 3:WALLTIME   --cancel
# a paused human decision:  python -m iris_agent.run --config configs/cssni3.yaml --resume '{"option": "stop"}'
# a new run needs a new thread:  --thread <name>
python -m iris_agent.faultinject --config configs/cssni3.yaml  # -> test_runs/fault_injection/report.md
```

### Runbook interface (claude/iris-agent-ai-results-runbook.md)

```bash
python -m iris_agent.check_env                                   # configs, data paths, replay index, keys (names only), eval freeze
python -m iris_agent.freeze_eval eval/                           # once, before any model run -> eval/FROZEN.sha256
python -m iris_agent.run --config configs/cssni3.yaml --mode replay --llm off --tag E1      # thread E1_cssni3
python -m iris_agent.resume_test --config configs/cssni3.yaml --kill-after f3 --tag E7    # test_runs/E7/resume_test.md
python -m iris_agent.inject --faults eval/faults.yaml --llm off --tag E2                  # test_runs/E2/inject_report.md
python -m iris_agent.inject --faults eval/faults.yaml --llm off --no-gates --tag E4       # ungated baseline
```

- Run options: `--tag` (thread `<tag>_<system>`), `--llm off` (other values refused until step 5), `--mode`,
  `--ablate no-gates,no-g6,no-rules,no-subagents` (`--no-gates` = `--ablate no-gates`), `--fresh`, `--continue`.
- Every audit line carries run_id, tag, system, fault_id, ablation_flags and the model fields (null while the LLM
  is off); gate lines add gate_code, outcome (pass / fail / fail_ignored / skipped), attempts; fix lines add
  recovery_tier, rule_id, option_id, output_valid, token/cost fields; node lines wall_time_s; the end line the
  final status and the G6 table.
- Checkpoints are written synchronously (`durability="sync"`): E7 showed that with LangGraph's default
  asynchronous saving a hard kill right after f3 lost f3's checkpoint.
- `eval/faults.yaml` holds the nine CsSnI3 seed faults (F001–F009); the runbook's full set (100–200 faults over
  six systems, seed + held-out) is still to be written, then frozen.
- Not yet available: configs for the other five systems; `--llm <model>` (step 5); `benchmark`, `robustness`,
  `react_baseline`, `intake_eval`, `run_batch`, `trace`, `export_reports`, `summarize`, plots.

### Ca₃Ti₂O₇ replay (manuscript X₃⁻/X₂⁺ plane, true A_p)

```bash
python -m iris_agent.run --config configs/ca3ti2o7.yaml            # thread ca3ti2o7_139_36_xplane, waits on 35 parts
python -m iris_agent.jobend --config configs/ca3ti2o7.yaml          # all parts end -> f3..f6 -> END
python -m iris_agent.regression --config configs/ca3ti2o7.yaml     # -> test_runs/<thread>/regression_report.md
```

- Primaries from the translation-free walk (`policy.amplitude_basis: As_tf`): X₃⁻ + X₂⁺.
- Γ₅⁻ held at 0 by `policy.hold_at_zero`. This overrides R4, and the override is recorded in `selection.policy_overrides`.
- The stored xplane labels are A_s of the 48-atom cell. Q = label/√2 (`run.replay.label_scale`); the structures decide the match.
- f5 runs `policy.analysis: surface`, which wraps `demo/ca3ti2o7/plot_ca3ti2o7_plane.py` unchanged. G5 checks coverage, that the minimum lies inside the grid, mirror symmetry, and that the script agrees with the node.

### InMnO₃ plane replay (stage 1: K₃ × Γ₂⁻ at Φ = 0, Meier-form fit)

```bash
python -m iris_agent.run --config configs/inmno3.yaml             # pauses at G2 R5_BORDERLINE (human decides)
python -m iris_agent.run --config configs/inmno3.yaml --resume '{"option": "include_borderline"}'   # -> f3 waits on 6 parts
python -m iris_agent.jobend --config configs/inmno3.yaml           # all parts end -> f3..f6 -> END
python -m iris_agent.regression --config configs/inmno3.yaml      # -> test_runs/<thread>/regression_report.md
```

- **Selection:** the primary is K₃ alone. Γ₂⁻ is kept by R4, and R5 is borderline (margin 0.076 Å), so the human decides at run time.
- **Grid:** per-axis spacing (`policy.grid.axes`).
- **Matching:** stored frames are matched modulo the old Γ₂⁻ rigid shift (`run.replay.match_modulo_translation`, at most 0.015 Å).
- **f5:** `policy.analysis: meier_QP` runs `fit_landau_QP.py` unchanged; the G5 tests are `G5_meier_QP`.

### ErMnO₃ plane replay (K₃ × Γ₂⁻ at Φ = 0 plus the Γ₂⁻ axis; published fixed-a_P fit)

```bash
python -m iris_agent.run --config configs/ermno3.yaml              # no human step expected -> f3 waits on 6 parts
python -m iris_agent.jobend --config configs/ermno3.yaml
python -m iris_agent.regression --config configs/ermno3.yaml
```

- **Stored data:** the merged `planepax` manifest, with POSCARs read from two stored grids (`run.replay.poscar_dirs`).
- **P axis:** the 11 P-axis points are anchors `pax_*`.
- **Fit:** f5 takes a_P from the P axis (P² + P⁴ + P⁶, |P| ≤ 0.5 Å), then fits the plane with a_P fixed (`policy.fit.aP_axis`).

### Manganites stage 2 (plane + polar hat wedge, joint Meier fit with c′)

```bash
python -m iris_agent.run --config configs/inmno3_joint.yaml       # R5 pause -> --resume '{"option": "include_borderline"}'
python -m iris_agent.jobend --config configs/inmno3_joint.yaml
python -m iris_agent.regression --config configs/inmno3_joint.yaml
python -m iris_agent.run --config configs/ermno3_joint.yaml       # no human step
python -m iris_agent.jobend --config configs/ermno3_joint.yaml
python -m iris_agent.regression --config configs/ermno3_joint.yaml
```

- **Second K₃ component:** obtained from a 120° parent-lattice translation.
- **Hat wedge:** Φ = 0–30° (`policy.grid.polar`).
- **Stored hat grid:** matched through `run.replay.extra_references`.
- **Fit:** `policy.analysis: meier_joint`.
- **Reference files:** regression reads `<config>_reference.yaml`.

### BiFeO₃ replay, stages B1–B4 (six single components; 6D plan; replay; degree-12 fit)

```bash
python -m iris_agent.run --config configs/bifeo3.yaml --fresh     # f0 .. f3, then waits on 104 job parts
python -m iris_agent.jobend --config configs/bifeo3.yaml           # all parts end -> f3 .. f6 -> completed (~4 min)
python -m iris_agent.regression --config configs/bifeo3.yaml
python -m pytest -q tests/test_bifeo3_b1.py
```

- **Staged run:** `run.stop_after: f1` ends the thread after G1 passes; the run status is `stage_completed`.
- **Components** (`policy.components`, `engines/components6.py`): P_i = i-th Cartesian part of the GM4- field
  (translation removed), R_i = the part of the R5- field rotating about x_i. f1 checks the partition, folds
  the fields onto the grid's 10-atom fcc(2a_c) cell, derives the 96 6×6 operation matrices there, and
  compares atom by atom with `demo/bifeo3/grid6d/bfo6d/basis.py` (imported read-only via `paths.grid_toolkit`).
- **G1:** new test `components_consistent`; `basis_det_equals_k` now uses det = s·z_child/z_parent
  (R3c on hexagonal axes: 2 × 3 = 6).
- **B2 (now in the same config, `stop_after: f2`):** f2 plans the six-component campaign from IRIS's own
  vectors and 96 matrices (`nodes/f2_grid6.py`): main_V1 (radius 6) and main_V0 (radius 5) orbits with the
  1.6 Å contact cut, the stored controls (verified), the three refine planes, and the 253 adaptive extra points
  (declared, checked). It compares everything with the stored packages (`paths.grid_packages`, read inside
  the .tgz files, nothing extracted). G2 uses the test set `G2_grid6`.
- **B3 (`stop_after: f4`):** f3 matches every frame to its stored POSCAR inside the packages
  (`nodes/f3_grid6.py`, `engines/replay6.py`: positions within `run.replay.tol_A`, q recovered by projection,
  nothing outside the six-vector span), then waits for job-end events as usual (104 parts of 100). f4 links
  energies, gradients and QC from `paths.collected_dir` (`nodes/f4_grid6.py`) and checks them by symmetry
  (controls, refine points on main nodes), by Simpson line integrals of the gradients, and for G-AFM.
  G4 uses the test set `G4_grid6`.
- **B4 (no stop: runs to f6 / G6):** f5 fits the degree-12 invariant polynomial to energies and gradients as
  `work/refit.py` does (`nodes/f5_landau6d.py`; invariants built from IRIS's own 96 matrices and checked against
  Molien's formula), derives the nine stationary points and a 60-start global search, and cross-checks with the
  RBF (`work/fit_rbf6d.py`, reported only). G5 uses `G5_landau6d`. f6 (`nodes/f6_grid6.py`) re-derives 74
  numbers by other routes (QR instead of lstsq, BFGS instead of Nelder-Mead, Hessians from energy differences,
  spglib at every stationary point).
- **Regression:** `python -m iris_agent.regression --config configs/bifeo3.yaml` (reference `configs/bifeo3_reference.yaml`).

### D4 hard-secondary scans (CsSnI₃ X₅⁺; `configs/cssni3_d4.yaml`)

```bash
python -m iris_agent.run --config configs/cssni3_d4.yaml --fresh      # waits on 26 job parts at f3
python -m iris_agent.jobend --config configs/cssni3_d4.yaml            # -> G5 SECONDARY_COUPLED -> human
python -m iris_agent.run --config configs/cssni3_d4.yaml --thread cssni3_221_62_d4 --resume '{"option": "accept_secondary_hold"}'
python -m iris_agent.regression --config configs/cssni3_d4.yaml
```

- `policy.d4`: each secondary held at zero is scanned along its own calibrated vector at declared base points
  of the primaries (f2, frames tagged `d4_<scan>`); the stored scans are matched as extra references; f5
  (`nodes/f5_d4.py`) fits each scan (quartic): curvature, relaxed amplitude, released energy; G5 test
  `d4_secondaries_hold` compares the largest released energy with `max_fraction` × `compare_to` (the ring
  corrugation) and stops with `SECONDARY_COUPLED` for the human (`accept_secondary_hold` or stop).
- The stored scans ran with other DFT settings (ENCUT 350, ISPIN 2); `policy.d4.settings: own_per_scan` lets G4
  accept that as long as each scan and the main grid each use one input set.

### HfO₂ paths, stages H1–H3 (five transitions; `configs/hfo2_T1.yaml` … `hfo2_T5.yaml`)

```bash
for t in T1 T2 T3 T4 T5; do
  python -m iris_agent.run --config configs/hfo2_$t.yaml --fresh                    # waits at f3 (job wait)
  th=$(grep thread_id configs/hfo2_$t.yaml | awk '{print $2}')
  python -m iris_agent.jobend --config configs/hfo2_$t.yaml --thread $th            # -> completed, G0-G6 OK
  python -m iris_agent.regression --config configs/hfo2_$t.yaml                     # test_runs/<thread>/regression_report.md
done
python -m pytest -q tests/test_hfo2_h1.py
```

- One config per transition (T1 137→29, T2 137→60, T3 137→14, T4 60→29, T5 60→14), stored ISODISTORT runs of 7–8 Oct;
  the regression reads `configs/hfo2_reference.yaml` (one file for the five).
- f1 also records every strain component (`decomposition.strain_components`; `strain` keeps the last one per irrep).
- **H2:** `nodes/f2_path.py` builds the 10 frames (every irrep at λ × its child A_p, polar ones translation-free;
  cell linear in λ from the parent to the child cell). `policy.path.child_lattice` sets the child cell's
  orientation (`stored` = as the stored path built it; `pure_stretch` = no rigid rotation). G2 uses `G2_path`.
- **H3:**
  - f3 (`nodes/f3_path.py`) matches frame k to the stored `L<kk>/POSCAR` (same species order, every atom within
    `run.replay.tol_A`, cell within `tol_lattice_A`) and links E0 and the run record from its `result.json`.
  - f4 (`nodes/f4_path.py`, G4 `G4_path`): OSZICAR rule (last |dE| < EDIFF in < NELM steps), |m| ≤ 0.01 μB,
    E/f.u. and dE re-derived from E0 against `result.json` and the collector's `energies.csv`, f.u. per cell from the
    composition, one INCAR/KPOINTS/POTCAR set and INCAR = `paths.incar_template`.
  - f5 (`nodes/f5_path.py`, analysis `path`, G5 `G5_path`): profile, frozen-path barrier and λ, dE end, spline
    barrier (not gated); `policy.path.network`: the same crystal in other stored paths is found by structure
    (StructureMatcher) and must agree in E/f.u. (`cross_setting_meV`), and closure chains (T1 = T2 + T4,
    T3 = T2 + T5) must connect by structure and close within `closure_meV`.
  - f6 (`nodes/f6_path.py`): stored POSCARs recounted, energies re-read from `energies.csv`, barrier from the CSV
    and `energies_summary.json`, spline maximum by a bounded optimiser, the closure identity
    (gap = sum of the cross-setting differences at the shared structures).

### Sub-agents (build step 5; S5.1 provider layer)

```bash
python -m iris_agent.llm --check                       # list all 3 providers + ping every pinned model in both modes
                                                       # -> results/llm_checks/<UTC time>/{models_<provider>.txt,
                                                       #    ping_constrained.jsonl, ping_free.jsonl, summary.md}
python -m iris_agent.llm --list openai [--save]        # model ids your account can use (also anthropic, google)
python -m iris_agent.llm --ping all [--mode free] [--save]   # fixed dummy prompt (no project data)
python -m iris_agent.run --config configs/cssni3.yaml --llm claude-sonnet --ablate no-rules --tag S5
python -m iris_agent.inject --faults eval/faults.yaml --llm claude-sonnet --ablate no-rules --tag S5 --only F001
```

- `iris_agent/llm.py`: one call, `llm_choose()`, for Anthropic (Messages API), OpenAI (Chat Completions; also
  OpenAI-compatible servers through `base_url`, for open models) and Google (Gemini `generateContent`), over plain
  HTTPS (standard library, nothing to install), plus a `fake` provider for tests.
- Models live in `eval/models.yaml` (`--llm <name>`); keys only from `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `GOOGLE_API_KEY` (never in files, state or logs; a key-like value in a config or models file is refused).
- `mode: constrained` makes the provider return one of the menu ids (OpenAI strict json_schema and Gemini
  responseSchema enforce the enum; Anthropic a forced tool call with the enum, schema-guided); `mode: free` asks for
  plain JSON. Off-menu, unparseable or truncated answers are invalid: logged, never retried, sent to the human.
  Transport errors (429 / 5xx / timeout) are retried up to 3 times.
- Every sub-agent call: audit `fix` line with provider, model and returned version, mode, temperature, seed,
  valid, tokens (in / out / reasoning), cost (if `price_usd_per_mtok` is set), latency, option order;
  the full prompt and reply in `test_runs/<thread>/llm_calls.jsonl`.
- `shuffle_options: true` shows the menu in a seeded random order (position-bias tests).

### Sub-agent benchmark cases (build step 5, S5.2)

```bash
python -m iris_agent.subagent_cases --configs configs            # capture every case (replay, no model calls; ~5 min)
python -m iris_agent.subagent_cases --table-only                 # rebuild eval/subagent_cases/CASES.md
```

- `eval/subagent_cases.yaml`: 19 cases with labels (correct / acceptable / wrong for every menu option) and the
  reason for each. Classes: rules_off (rule table ablated), used_up (a rule failed once), no_rule, judgment, decoy.
- Each case is captured from a real failing replay: a stand-in model answers earlier calls from a script and
  declines the k-th, whose exact prompt inputs, template and rendered prompts go to `eval/subagent_cases/<id>.json`
  (paths as `<repo>` / `<agent>`), with both prompt variants: `guided` (the gate's Guidance line) and `bare` (without).
- Menus (`recovery.yaml`) list only options a node acts on (tested); a stop-only menu goes to the human directly.

### S5.3 model comparison and the model-off evaluation (E1, E2, E4, E7)

```bash
python -m iris_agent.freeze_eval eval/                               # once, after the cases are approved
python -m iris_agent.subagent_bench --tag S5_3                       # 9 models x 27 cases x guided/bare x 10 repeats
python -m iris_agent.subagent_bench --tag S5_3 --retry-errors        # redo calls that hit HTTP / timeout errors
python -m iris_agent.subagent_bench --tag S5_3 --summarize           # results/summary/S5_3_*.csv + S5_3_summary.md
python -m iris_agent.menus                                           # SI Table S3: results/summary/SI_S3_menus.{csv,md}
python -m iris_agent.run_e1 --configs configs                        # E1: every system end to end, model off
python -m iris_agent.inject --faults eval/faults.yaml --llm off --tag E2
python -m iris_agent.inject --faults eval/faults.yaml --llm off --no-gates --tag E4
python -m iris_agent.resume_test --config configs/cssni3.yaml --kill-after f3 --tag E7_f3
python -m iris_agent.eval_summary --e2 E2 --e4 E4 --e7 E7_f2,E7_f3,E7_f5,E7_hfo2 --e1 E1
```

- The benchmark refuses to run unless `eval/` is frozen and unchanged; every model sees the same prompts and, per
  repeat, the same shuffled option order (paired). Scores: correct / safe / harmful / invalid; baselines
  always-stop, first-option, uniform-random; 95 % CIs by bootstrap over cases; McNemar vs the reference model.
- `results/summary/` holds every table as CSV.

### The f3 job wait (step 3)

f3 matches the frames to the stored computed structures, groups them into parts (`run.jobs.part_size`,
40 = one Slurm array task of the 12 Sep campaign → 25 parts), writes the submission record
`test_runs/<thread>/f3_jobs/submission.json`, and pauses with `interrupt()`. The thread sits in the
SQLite checkpoint until a job-end event arrives (`iris_agent.jobend`, the stand-in for a Slurm job-end
hook). On every resume LangGraph re-runs f3, which finds the submission record for the same grid and
reuses it: a resumed run never submits twice (`n_submissions` stays 1; tested). Events that are not job
events are rejected and f3 keeps waiting. Energies are linked only for finished parts; a failed part
(`--fail 3:WALLTIME`) makes G4 fail with that code, a cancel makes G3 fail with `JOBS_CANCELLED`.
A failed part is resubmitted by the WALLTIME/NELM rules (`goto: f3, resubmit_failed`): f3 writes a
resubmission round (`submission_r1.json`, only the failed parts, with any INCAR patch) and waits again.

### Fault injection (step 4)

`python -m iris_agent.faultinject` runs nine scenarios on the CsSnI₃ replay, one per recovery path,
each in its own thread (`fi_<name>`). Faults enter only through the run config (`faults:` and policy
values; allowed in replay mode only, recorded by f0) — data and code are never touched.

| scenario | fault | expected handling |
|---|---|---|
| walltime | part 3 ends WALLTIME | G4 → rule `f4_walltime_resubmit` → f3 resubmits part 3 → completes, numbers = stored fit |
| nelm | part 7 ends NELM | G4 → rule `f4_nelm_robust_mixing` → f3 resubmits part 7 with AMIX/BMIX/NELM → completes |
| translation | 0.05 Å/atom rigid shift left in M3+ | G2 TRANSLATION → rule `f2_translation` → completes |
| no_basis | atom matching limited to dmax 0.3 Å | G1 NO_BASIS → ladder `f1_no_basis_dmax_ladder` (1.0 Å) → completes |
| no55 | single-mode check on the child cell | G2 SINGLE_MODE_SG (#55 instead of #127) → rule → fixed parent lattice → completes |
| thin_grid | G5 wants 100 points per coefficient | G5 THIN_GRID → rule → f2 densify ×2 → G2 OVER_BUDGET (3721 > 1100) → human |
| unmatched | stored frame 100 missing | G3 UNMATCHED → human (never computed) |
| retry_budget | dmax 0.3 Å, retry budget 0 | G1 NO_BASIS → human straight away → widens dmax → completes |
| cancel | jobs cancelled while waiting | G3 JOBS_CANCELLED → human |

`f0_schema_reask` is the only rule without a scenario: it needs the LLM (step 6); with the LLM off the
case goes to the human (tested in `tests/test_graph.py`).

## What each node does now

| Node | Wraps (read-only) | Gate checks |
|---|---|---|
| f0 Intake | reads `configs/cssni3.yaml` (LLM intake: step 6) | G0: schema, CIFs exist, spglib SG 221/62, pinned sha256 (= `RUN_MANIFEST.json`), budget, write location |
| f1 Crystallographer | `step1_standardize.tolerance_ladder`, `step2_subgroup.group_index/is_true_subgroup`, `step3_isodistort.parse_modes_details/parse_tree`, `iris/lib/basis_search.find_basis`; stored ISODISTORT mode matrix (`full_movie.cif`) → per-irrep displacement fields | G1: H ⊂ G and t·k = i; spglib ladder + stored FINDSYM; det(basis) = k, independent atom-matching basis agrees (max displacement 0.5929 vs 0.5929 Å); ISODISTORT SG = spglib (child CIF and rebuilt decomposition); ‖field‖ = A_s for every irrep |
| f2 Path Planner | `rules/select_modes.py` (R1–R5, primaries) | G2: c1; c2 atom matching (< 2 Å), translation removed (f_T), calibration (s = A_child/A_movie consistent across irreps; child projects onto each calibrated vector at its A_p), strict single-mode SG at 1e-2 on the fixed parent lattice; c3 D1/D2, budget, every descent-tree subgroup on the grid; every frame's SG = descent tree and d_min ≥ d_cut |
| f3 Runner | `engines/replay.py`: each built frame matched to a stored POSCAR by structure (same lattice, species, every coordinate within 1e-4); `engines/jobs.py`: parts, submission record, `interrupt()` wait for job-end events | G3: nothing queued/running, no part cancelled, every frame matched |
| f4 Reviewer | stored CSV (written by `collect_energies.py`'s OSZICAR rule) | G4: frames of failed parts → their code (WALLTIME, NELM, …) unless accepted as flagged; every frame converged or flagged, parent has an energy, energy range sane, one INCAR/KPOINTS set |
| f5 Analyst | `fit_landau_plane.py` and `ring_profile.py`, unchanged, as subprocesses on copies in `test_runs/<thread>/f5_fit/`; + 10-fold CV | G5: CV RMS, residuals, coverage (points per coefficient, ring inside the fit region) |
| f6 Skeptic | independent re-derivation of every reported number (QR refit, bounded per-angle minimiser, spglib recount, CSV re-read, …) | G6: all re-derived numbers agree |

## Plan

0. ✅ Read-only survey and mapping table
1. ✅ Layout, graph, state, audit log, checkpointer; f0 reads the config; prompt gallery
2. ✅ CsSnI₃ replay regression (`test_runs/<thread>/regression_report.md`)
3. ✅ f3 `interrupt()` + simulated job-end resume (`iris_agent.jobend`)
4. ✅ `recovery.yaml` fault-injection tests (`iris_agent.faultinject`, 9/9 scenarios)
5. Claude sub-agents · 6. LLM intake · later: Ca₃Ti₂O₇, InMnO₃, ErMnO₃, BiFeO₃, HfO₂ replays
