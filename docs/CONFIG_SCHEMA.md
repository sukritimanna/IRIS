# Run configuration, policies and the recovery table

Everything IRIS decides about a landscape is written in two places: the run configuration (`configs/<system>.yaml`,
one per campaign; its `policy:` block carries the rules R1–R5 and D1–D5 of the paper's Methods 4.2) and the
recovery table (`recovery.yaml`; `recovery_live.yaml` for live runs). The language model never edits either; the
intake writes a configuration from a request by choosing ids from the tables in `intake/library.py`, and a
recovery fix is a patch merged into the overrides of the node that runs next. This document lists every key, says
which node reads it, and ends with a worked example of adding a new system.

There is no file called `policy.yaml`: the policies live under `policy:` in each configuration, so that the
configuration is the complete, hashed record of a campaign (`iris_agent/config.py` validates it; `f0` records its
hash and the CIF digests in the audit log).

## 1. Run configuration (`configs/<system>.yaml`)

### Top level

| Key | Read by | Meaning |
|---|---|---|
| `system` | all | system id (`cssni3`, `ca3ti2o7`, `inmno3`, `ermno3`, `bifeo3`, `hfo2`, or any new id) |
| `thread_id` | runtime | checkpoint and run directory name (`test_runs/<thread_id>/`); a thread that already ran is never restarted |
| `request` | f0 | the plain-language request (recorded; in replay it is not parsed) |
| `run` | f0, f3 | mode, engine, budget, jobs, replay or live settings (below) |
| `paths` | f0–f6 | where the inputs and stored data are (read only) and where IRIS writes (`agent_root`) |
| `expected` | G0, G1 | parent and child space-group numbers; pinned SHA-256 of both CIFs (`CIF_CHANGED` if they differ) |
| `policy` | f2, f5, f6 | the physics decisions R1–R5, D1–D5 and the fit limits (below) |
| `retry` | recover | `max_per_node` (3): attempts per node before the failure goes to the human |
| `llm` | f0, recover | `enabled`, `model` (an id from `eval/models.yaml`), `api_key_env` (the key is read from this variable only) |
| `faults` | f0 | evaluation only: the fault to inject (`eval/faults.yaml`); refused outside replay |

### `run`

| Key | Meaning |
|---|---|
| `mode` | `skeleton` (nodes stubbed; tests), `replay` (every frame linked to a stored calculation; nothing computed), `live` (compute) |
| `engine` | `dft` (VASP) or `mlip` (batch evaluation) |
| `budget_runs` | B, the campaign budget; an over-budget grid fails G2 `OVER_BUDGET` |
| `allow_live_submission` | must be `true` for mode `live` and `false` otherwise (validated, and checked again in f3) |
| `jobs.wait`, `jobs.part_size` | f3 pauses until every part has ended; frames per job part |
| `replay.tol_A`, `replay.tol_lattice_A` | frame-to-stored-structure matching tolerances |
| `replay.match_modulo_translation`, `replay.max_rigid_shift_A` | match after removing a rigid shift (older stored frames); G3 `RIGID_SHIFT` above the limit |
| `replay.label_scale`, `replay.poscar_dirs` | unit of the stored axis labels; several stored grids merged into one campaign |
| `live.submit_cmd`, `live.queue_cmd`, `live.poll_s` | scheduler commands (`docs/LIVE_RUN.md`) |
| `live.job_header`, `live.vasp_cmd`, `live.potcar_dir`, `live.incar`, `live.kspacing` | the job script header, the VASP call, the PAW library, the INCAR tags and the k-point rule |

### `paths`

`repo_root` (the stored campaigns and the `imhafo2` package; read only), `agent_root` (the only writable root; every
write goes through `paths.Paths.out`, which refuses anything else), `test_runs`, `parent_cif`, `child_cif`,
`system_json` (the electronic-structure profile: functional, +U, magnetic order, cut-off, k-mesh), `walkthrough`,
`reference_run`, `reference_grid`, `isodistort_stored` (the stored ISODISTORT responses f1 reads in replay),
`energies_csv`, `reference_fit`, and for live runs `isodistort_live` and `recovery` (`recovery_live.yaml`).

### `policy` — the physics decisions

| Key | Rule | Read by | Meaning |
|---|---|---|---|
| `a_thr` | R2 | f2 | amplitude threshold (0.05 Å in every campaign) |
| `amplitude_basis` | R2 | f2 | `As` (supercell-normalized) or `As_tf` (translation-free; needed when a polar irrep carries a rigid shift) |
| `r5_margin` | R5 | f2 | margin (0.1 Å) below which the selection is borderline and goes to the sub-agent or human |
| `hold_at_zero`, `hold_at_zero_reason` | override of R4 | f2 | irreps never made axes, with the reason recorded in the audit log |
| `remove_translation` | c2 | f2 | subtract the mean displacement of polar vectors (default on) |
| `strain_policy` | P1–P5 | f2 | `P1` fixed lattice, `P2` stated cell, `P3` strain-interpolated (paths), `P5` fixed-lattice bias statement |
| `d_cut` | c3 | f2 | minimum interatomic distance in any frame (Å) |
| `analysis` | D1 | f2, f5 | `landau_plane`, `surface`, `meier_QP`, `meier_joint`, `landau6d`, `path` (which f5 model is fitted and which G5 tests apply) |
| `grid.q_max`, `grid.dq` or `grid.axes.<irrep>` | D2 | f2 | per-axis range and step in Å of A_p; m_i = 2 q_max,i / dq_i + 1, N = Π m_i |
| `anchors` | — | f2 | extra exact points (named structures) added to the grid |
| `d4` | D4 | f2, f5 | one-dimensional scans of a secondary held at zero (the CsSnI₃ X₅⁺ scans) |
| `path.n_points`, `path.child_lattice`, `path.child_rms_tol`, `path.network` | paths | f2, G5 | straight irrep path with strain scaled alongside; the stored paths a new path is checked against (`CLOSURE`, `CROSS_SETTING`, `NETWORK`) |
| `fit.rmax`, `fit.per_fu`, `fit.cv_folds` | — | f5, f6 | fit region, formula units per cell (G4 checks it against the composition), cross-validation folds |
| `fit.max_rms_meV`, `fit.max_cv_rms_meV`, `fit.max_abs_res_meV`, `fit.min_points_per_coef`, `fit.edge_margin_steps` | G5 | G5 | the tolerances: `RESIDUALS`, `CV_ERROR`, `THIN_GRID`, `COVERAGE` |
| `fit.allow_missing_frames` | G4, G5 | G4, G5 | a recorded human authorisation of a fit on fewer frames than planned (`MISSING_FRAMES` otherwise) |
| `fit.aP_axis` | — | f5 | fix the P-axis coefficient from a separate axis scan (the ErMnO₃ procedure) |
| `qc.mag_max_muB` | G4 | G4 | magnetic moment allowed in a non-magnetic calculation |

The rules themselves are code (`rules/select_modes.py` for R1–R5 and the R5 decision semantics; `nodes/f2_*.py`
for D1–D5; `gates.py` for every test). A policy value changes what the rules compute; it never bypasses a gate.

## 2. The recovery table (`recovery.yaml`)

```yaml
rules:
  - id: f4_nelm_robust_mixing            # unique id, written to the audit log with every use
    node: f4                             # the node whose gate failed
    code: NELM                           # the error code the gate raised
    fix: {goto: f3, resubmit_failed: true, incar: {AMIX: 0.2, BMIX: 0.0001, NELM: 300}}
    ladder: {basis_dmax_A: [1.0, 1.5, 2.0]}   # optional: attempt k sets the key to the k-th value, then the rule is used up
    requires: [llm]                      # optional: the rule applies only when that capability is on
    source: "hand fix: ..."              # where the fix came from (audit log)
options:
  f5:                                    # the menu the gate's sub-agent and the human choose from
    - {id: densify, patch: {goto: f2, densify: 2}, text: "Go back to f2 and densify the grid"}
    - {id: stop,    patch: {abort: true}, text: "Stop and ask the human"}
```

`fix` and `patch` are configuration patches merged into the overrides of the node that runs next (`goto`, else
the failing node). Every option must change something a node reads: `tests/test_gates_recover.py` checks the
patch keys, so an option that no node would act on is refused at test time, not discovered in a run. The recovery
order is fixed in code: a matching rule that is not used up, then the sub-agent choosing one id from the node's
menu (its answer is validated against the menu and re-checked by the gate), then the human with the same menu.
A human answer can be written back as a new rule, which is how the table grew during the campaigns (Supplementary
Table S2 records the provenance of each rule).

The guidance line of each sub-agent prompt (`prompts/subagent_G*.md`) is the one-sentence transcription of these
rules that the model sees; keep the two in step when you add a rule, and give every option a sentence that says
which codes it is for (Supplementary Section S12.1, "Why the models choose harmful fixes on decoys").

## 3. Adding a new system

1. **Profile.** Write `demo/staged_walkthrough/systems/<id>.json` (functional, +U scheme, magnetic order, cut-off,
   k-mesh, PAW set) and describe it in `intake/library.py` by its physics, not its name: the only systematic
   intake error of the paper came from two profiles described in the same words.
2. **Structures.** Parent and child CIFs; put their space-group numbers and SHA-256 digests under `expected`. G0 refuses
   a CIF whose digest or spglib space group differs.
3. **Configuration.** Copy the closest campaign: `cssni3.yaml` for a two-irrep plane, `inmno3.yaml` for a plane with
   a borderline polar secondary, `bifeo3.yaml` for a multi-component grid under D5, `hfo2_T1.yaml` for a path.
   Set `policy.amplitude_basis: As_tf` if the child has a polar irrep with a rigid translation; leave `a_thr` and
   `r5_margin` at their defaults unless you report the change.
4. **Transition table.** Add the pair to `TRANSITIONS` in `intake/library.py` (id, system, space groups, label) so that
   the intake can name it; without it a request for the system is `NEEDS_NEW_DFT` (valid, but no stored template).
5. **Dry run.** `python -m iris_agent.run --config configs/<id>.yaml --mode skeleton` checks the configuration and
   paths without computing; in replay, f3 reports every frame it cannot match to a stored structure (`UNMATCHED`),
   which in live mode is the list of calculations to run.
6. **Rules.** Run with the existing table. A failure without a rule stops at the human; when you answer it, add the
   answer to `recovery.yaml` with its `source`, and the matching sentence to the guidance line of that gate's prompt.
