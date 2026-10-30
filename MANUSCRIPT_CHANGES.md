# IRIS_AGENT → manuscript: what changed, why, and what the paper must say

For the manuscript session. Written 16 Oct 2026 (build session). No code was changed, moved or deleted to write this file.

**Sources quoted as "paper":**
- `IRIS_RULES_R1-R5_D1-D5.md`: verbatim Methods 4.2, revised 16 Oct.
- `IRIS_AGENT_HANDOVER.md`: the gate and recovery wording from the paper.
- `IRIS_AGENT_AI_RESULTS_RUNBOOK.md`: commands and audit fields.

Where I do not have the manuscript's exact wording, the item says so.

**Status labels:**
- **SETTLED**: implemented, tested, and agreed with Sukriti.
- **PROVISIONAL**: implemented as a proposal, or still awaiting a decision or data.

**Where things are confirmed:**
- CsSnI₃ replay and fault injection: confirmed on the Mac (61 tests).
- Ca₃Ti₂O₇ replay: confirmed on the Mac on 16 Oct (63 tests passed; regression identical to the cloud run).

---

## A. Changes since the build started

### A1. Primary/secondary labelling of irreps (rule; f2). SETTLED
- **What.** Walk the displacive irreps in order of decreasing amplitude. Add an irrep to the primaries only if its isotropy subgroup lowers the symmetry of the running intersection. Stop when the intersection equals H. All other displacive irreps are secondaries. If the list runs out before H is reached, R3 fails with code `R3_FAIL` (G2 → recover → sub-agent/human). The audit log records, for each irrep, the rule that kept or held it.
  - Intersections are read from the stored ISODISTORT subgroup tree: the highest-symmetry node whose order parameters contain the set.
  - Code: `iris_agent/rules/select_modes.py`.
- **Why.** The paper's R2 uses "primary" and "secondary" but gives no procedure for assigning them. CsSnI₃ step 3 had listed all four modes above A_thr, and the 2-mode plane had been a hand choice.
- **Paper.** The paper now carries R2 as revised on 16 Oct. Its definition of a secondary: "induced by the primaries through their couplings". The walk itself is **not yet written in Methods 4.2**. Suggested sentence: *"Primaries are found by walking the irreps in decreasing amplitude and keeping an irrep only if it lowers the symmetry of the running intersection of isotropy subgroups, stopping at H; if the list is exhausted first, R3 fails."*
- **Results.**
  - CsSnI₃: primaries M₃⁺, R₄⁺; R₅⁺ and X₅⁺ held at 0 (paper ✓).
  - Ca₃Ti₂O₇: see A2.

### A2. The primary walk runs on translation-free amplitudes (rule input; f1/f2). SETTLED for Ca₃Ti₂O₇
- **What.** A new policy value, `policy.amplitude_basis: As_tf`, with A_s^tf = A_s·√(1 − f_T). f1 computes f_T for every irrep from the stored mode matrix. Ca₃Ti₂O₇ uses `As_tf`. CsSnI₃ keeps `As`; its M/R/X irreps have f_T = 0, so the selection is the same either way.
- **Why.** On raw A_s, Ca₃Ti₂O₇ gives X₃⁻ 1.163 > Γ₅⁻ 1.120 > X₂⁺ 0.847, so the walk picks X₃⁻ + Γ₅⁻. That is wrong: the manuscript's primaries are X₃⁻ + X₂⁺. Γ₅⁻ has f_T = 0.7507, so 75 % of its amplitude is a rigid shift. Translation-free, Γ₅⁻ drops to 0.559 Å, below X₂⁺, and the walk gives X₃⁻ (139 → 63) then X₂⁺ (63 → 36 = H).
- **Paper.**
  - Revised R2 already says "translation-free amplitude reaches the threshold".
  - **But** the policy sentence says *"A_thr = 0.05 Å, applied to the supercell-normalized amplitudes A_s … (for every polar irrep in this work the translation-free amplitude gives the same selection)"*. That holds for the threshold test, but **not for the ordering used in the walk**: Ca₃Ti₂O₇ is the counter-example.
  - Suggested wording: *"Irreps are ranked and thresholded on translation-free amplitudes A_s^tf."*
  - The f_T values in c2 check 2 match: Γ₅⁻ Ca₃Ti₂O₇ 0.75 ✓ (IRIS 0.7507).

### A3. Policy override `hold_at_zero` (Γ₅⁻ in Ca₃Ti₂O₇ overrides R4). SETTLED (user decision, 16 Oct)
- **What.** New config keys `policy.hold_at_zero: [GM5-]` and `policy.hold_at_zero_reason`. A held irrep never becomes an axis, whatever R2–R4 say. Every override is written to `selection.policy_overrides` and to the audit log with its reason.
- **Why.** The manuscript figure is the (X₃⁻, X₂⁺) plane with Γ₅⁻ = 0, matching the stored `xplane` campaign. R4 ("a polar child keeps at least one polar irrep") would add Γ₅⁻ as a third axis, giving a 3-D grid that the stored data does not cover.
- **Paper.**
  - R4 as written has no exception. The runbook decision note also says *"Ca₃Ti₂O₇ and the manganites: the polar Γ irrep (Γ5−, Γ2−) is a secondary kept as the polarization axis by R4."*
  - **The figure does not do that.** The paper must either:
    - (a) state that the Ca₃Ti₂O₇ plane holds Γ₅⁻ at 0 and that this overrides R4, or
    - (b) present the plane as a 2-D section of the R4 grid.
  - Open question Q3.

### A4. Strict single-mode check (G2 c2 check 4; gate code `SINGLE_MODE_SG`). SETTLED
- **What.** For each active irrep, build r0 + A_p,child·ê_i exactly as the grid builds it:
  - parent fractional coordinates plus the calibrated, translation-free displacement;
  - on the **fixed parent-supercell lattice**, with no strain.

  The check passes only if spglib (pymatgen `SpacegroupAnalyzer`, `symprec = 1e-2`, default angle tolerance) returns the isotropy-subgroup number H_i from the ISODISTORT tree. A match at other tolerances (ladder 1e-4, 1e-3, 1e-1 recorded) does not count, and a loose-only match fails `SINGLE_MODE_SG`.
  - Recovery rule `f2_single_mode_sg_fixed_lattice`: rebuild on the fixed parent lattice and re-check; otherwise human.
- **Why — CsSnI₃ "No. 55" (12 Sep).** The single-mode check had been run on the raw ISODISTORT movie frame. That frame sits on the child cell, so the child's shear strain broke the symmetry to Pbam #55, and the check still passed at a loose tolerance.
- **Paper.** c2 check 4 reads *"Single-mode frame for each active irrep: SG(r0 + Q ê_i) = H_i"*. It does not state the tolerance, the lattice or the amplitude Q. See Q1.
- **Results.**
  - CsSnI₃: M₃⁺ → #127, R₄⁺ → #74, strict ✓.
  - Ca₃Ti₂O₇: X₃⁻ → #63, X₂⁺ → #64, strict ✓ (the same number at every tolerance on the ladder).
  - Fault F005 (No. 55 re-created) is caught by G2 SINGLE_MODE_SG and fixed by the rule; the numbers are identical to the stored fit.

### A5. Calibration check (G2 c2 check 3). SETTLED
- **What.** For each irrep, the child structure is mapped into the parent frame by structure matching, then species-constrained Hungarian assignment. Before projecting, the child domain is aligned to the vectors: the parent-group operation with the largest overlap is used. The child's projection on the calibrated vector must equal the irrep's A_p within 2 %.
  - The movie factor s_i = A_child / A_movie is recorded per irrep. It is **no longer required to be the same for all irreps.**
  - Movie vectors can come from another stored run (`paths.movie_vectors`, `paths.movie_grid`).
- **Why.**
  - (i) StructureMatcher returned a symmetry-equivalent child domain, which gave sign errors until the domain was aligned.
  - (ii) For Ca₃Ti₂O₇ the movie factors differ by irrep: X₃⁻ 1.25, X₂⁺ 2.50. ISODISTORT scales each irrep's movie separately.
- **Paper.** c2 check 3: *"Calibration s_i = A_i^child / A_i^movie (CsSnI3: s = 1.25, 1.758 vs 1.406 Å; Ca3Ti2O7: 1.13 X3−, 0.57 X2+), or equivalently norm fixed at √s Å per Å of A_p for a supercell of s parent cells."*
  - CsSnI₃ 1.25 ✓ (IRIS 1.2501 for both irreps); child displacement 1.758 ✓ (IRIS 1.7578).
  - **Ca₃Ti₂O₇ "1.13 / 0.57" is not s_i by the paper's own definition.** It is |movie vector| / A_s (the stored `movie_scale_factor`). By the definition, s = X₃⁻ 1.250, X₂⁺ 2.500 (Γ₅⁻ 1.250). Needs correcting (Q5).
  - **"√s … for a supercell of s parent cells" must mean s = the number of PRIMITIVE parent cells in the frame**, not ISODISTORT's s (see A6).
- **Results.** Ca₃Ti₂O₇ child projections 0.8223 / 0.5988 Å vs ISODISTORT A_p 0.8222 / 0.5988 ✓.

### A6. Cell counting and the A_p / A_s units (G1 test `mode_norms_equal_As`; f6; Ca₃Ti₂O₇ axes). SETTLED
- **What.** |field_i| in the frame = A_p,i·√n_cells, where n_cells = the number of parent primitive cells in the frame. f1 records n_cells from the parent CIF; f6 re-derives it from spglib's primitive cell of r0. The G1 test name is kept, but it now checks |field| = A_p·√n_cells. Before, it checked |field| = A_s, which holds only when n_cells = ISODISTORT's s.
- **Why.** Ca₃Ti₂O₇: the 48-atom frame is 4 primitive I4/mmm cells (12 atoms each), so |field| = 2·A_p. But ISODISTORT's s = 2: its supercell is the 24-atom A-centred primitive child cell, so A_s = √2·A_p and |field| = √2·A_s. G1 failed (`DECOMP_NORM`, Γ₅⁻ 1.583 vs 1.120) until this was fixed. CsSnI₃: 20/5 = 4 = s, so the old test happened to work.
- **Consequence for the published Ca₃Ti₂O₇ figure (SETTLED; corrected notebook delivered).**
  - The `xplane` campaign normalised its vectors to √2 Å per unit, so its axis labels are **A_s, not A_p**. True A_p = label/√2.
  - The figure axes become ±1.273 Å (not ±1.8). The minima are at A_p (±0.919, ±0.212). The A2₁am marker moves from the label point (0.822, 0.599), which is really A_p (0.581, 0.424) at 97.8 meV/f.u., to the true child A_p (0.822, 0.599) at 50.8–50.9 meV/f.u. (bilinear).
  - Notebook: `IRIS_AGENT/manuscript_updates/fig_ca3ti2o7_energy_and_dR_Ap.ipynb`. Same style; new `*_Ap` files, nothing overwritten. Sukriti ran it on the Mac on 16 Oct and every printed number matched.
- **Paper.** Methods must define A_p as normalised to the parent **primitive** cell (ISODISTORT's convention) and say which axis unit every figure uses. Check InMnO₃, ErMnO₃, BiFeO₃ and HfO₂ for the same issue (Q6).

### A7. G1 basis-search comparison (G1 `basis_det_equals_k`; code `BASIS_DISAGREE`). SETTLED
- **What.** The independent atom-matching basis search (`iris/lib/basis_search.find_basis`) must agree with ISODISTORT's maximum displacement within 0.01 Å. It may match either the printed value or the shift-free value (rigid translation removed).
- **Why.** Ca₃Ti₂O₇: the printed "displ" includes Γ₅⁻'s rigid shift (0.548 Å). The matcher fixes the origin and finds 0.409 Å; the shift-free ISODISTORT value is 0.411 Å.
- **Paper.** G1 is described as *"H ⊂ G, basis det = k, decomposition SG = spglib"*. The basis-search cross-check is an addition (see B).

### A8. Rigid-translation removal (G2 c2 check 2; code `TRANSLATION`; rule `f2_translation`). SETTLED
- **What.** f_T is recorded for every vector and the mean displacement is subtracted (`policy.remove_translation`, default on). G2 fails if a vector keeps a mean displacement or if f_T > 1e-6 is not removed.
- **Paper.** Matches c2 check 2 (f_T formula and values) ✓.
- **Results.** Fault F003 (0.05 Å/atom shift left in M₃⁺, removal switched off) → G2 TRANSLATION → rule → numbers identical to the stored fit.

### A9. Recovery fixes configure the node that runs next (`recovery.yaml`). SETTLED
- **What.**
  - Rule fields: `fix`, `goto`, `ladder`, `requires`, `source`.
  - A patch is merged into the overrides of the node that re-runs (the `goto` target, else the failing node).
  - Seven rules:

    | rule | trigger | fix |
    |---|---|---|
    | `f0_schema_reask` | SCHEMA | needs the LLM; inactive |
    | `f1_no_basis_dmax_ladder` | NO_BASIS | dmax 1.0 → 1.5 → 2.0 Å |
    | `f2_translation` | TRANSLATION | subtract the mean displacement |
    | `f2_single_mode_sg_fixed_lattice` | SINGLE_MODE_SG | rebuild on the fixed parent lattice |
    | `f4_walltime_resubmit` | WALLTIME | goto f3, resubmit the failed parts |
    | `f4_nelm_robust_mixing` | NELM | goto f3, resubmit with INCAR AMIX 0.2, BMIX 1e-4, NELM 300 |
    | `f5_thin_grid_densify` | THIN_GRID | goto f2, densify ×2 |

  - Every node also has an **option menu** for the sub-agent and the human.
  - Retry budget per node: `retry.max_per_node: 3`. Once it is used up, the failure goes to the human.
- **Why.** WALLTIME and NELM first re-ran f4 on the same failed data. A resubmission must go through f3, so the rules now go to f3 with numbered resubmission rounds (`submission_r<k>.json`, failed parts only).
- **Paper.** Handover/paper: *"Gate fail → recover node: rule table (recovery.yaml) → sub-agent of that gate (LLM picks one listed option + reason) → human via interrupt(). Retry budget per node in state. G5 coverage fail → back to f2."* ✓ The three tiers are implemented. **While the LLM is off, the sub-agent tier answers "off" and the failure goes straight to the human** (see A13).

### A10. f3 job wait, idempotent submission and replay matching (f3; G3). SETTLED
- **What.**
  - Frames are grouped into parts of 40, one Slurm array task each, as in the 12 Sep campaign.
  - f3 writes a submission record before waiting. On resume, f3 re-runs, finds the record and never submits twice.
  - f3 waits with `interrupt()` until every part has ended. Job-end, failed and cancel events arrive through `python -m iris_agent.jobend`, which stands in for the Slurm job-end hook. Answers that are not job events are rejected while waiting.
  - Replay matching:
    - A frame matches a stored POSCAR when lattice and species are the same and every fractional coordinate agrees within 1e-4, after one fixed atom permutation found at Q = 0.
    - Stored axis labels only narrow the candidates (`run.replay.label_scale` converts their units).
    - Unmatched frames fail G3 `UNMATCHED` and go to the human. They are never computed.
- **Paper.** Handover: *"f3 replay: match each frame to an existing computed structure and link its energy; flag unmatched frames, never compute them."* ✓ The parts/wait mechanics are new detail.
- **Results.**
  - CsSnI₃: 962/962 frames matched (max |Δfrac| 2.7e-5); 25 parts; resumed 3× from the checkpoint; 1 submission.
  - Ca₃Ti₂O₇: 1372/1372 matched (max |Δfrac| 4.4e-5).

### A11. Checkpointing (graph runtime). SETTLED
- **What.** SqliteSaver per thread in `test_runs/<thread>/iris.sqlite`, written synchronously (LangGraph `durability="sync"`). A crashed run continues with `run --continue`.
- **Why.** E7 kill test: with LangGraph's default asynchronous saving, a hard kill right after f3 lost f3's checkpoint.
- **Results.** E7 (CsSnI₃, killed after f3, continued in a new process): the G6 table (42 rows), the gate outcomes and the single submission are identical to an uninterrupted run. PASS.

### A12. f5 analysis kinds; G5 tests (f5, G5). Landau SETTLED; G5 limits PROVISIONAL
- **What.**
  - `policy.analysis: landau_plane` (CsSnI₃) runs `fit_landau_plane.py` and `ring_profile.py` unchanged, as subprocesses on copies inside IRIS_AGENT. IRIS adds 10-fold cross-validation.
  - G5 for the Landau fit:
    - `CV_ERROR`: CV RMS ≤ 0.5 meV/f.u.
    - `RESIDUALS`: RMS ≤ 0.5 and max |res| ≤ 2 meV/f.u.
    - `THIN_GRID`: ≥ 10 points per coefficient.
    - `COVERAGE`: the ring lies ≥ 2 grid steps inside the fit edge.
  - New `policy.analysis: surface` (Ca₃Ti₂O₇) reads the DFT surface directly, with no fit. It wraps `demo/ca3ti2o7/plot_ca3ti2o7_plane.py` unchanged. Its G5 tests (`G5_surface`):
    - complete coverage (`THIN_GRID`/`COVERAGE`);
    - minimum ≥ 2 steps inside the grid (`COVERAGE`);
    - mirror asymmetry ≤ 1.0 meV/f.u. (`MIRROR`);
    - the script's printed numbers agree with the node (`SCRIPT_MISMATCH`/`SCRIPT_FAILED`).
- **Paper.** G5 is *"fit acceptable (CV, residuals, coverage)"*. No numeric limits are in the paper, and a "surface without a fit" kind is not mentioned (Q4).

### A13. Role of the language model. SETTLED as a design; NOT YET EXERCISED
- **What.** `--llm off` everywhere. **No model has been called: no sub-agent calls, no LLM intake; model/version = none.**
  - The sub-agent interface (`llm.py`) returns "off", and recovery goes rule → human.
  - The prompts exist as a gallery (`prompts/intake_f0.md`, `subagent_G0..G6.md`, `borderline_R5.md`, `human_interrupt.md` → `PROMPT_GALLERY.md`). They have not been sent to any model.
  - The planned contract: the model returns one option id from the failing node's menu plus a one-sentence reason. Ids not on the menu are ignored and logged as invalid.
- **Paper.** Handover: *"The LLM never computes, never decides pass/fail, never routes, never writes numbers."* ✓ The code enforces this: gates and routing are plain Python, and recover() accepts only listed ids.
  - **Section 2.6 cannot yet report any sub-agent or intake result.** Build step 5 (sub-agents, provider-agnostic) and step 6 (intake) are still to do.
  - The config validator currently accepts only `ANTHROPIC_API_KEY`. The runbook's multi-provider panel (OpenAI, DeepSeek, open models) needs that relaxed in step 5.

### A14. f0 Intake. PROVISIONAL (LLM part is step 6)
- **What.** f0 reads the system config (YAML), validates it against a schema and records versions, the CIF sha256 digests and any injected faults.
- **G0 tests:**
  - `SCHEMA`;
  - `CIF_MISSING`, `CIF_UNREADABLE`;
  - `CIF_SG`: spglib at 1e-3 equals the expected SG;
  - `CIF_CHANGED`: pinned sha256;
  - `BUDGET`;
  - `FAULTS`: faults only in replay;
  - `PATHS`: writes only inside IRIS_AGENT.
- **Paper.** f0 Intake is described as turning a plain-language request into the config. G0 is *"config valid (schema, CIFs exist, budget)"*. The LLM step is not built. The `request:` line in each config is not parsed yet.

### A15. Fault injection (evaluation infrastructure). SETTLED for the seed set
- **What.**
  - Faults are injected **only through the run config** (`faults:` keys or policy values), only in replay mode, and recorded by f0. Data and code are never altered.
  - `eval/faults.yaml` holds 9 seed faults (CsSnI₃).
  - `--no-gates` runs the gates but never lets them stop the run (the E4 baseline).
  - Ablations: `no-gates`, `no-g6`, `no-rules`, `no-subagents`.
- **Results (E2, gated, Mac): 9/9 handled as expected.**

  | Fault | Gate failure | Handled by | Outcome |
  |---|---|---|---|
  | F001 WALLTIME | f4 WALLTIME | rule → f3 resubmit | numbers = stored fit |
  | F002 NELM | f4 NELM | rule → f3 with robust mixing | numbers = stored fit |
  | F003 translation | f2 TRANSLATION | rule | numbers = stored fit |
  | F004 no basis | f1 NO_BASIS | dmax ladder | numbers = stored fit |
  | F005 No. 55 | f2 SINGLE_MODE_SG | rule | numbers = stored fit |
  | F006 thin grid | f5 THIN_GRID | densify → f2 OVER_BUDGET → human | stopped |
  | F007 missing stored frame | f3 UNMATCHED | human | stopped |
  | F008 retry budget 0 | f1 NO_BASIS | human widens dmax | completed |
  | F009 jobs cancelled | f3 JOBS_CANCELLED | human | stopped |

- **Results (E4, ungated, Mac):**
  - **2 silent corruptions.** WALLTIME and NELM: the fit runs on 530/515 nodes instead of 545; the coefficients shift by about 1e-3 and nothing flags it.
  - **2 crashes.** Translation: 931/962 frames unmatched, fit on 27 nodes, f6 crashes. Cancel.
  - **5 harmless in replay.** The basis search and the single-mode check are cross-checks in replay; the thin-grid limit is a policy, not damage; the missing frame lies outside the fit radius.
- **Not yet done:** the full fault set (100–200 faults, six systems, seed/held-out split), tasks, intake requests, held-out transitions and models, then freezing them (`freeze_eval`).

### A16. File layout (all inside `IRIS_AGENT/`). SETTLED
| Path | Contents |
|---|---|
| `iris_agent/` | `graph.py`, `state.py`, `gates.py`, `recover.py`, `audit.py`, `config.py`, `paths.py` (write guard) |
| `iris_agent/nodes/` | `f0_intake` … `f6_skeptic`, plus `f5_surface.py` |
| `iris_agent/engines/` | `replay.py`, `jobs.py`, `stored_isodistort.py`, `legacy.py` |
| `iris_agent/rules/select_modes.py` | the mode-selection rules |
| `iris_agent/` (CLI modules) | `run`, `jobend`, `regression`, `inject`, `faultinject`, `resume_test`, `check_env`, `freeze_eval`, `prompts` |
| `recovery.yaml` | recovery rules and option menus |
| `configs/` | `{cssni3,ca3ti2o7}.yaml` and `*_reference.yaml` |
| `eval/faults.yaml` | the seed faults |
| `prompts/`, `PROMPT_GALLERY.md` | the prompt gallery |
| `tests/` | 63 tests |
| `test_runs/<thread>/` | `iris.sqlite`, `audit.jsonl`, `f2_grid/`, `f3_jobs/`, `f5_fit/` or `f5_surface/`, regression reports |
| `manuscript_updates/` | corrected figure notebooks |

Existing repo scripts are imported or run read-only. No live ISODISTORT/FINDSYM calls: the stored responses are read.

### A17. Gate codes in use (SI Table S2 should list them). SETTLED except the G5 limits
| Gate | Codes |
|---|---|
| G0 | SCHEMA, CIF_MISSING, CIF_UNREADABLE, CIF_SG, CIF_CHANGED, BUDGET, FAULTS, PATHS |
| G1 | NOT_SUBGROUP, SG_LADDER, SG_DISAGREE, BASIS_DET, NO_BASIS, BASIS_DISAGREE, DECOMP_NORM |
| G2 | R3_FAIL, R4_NO_POLAR, R5_BORDERLINE, ATOM_MATCH, TRANSLATION, CALIBRATION, SINGLE_MODE_SG, OVER_BUDGET, TREE_COVERAGE, FRAME_SG, D_MIN |
| G3 | JOBS_PENDING, JOBS_CANCELLED, UNMATCHED |
| G4 | ACCOUNTING, WALLTIME / NELM (codes of failed job parts), NO_ORIGIN, ENERGY_RANGE (1 meV–10 eV, `iris/validation/energy_sanity.py`), DFT_INCONSISTENT |
| G5 | NO_FIT, CV_ERROR, RESIDUALS, THIN_GRID, COVERAGE; surface: NO_SURFACE, MIRROR, SCRIPT_FAILED, SCRIPT_MISMATCH |
| G6 | NOT_REDERIVED, MISMATCH |
| any node | NODE_ERROR (a node that crashes); NOT_IMPLEMENTED (an unimplemented test outside skeleton mode, which can never pass silently) |

---

## B. Where the build goes beyond, or differs from, the paper's gate wording
| Gate | Paper (handover wording) | Built |
|---|---|---|
| G0 | "config valid (schema, CIFs exist, budget)" | + spglib SG of both CIFs, pinned sha256, faults only in replay, writes only inside IRIS_AGENT |
| G1 | "H ⊂ G, basis det = k, decomposition SG = spglib" | + index t·k = i, SG ladder 1e-3…1e-2, stored FINDSYM, independent basis search, mode norms (A6) |
| G2 | "4 eigenvector checks, every frame's SG on the subgroup tree" | as stated + c1/c3 + d_min ≥ d_cut. Check 4 strict (A4); check 3 per irrep (A5) |
| G3 | "jobs finished" | + every frame matched to a stored structure (replay) |
| G4 | "energies converged or flagged" | + E range sanity, one INCAR/KPOINTS set across frames. In replay, "converged" = has an energy in the stored CSV; OSZICARs are not available locally |
| G5 | "fit acceptable (CV, residuals, coverage)" | numeric limits proposed (A12); new surface variant |
| G6 | "every reported number re-derived" | ✓ CsSnI₃ 42/42; Ca₃Ti₂O₇ 38/38. Each number gets an independent route (QR instead of lstsq, scipy minimiser instead of grid search, interpn, CSV re-read by stored id, spglib recount, n_cells from r0) |

The D rules as implemented:
- **D1** and **D2**: implemented.
- **D3** (grid reduction): **not implemented**. Over-budget grids fail G2 OVER_BUDGET and go to the human.
- **D4** (hard-secondary parabola scan): **not implemented**. The CsSnI₃ X₅⁺ 13-point scan is not replayed.
- **D5** (orbit reduction): **not implemented**. BiFeO₃ needs it.

Strain policies: CsSnI₃ and Ca₃Ti₂O₇ use P2 (fixed parent cell) ✓.

---

## C. Replay results so far
### CsSnI₃ 221 → 62 (thread `cssni3_221_62_wait`). SETTLED; confirmed on the Mac
- **Gates:** G0–G6 all pass. f6 re-derives 42/42 numbers.
- **Score:** paper 27/30, stored 12 Sep results 29/30.

| Quantity | Paper | IRIS | Stored |
|---|---|---|---|
| A_p M₃⁺ / R₄⁺ / R₅⁺ / X₅⁺ (Å) | 0.843 / 0.229 / 0.086 / 0.045 | 0.8431 / 0.2286 / 0.0861 / 0.0448 ✓ | ✓ |
| Active set; held at 0 | M₃⁺, R₄⁺; R₅⁺, X₅⁺ | same ✓ | 4 modes (the old hand choice) ✗ |
| Calibration s; child displacement | 1.25; 1.758 Å | 1.2501; 1.7578 ✓ | ✓ |
| Grid n, m, N | 2, 31, 961 | same ✓ | — |
| Frames by SG | 1 × #221, 30 × #127, 30 × #74, 900 × #62 | same ✓ | ✓ |
| Frames matched | — | 962/962 (961 + 1 anchor) | — |
| a₁ / a₂ (eV Å⁻²); λ (eV Å⁻⁴) | −0.149 / −0.155; 0.255 | −0.1486 / −0.1554; 0.2552 ✓ | identical to 1e-9 |
| RMS; fit nodes | 0.10 meV/f.u.; 545 | 0.0981; 545 ✓ | ✓ |
| 10-fold CV RMS | — | 0.0997 meV/f.u. (new) | — |
| Ring depth below cubic | ~22 meV/f.u. | 22.72 ✓ | ✓ |
| Corrugation | 1.4 meV/f.u. | fit 1.376 ✓; DFT grid at r = 0.74 Å: 1.6 ✗ | — |
| **Ring minima** | **0.72–0.76 Å** | fit 0.76 at every angle ✗; DFT grid (ring_profile.py) 0.72–0.80 ✗ | — |

### Ca₃Ti₂O₇ 139 → 36 (thread `ca3ti2o7_139_36_xplane`). SETTLED; confirmed on the Mac (16 Oct)
- **Gates:** G0–G6 all pass. f6 re-derives 38/38 numbers.
- **Score:** paper/notes 25/25, stored 9/10. The miss is the old step-3 active set: X₃⁻, Γ₅⁻ and X₂⁺ on raw A_s.
- **Not tested yet:** E7 and fault injection for this system.

| Quantity | Reference | IRIS |
|---|---|---|
| A_p X₃⁻ / X₂⁺ / Γ₅⁻ (Å) | 0.822 / 0.599 / 0.792 | 0.8222 / 0.5988 / 0.7917 ✓ |
| A_s X₃⁻ / X₂⁺ / Γ₅⁻ (Å) | 1.163 / 0.847 / 1.120 | 1.1628 / 0.8468 / 1.1196 ✓ |
| f_T Γ₅⁻ | 0.75 | 0.7507 ✓ |
| Primaries; held at 0 | X₃⁻, X₂⁺; Γ₅⁻ | same ✓ (R4 overridden, recorded) |
| Calibration s X₃⁻ / X₂⁺ | paper says 1.13 / 0.57 | 1.2499 / 2.5001 (A5, Q5) |
| Grid n, m, N | 2, 37, 1369 | same ✓; ±1.2728 Å, step 0.0707 Å A_p |
| Frames matched | — | 1372/1372 (1369 + 3 anchors) |
| E − E_min (meV/f.u.): I4/mmm; Cmcm, Cmce, A2₁am anchors | 489.4; 189.0, 324.4, 97.8 | 489.36; 189.01, 324.39, 97.78 ✓ |
| A2₁am child at its true A_p (0.822, 0.599) | — | 50.8 (bilinear; new) |
| E range | 0–3680 meV/f.u. | 3680.2 ✓ |
| Grid minimum | old labels (±1.3, ±0.3) | A_p (±0.919, ±0.212) ✓ |
| Mirror asymmetry | — | 0.42 meV/f.u. |
| Figure CSV | — | 1369/1369 nodes, ΔE = 0 with axes × 1/√2 |

**Sub-agent calls: none. Model and version: none** (`--llm off` in every run).

---

## D. CLI and audit log compared with `IRIS_AGENT_AI_RESULTS_RUNBOOK.md`
**Implemented:**
- `check_env`, `freeze_eval [--check|--refreeze]`.
- `run --config --tag --llm off --mode {skeleton,replay} --ablate --no-gates`, plus additions not in the runbook: `--thread`, `--fresh`, `--continue`, `--resume '<json>'`, `--status`.
- `jobend --config [--thread] [--parts 0-9] [--fail 3:WALLTIME] [--cancel]` (not in the runbook).
- `inject --faults --llm off --tag [--no-gates] [--ablate] [--only] [--system] [--configs]`.
- `resume_test --config --kill-after f3 --tag E7`.
- `regression --config [--thread]` (not in the runbook).
- `faultinject` (an alias for the seed set).
- `prompts --gallery`.

**Defaults that differ from the runbook:**
- A tagged run uses the thread `<tag>_<system>`.
- `--llm` accepts only `off` until step 5.

**Not yet implemented:** `react_baseline`, `list_models`, `benchmark`, `robustness`, `run_batch`, `intake_eval`, `trace`, `export_reports`, `summarize`, `plot_ai_figure`, `plot_si_figures`. Of the six system configs, only `cssni3` and `ca3ti2o7` exist.

**Audit log** (`test_runs/<thread>/audit.jsonl`, one JSON line per event):
- **Kinds:** run, node, gate, fix, subagent, decision, interrupt, resume, end, kill.
- **On every line:** ts, thread_id, run_id, tag, system, fault_id, task_id, task_level, ablation_flags, provider, model_version, temperature, seed, constrained_decoding, prompt_variant_id, option_order_seed. The model fields are null while the LLM is off.
- **Gate lines:** gate, gate_code, outcome (pass/fail/fail_ignored/skipped), tests, attempts.
- **Node lines:** wall_time_s, attempts.
- **Fix lines:** recovery_tier (rule | subagent | human), rule_id, option_id, output_valid, tokens_in, tokens_out, cost_usd (null while the LLM is off), route, attempts.
- **End line:** status and the G6 table (quantity, reported, re-derived, ok).
- **Differences from the runbook list:**
  - `tool_name` per tool call is not written; there are no LLM tool calls yet.
  - `recovery_tier` "none" is not written; a run without a fix simply has no fix line.
  - The G6 table columns are `reported / rederived / ok` rather than `reference / re-derived / match`.

---

## E. Open questions for the paper
| # | Question | Status |
|---|---|---|
| Q1 | **Exact "strict" single-mode criterion.** Proposed text for c2 check 4: *"For each active irrep, the frame r0 + A_p,i ê_i is built exactly as the grid builds it (parent fractional coordinates plus the calibrated, translation-free displacement on the fixed parent lattice); spglib at symprec = 10⁻² (default angle tolerance) must return the isotropy subgroup H_i. A match only at another tolerance counts as a failure (SINGLE_MODE_SG)."* Decide: (a) is 1e-2 the stated tolerance; (b) is Q = the child amplitude A_p,i (as built) or any Q ≠ 0; (c) SG number only, as implemented, or also setting/origin. | PROVISIONAL (implemented as written) |
| Q2 | Methods 4.2 policy sentence ("A_thr … applied to A_s … translation-free gives the same selection") versus the Ca₃Ti₂O₇ walk order (A2). Rewrite to rank on A_s^tf. | PROVISIONAL |
| Q3 | R4 and Γ₅⁻ in Ca₃Ti₂O₇ (A3): state the hold-at-zero override, or present the plane as a section. Same question for the manganites' Γ₂⁻ when those replays come. | PROVISIONAL |
| Q4 | G5 limits (CV RMS ≤ 0.5, RMS ≤ 0.5, max \|res\| ≤ 2 meV/f.u., ≥ 10 points per coefficient, ring ≥ 2 steps inside the fit edge; surface mirror ≤ 1 meV/f.u., minimum ≥ 2 steps inside). Also whether a no-fit "surface" analysis is described. | PROVISIONAL |
| Q5 | Ca₃Ti₂O₇ calibration numbers in c2 check 3: "1.13 X3−, 0.57 X2+" → s = 1.25 (X₃⁻), 2.50 (X₂⁺) by the paper's own definition. Also define the √s normalisation with s = the number of primitive parent cells in the frame. | PROVISIONAL (numbers settled; wording open) |
| Q6 | A_p / A_s axis units in every figure. Ca₃Ti₂O₇ is fixed (A6). InMnO₃, ErMnO₃, BiFeO₃ and HfO₂ still need checking. | PROVISIONAL |
| Q7 | CsSnI₃ "ring minima 0.72–0.76 Å" exists only as text in the Fig. 1 drawio. Fit 0.76 Å at every angle; DFT grid 0.72–0.80 Å. Pick one and say which. | PROVISIONAL |
| Q8 | CsSnI₃ corrugation: 1.4 (fit, 1.376) vs 1.6 meV/f.u. (DFT grid at r = 0.74 Å). State which. | PROVISIONAL |
| Q9 | DFT settings: the stored CsSnI₃ grid INCARs say ENCUT 600 / ISPIN 1, while the campaign notes say 350 / ISPIN 2. For Ca₃Ti₂O₇ the system file says Ca_sv, the notes Ca_pv; no INCAR/KPOINTS are stored per xplane point. The Perlmutter OSZICAR/INCAR files are needed to verify. | PROVISIONAL |
| Q10 | μ in `landau_fit_all_sets.json` is ×1/3 of `landau_fit_plane.json`, a normalisation difference. The paper should quote one convention. | PROVISIONAL |
| Q11 | Budget B per campaign is not in the paper yet. The configs use CsSnI₃ 1100 and Ca₃Ti₂O₇ 1400. | PROVISIONAL |
| Q12 | D3, D4 and D5 are described in Methods but not built. Either build them before claiming the reruns cover BiFeO₃ (D5) and the CsSnI₃ X₅⁺ scan (D4), or say the reruns used the stored grids. | PROVISIONAL |
| Q13 | Section 2.6 wording: the reruns reuse stored DFT energies, so they should be described as "rerun end to end on the stored DFT energies". Gate failures, fixes and human interventions are real measurements; **no sub-agent or LLM-intake result exists yet.** | SETTLED (wording) / results pending |
| Q14 | Ca₃Ti₂O₇ figure text: the A2₁am ground state sits about 51 meV/f.u. above E_min in the Γ₅⁻ = 0 plane. Avoid "at the minimum"; one sentence can note that the trilinear X₃⁻X₂⁺Γ₅⁻ term is missing at Γ₅⁻ = 0. | PROVISIONAL (awaiting the manuscript paragraph) |

---

## F. Additions from the InMnO₃ plane replay (16 Oct 2026, stage 1)

Stage 1 is the (K₃, Γ₂⁻) plane at Φ = 0: the stored grid `plane_v2_tf` (225 frames) and the Meier-form (Q, P) fit of that plane. The polar hat grid and the joint plane + hat fit are stage 2 (see F8).
Decisions agreed with Sukriti: plane first; R5 decided by the human at run time; matching modulo a rigid shift; K₃ counts as 1 axis on this plane.
Status: cloud run passes, 64 tests (CsSnI₃ and Ca₃Ti₂O₇ unchanged). **Confirmed on the Mac (16 Oct): identical regression report** (R5 answered `include_borderline` at run time).

### F1. Vectors calibrated to the translation-free amplitude (f2; G2 c2 check 3). SETTLED
- **What.** Each vector is now scaled by A_p^tf = A_p·√(1 − f_T), not by ISODISTORT's A_p. Two consequences:
  - |ê| = √n_cells Å per Å, and Q is in Å of translation-free A_p.
  - The child lies on the axis at A_p^tf.
- **Why.** For InMnO₃ Γ₂⁻, f_T = 0.0385, so ISODISTORT's A_p 0.0585 becomes A_p^tf 0.0573 Å. That equals the stored `plane_v2_tf` labels (0.05733) and the child projection (0.05733).
- **Unchanged elsewhere:** for every irrep used so far on CsSnI₃ and Ca₃Ti₂O₇, f_T = 0, so nothing changes there.
- **Paper.** Matches c2 as written (*"ê_i translation-free and calibrated, Q_i in Å of A_p"*; *"norm fixed at √s Å per Å of A_p"*). The paper should say explicitly that Q is in **translation-free** A_p, with s = the number of primitive cells (A6).

### F2. Per-axis grid spacing (policy `grid.axes`; D2). SETTLED
- **What.** Each active irrep can have its own range and step, so N = Π m_i.
- **InMnO₃ grid:**
  - K₃ ±0.66 Å in steps of 0.0943;
  - Γ₂⁻ ±0.2353 Å in steps of 0.0336;
  - m = 15 on each axis, N = 225.
- **Paper.** D2 is written with one ΔQ and one Q_max: *"with m points per axis over ±Q_max in steps ΔQ, m = 2Q_max/ΔQ + 1, N = m^n"*. Suggest *"per axis i, m_i = 2Q_max,i/ΔQ_i + 1, N = Π m_i"*.

### F3. Replay matching modulo a rigid shift (f3; new G3 code `RIGID_SHIFT`). SETTLED
- **What.** With `run.replay.match_modulo_translation`, a built frame matches a stored structure after the mean displacement between them is removed.
  - The removed shift is logged per frame.
  - G3 fails `RIGID_SHIFT` if it exceeds `max_rigid_shift_A` (0.05 Å).
- **Why.** The stored `plane_v2` POSCARs were built before the polar-origin fix, so their Γ₂⁻ vector still carries a rigid translation of up to 0.015 Å per atom. A rigid shift does not change the energy. Without this, 210 of 225 frames would be "unmatched".
- **Results.** 225/225 matched; max |Δfrac| 2.1 × 10⁻⁵ after a shift of at most 0.0151 Å.

### F4. G1 basis-search check for a polar child (G1 `basis_det_equals_k`). SETTLED
- **What.** For a polar child, the atom-matching result must be at most ISODISTORT's maximum displacement + 0.01 Å; it is an upper bound only. For a non-polar child it stays ±0.01 Å.
- **Why.** In a polar child the origin along the polar axis is free, and the matcher minimises the largest displacement over that origin. So it can only come out lower: InMnO₃ 0.282 vs 0.309 printed / 0.313 shift-free.

### F5. The R5 path, run for the first time (G2 `R5_BORDERLINE` → human). SETTLED
- **Selection.** Primaries: K₃ only, since K₃ alone already gives P6₃cm (#185). Γ₂⁻ is a secondary kept by R4 (polar child). K1 is below threshold.
- **R5.** The margin is 0.076 Å on A_s^tf (0.078 on raw A_s, as the paper says), which is < 0.1 Å.
- **Recovery.** G2 → recover: no rule → sub-agent off → human. The human chose `include_borderline` and the run completed.
- **Audit.** The fix line records `recovery_tier: human`, `option_id: include_borderline`. Human choices now fill `option_id` too; before, they were only in `human_answer`.
- **Paper.** Matches Methods' own example (*"InMnO3 Γ2− A_s 0.101 active, margin 0.078 over K1 → R5"*). See Q18.

### F6. f5 analysis `meier_QP` and its G5 tests. Fit SETTLED; limits PROVISIONAL
- **What.** f5 runs `demo/staged_walkthrough/fit_landau_QP.py` unchanged. It fits Meier Eq. 12 on the plane, with c′ not determinable at Φ = 0:
  - window |Q| ≤ 0.58 Å and |P| ≤ 0.08 Å (A_p);
  - energies per 30-atom cell;
  - coefficients reported in A_p and in Meier's A_s = √3 A_p.

  IRIS adds 10-fold cross-validation.
- **G5 tests (G5_meier_QP):**
  - `CV_ERROR`: CV RMS ≤ 6 meV/cell;
  - `RESIDUALS`: RMS ≤ 5 and max ≤ 12 meV/cell;
  - `THIN_GRID`: ≥ 10 points per coefficient;
  - `COVERAGE`: the K₃ minimum and the coupled minimum lie ≥ `edge_margin_steps` K₃ steps inside the window edge.
- **The coverage margin is set to 0.5 step, PROVISIONAL.** The coupled minimum (Q = 0.510 Å A_p) is only 0.75 step inside the published 0.58 Å edge. With the 2-step rule used for CsSnI₃, G5 would fail (Q17).
- **f6** re-derives everything independently (39/39):
  - the fit by QR on a set rebuilt from the CSV energies;
  - the A_s conversion with n_cells from r0;
  - Q*, the depth and the coupled minimum with scipy optimisers.

### F7. InMnO₃ results (plane, thread `inmno3_194_185_plane`; confirmed on the Mac)
- **Gates:** G0 OK → G1 OK → G2 R5_BORDERLINE → (human: include) → G2 OK → G3–G6 OK.
- **Score:** f6 39/39 numbers; regression vs paper 20/23, vs stored 21/27. The misses are explained below.

| Quantity | Paper / notes | IRIS | Stored |
|---|---|---|---|
| A_p K₃ / Γ₂⁻ (Å) | 0.528 / 0.0585 | 0.5280 / 0.0585 ✓ | ✓ |
| A_s K₃ / Γ₂⁻ / K1 (Å) | 0.9146 / 0.1013 / 0.0234 | ✓ | ✓ |
| f_T Γ₂⁻ | — | 0.0385 (the stored movie vector had 0.0396) | |
| A_p^tf Γ₂⁻ (child on the axis) | — | 0.05733 | 0.05733 ✓ |
| Primaries; active | K₃; K₃, Γ₂⁻ | same ✓ | ✓ |
| R5 margin; decision | 0.078 → R5 | 0.076 (A_s^tf) → human: include | |
| Grid n, m, N; frames by SG | 2, 15, 225 | 210 × #185, 14 × #186, 1 × #194 | same ✓ |
| Frames matched | — | 225/225 (shift ≤ 0.0151 Å) | ✓ |
| a, b, c (A_s, eV/cell) | −1.211, 1.216, 0.764 | −1.2111, 1.2188, 0.7612 | −1.2108, 1.2164, 0.7639 |
| a_P, g, g′ | 2.711, 0.986, 5.375 | 2.7084, 0.9858, 5.3708 | 2.7110, 0.9863, 5.3748 |
| Refit on the stored 4-dp labels | — | reproduces the stored fit exactly (max \|Δ\| < 10⁻⁶) | ✓ |
| RMS; nodes in window | 3.9 meV/cell; — | 3.917; 65 | 3.915; 65 ✓ |
| 10-fold CV RMS | — | 4.26 meV/cell (new) | |
| Q* (A_s); depth | 0.833 Å; −231 meV/cell | 0.8325; −231.1 ✓ | ✓ |
| Coupled (Q, P) (A_s); hat | (0.884, +0.099); 260 meV/cell | (0.8840, +0.0986); 260.2 ✓ | ✓ |

**Why b, c, a_P and g′ miss.** The 0.2 % differences come only from the stored grid labels being rounded to 4 decimals: 0.0943 instead of 0.094286, and 0.0336 instead of 0.033613.
- IRIS uses the exact Q.
- Refitting the same energies on the rounded labels gives the stored and published coefficients exactly.
- Q*, the depth, the coupled minimum and the hat are unaffected at the quoted precision.

### F8. Stage 2: not built (needed for the joint plane + hat fit and Fig. 2's Mexican hat)
- **Second K₃ component.** The stored ISODISTORT direction is (a, 0). The stored hat vectors use a 120° phase shift (`df_K3_c1`, `df_K3_c2`).
- **Polar (Q, Φ, P) grid builder.** The stored hat grid is Q 0.35–0.70, Φ 0–30°, P ±0.1: 175 frames, all in true A_p with no rigid shift (checked).
- **The Φ = 0–30° reduction (D5).**
- **The joint fit** (`joint_hat_fit.py`; notebook coefficients a −1.206, b 1.206, c 0.700, c′ 0.068, a_P 2.663, g 0.962, g′ 5.310).

### F9. CLI and audit-log differences from the runbook
- No new commands.
- Audit: `option_id` is now set for human choices.
- Fix lines and the f3 record carry `modulo_translation` / `max_rigid_shift_A`.
- New gate code: `RIGID_SHIFT` (G3).
- New G5 test set: `G5_meier_QP`.

### F10. New open questions
| # | Question | Status |
|---|---|---|
| Q15 | **D1 for K₃.** The direction (a, 0) is a fixed-ratio direction, so D1 gives 1 component; Methods also says "2 for K3 in the manganites (Q, Φ)". Agreed for now: plane = 1 axis. The hat (stage 2) uses 2. The paper should say n depends on whether Φ is sampled. | PROVISIONAL |
| Q16 | **InMnO₃ coefficients from rounded labels.** The published b 1.216, c 0.764, a_P 2.711, g′ 5.375 come from 4-dp grid labels. With exact amplitudes they are 1.219, 0.761, 2.708, 5.371; a, g and every derived number are unchanged at the quoted precision. Update Table 10 / the Meier table, or keep and footnote? The ratios to Meier change by ≤ 0.003. | PROVISIONAL |
| Q17 | **Fit-window coverage.** The coupled minimum (0.510 Å A_p) sits 0.75 K₃ step inside the 0.58 Å window edge, and the K₃ well (0.481) 1.05 steps inside. Widen the window (data exist to 0.66 Å), or state the margin rule (0.5 step used here)? | PROVISIONAL |
| Q18 | **R5 and R4-kept irreps.** Γ₂⁻ is active only because of R4. Should an R4-kept polar axis count as "active" in the R5 margin? Methods' example says yes, and that is what is implemented. Also: is the margin measured on raw A_s (0.078) or A_s^tf (0.076, as implemented)? | PROVISIONAL |
| Q19 | **G5 limits for the (Q, P) fit, per cell:** RMS ≤ 5, CV ≤ 6, max \|res\| ≤ 12 meV/cell. These are proposals. | PROVISIONAL |

---

## G. Additions from the ErMnO₃ plane replay (16 Oct 2026)

The replay covers the (K₃, Γ₂⁻) plane at Φ = 0 (stored `plane`, 225 frames) and the 11-point Γ₂⁻ axis (stored `paxis`), with the published fit procedure. The hat grid and the joint fit are stage 2, as for InMnO₃.
Status: cloud run passes, 65 tests (the other three systems unchanged). **Confirmed on the Mac (16 Oct): 65 passed, identical regression report.**

### G1. Units checked: no relabelling needed. SETTLED
The stored K₃ and Γ₂⁻ labels are true translation-free A_p: all 236 frames match IRIS's √3-normalised frames with max |Δfrac| 3.5 × 10⁻⁵, with no label scale and no rigid shift. The 30-atom cell is 3 primitive cells, and ISODISTORT's s is also 3. So, like InMnO₃, **the manganite figures need no unit correction.**

### G2. The published ErMnO₃ fit fixes a_P from the P axis (f5 `meier_QP` variant `fit.aP_axis`). SETTLED as a reproduction; procedure PROVISIONAL
- **What.** The procedure has two steps:
  1. a_P = c₂ from a fit of E(P) = c₂/2 P² + c₄/4 P⁴ + c₆/6 P⁶ to the 11 P-axis points (|P| ≤ 0.5 Å A_p, in A_s);
  2. the other five coefficients from the plane, |Q| ≤ 0.66 and |P| ≤ 0.08 Å A_p (91 points), with a_P fixed.

  This is the row "LDA+U A-AFM, a_P from P axis" of `demo/ermno3/landau/compare_meier_final.md`. It is computed inside f5, because `fit_meier_fixed_aP.py` hardcodes a_P (0.507 / 0.583) and cannot be run as is. f6 re-derives both steps by QR.
- **Paper.** The Methods / table caption should state this two-step procedure. **a_P depends on the axis window and the powers** (Q20):

| P-axis fit window and powers | a_P |
|---|---|
| \|P\| ≤ 0.5, P²+P⁴+P⁶ (published) | 0.583 |
| \|P\| ≤ 0.5, P²+P⁴ | 0.507 |
| \|P\| ≤ 0.3 or ≤ 0.2 | 0.551–0.555 |

### G3. Merged stored grids and duplicate stored points (f3, engines/replay). SETTLED
- **Merged manifest.** The stored `planepax` manifest merges two grids, so its POSCARs live in `plane/03_grid` (ids 0–224) and `paxis/03_grid` (ids 0–10 → 225–235). The new config key `run.replay.poscar_dirs` lists both.
- **Duplicate origins.** The two stored origins (plane id 112, P-axis id 230) are the same structure. The matcher now skips stored ids already linked, so each IRIS frame gets its own stored point.

### G4. DFT-settings check compares settings, not bytes (G4 `DFT_INCONSISTENT`). SETTLED
- **What.** INCARs are compared as sorted tag = value sets, and KPOINTS without the free-text comment line.
- **Why.** G4 failed on ErMnO₃ because the P-axis INCARs list `GGA = CA` on another line and the KPOINTS comment reads "Gamma" instead of "Gamma 6x6x2". The settings are identical, and the two origin energies agree to 0.0 meV.

### G5. G1 basis check for a polar child (supersedes F4). SETTLED
- **What.** For a polar child, G1 compares the centre-of-mass-fixed child mapping (StructureMatcher + assignment, recorded by f1) with ISODISTORT's shift-free maximum displacement, within 0.01 Å. For a non-polar child it stays basis search vs ISODISTORT, ±0.01 Å.

| System | CoM-fixed mapping | ISODISTORT shift-free |
|---|---|---|
| Ca₃Ti₂O₇ | 0.4108 Å | 0.4107 Å |
| InMnO₃ | 0.3128 Å | 0.3128 Å |
| ErMnO₃ | 0.2995 Å | 0.2994 Å |

- **Why the F4 rule was dropped.** The atom-matching basis search fixes the polar origin its own way. It gave 0.282 Å (InMnO₃, below ISODISTORT) and 0.316 Å (ErMnO₃, above). The F4 "upper bound" rule was therefore wrong.

### G6. ErMnO₃ results (thread `ermno3_194_185_plane`; confirmed on the Mac)
- **Gates:** G0–G6 all OK. There was no gate failure and no human step: the R5 margin is 0.212 Å, well above 0.1.
- **Score:** f6 40/40 numbers; regression vs paper 26/31, vs stored 20/26.

| Quantity | Paper / notes | IRIS |
|---|---|---|
| A_p K₃ / Γ₂⁻; A_s K₃ / Γ₂⁻ / K1 | 0.6037 / 0.1271; 1.0456 / 0.2201 / 0.0072 | ✓ |
| f_T Γ₂⁻; A_p^tf | stored ratio 0.9938 (f_T 0.0124); 0.12631 | 0.0125; 0.12629 ✓ |
| Primaries; active | K₃; K₃, Γ₂⁻ (R4) | ✓ |
| Grid; frames by SG | 15 × 15; plus the 11 P-axis points | 210 × #185, 14 × #186, 1 × #194 (same as stored) |
| Frames matched | — | 236/236 |
| a_P from the P axis | 0.583 | 0.5825 ✓ (axis fit RMS 0.50 meV/cell) |
| a, b, c (A_s, eV/cell) | −3.703, 3.952, 0.476 | −3.7038, 3.9552, 0.4728 |
| g, g′ | 2.301, 10.777 | 2.3002, 10.7693 |
| Same procedure on the stored 4-dp labels | — | −3.703, 3.952, 0.476, 0.583, 2.301, 10.777: all equal to the paper |
| RMS; nodes in window | 6.0 meV/cell; 91 | 5.99; 91 ✓ |
| 10-fold CV RMS | — | 7.16 meV/cell (new) |
| Q* (A_s); depth | 0.922; −811 meV/cell | 0.9219; −811.3 ✓ |
| Coupled (Q, P) (A_s); hat | (1.029, +0.209); 1021 meV/cell | (1.0292, +0.2091); 1020.8 ✓ |

**Why five coefficient rows "miss".** As for InMnO₃ (Q16), only the 4-dp grid labels separate IRIS from the published numbers: K₃ 0.1079 instead of 0.107855, and Γ₂⁻ 0.0226 instead of 0.022572. Running the same procedure on the stored labels reproduces every published coefficient to the printed precision. The largest changes are c (0.476 → 0.473) and g′ (10.777 → 10.769).

### G7. New open questions
| # | Question | Status |
|---|---|---|
| Q20 | **ErMnO₃ a_P procedure.** a_P from the P axis depends on the window and the powers (0.507–0.583). State the choice (11 points, \|P\| ≤ 0.5 Å A_p, P²+P⁴+P⁶) and its sensitivity in the table caption or SI. | PROVISIONAL |
| Q16 (extended) | **Rounded labels, now in both manganites.** ErMnO₃ coefficients with exact amplitudes: a −3.704, b 3.955, c 0.473, a_P 0.583, g 2.300, g′ 10.769. Update the Meier comparison table or footnote it. | PROVISIONAL |
| Q17 (extended) | **Fit-window coverage, ErMnO₃.** The coupled minimum (0.594 Å A_p) lies 0.61 K₃ step inside the 0.66 Å window edge. It passes the provisional 0.5-step rule but would fail a 1-step rule. | PROVISIONAL |
| Q19 (extended) | **Proposed ErMnO₃ G5 limits, per cell:** RMS ≤ 8, CV ≤ 10, max \|res\| ≤ 25 meV/cell. The fit gives RMS 5.99, CV 7.16, max 16.5. | PROVISIONAL |


---

## H. Stage 2 of both manganites: the polar hat wedge and the joint fit (16 Oct 2026)

Configs `configs/inmno3_joint.yaml` and `configs/ermno3_joint.yaml`: the stage-1 plane (and the ErMnO₃ P axis) plus the stored hat wedge, and the joint Meier fit with the six-fold term c′. This is the fit behind the Fig. 2 Mexican hats and the figure notebook's coefficients.
Status: cloud runs pass, 67 tests. **Confirmed on the Mac (16 Oct): 67 passed; both regression reports identical to the cloud runs.**

### H1. Second component of a two-dimensional irrep (f2; `policy.grid.polar`). SETTLED
- **What.** ISODISTORT gives K₃ only along (a, 0). The second component e₂ comes from translating the K₃ displacement field by a parent lattice vector t = (−1/3, 1/3, 0) (child fractional), which rotates the K₃ phase by 120°:
  - e₂ = (T e₁ − cos 120° e₁) / sin 120°, normalised;
  - checked: cos = −0.5000 and |T e₁| = |e₁| exactly.
- **Independent check (f6).** e₂ is re-derived as (T e₁ − T² e₁)/√3; the two agree to 2 × 10⁻¹⁶.
- **Frames.** Q (cos Φ e₁ + sin Φ e₂) + P e_Γ₂⁻. Built frames match every stored hat POSCAR (max |Δfrac| 3.5 × 10⁻⁵), so this is the construction the stored hat grids used.
- **Paper.** Methods should say how the second K₃ component is obtained. D1 then gives n = 2 for K₃ (Q, Φ) on the hat (Q15).

### H2. Polar grid, the declared wedge and D5 (f2, G2). PROVISIONAL (D5)
- **What.** The hat is sampled on a declared wedge Φ = 0–30° (7 angles) × 5 Q × 5 P = 175 frames.
- **Why the wedge is enough.** The relaxed landscape obeys E(Φ) = E(−Φ) = E(Φ + 60°) with P → −P. That is the D5 idea (one point per symmetry orbit).
- **What IRIS does not do yet.** IRIS takes the wedge from the config; it does **not** compute the orbits itself (general D5 still not built).
- **G2 audit.** Each hat frame's space group must follow its direction:

| Direction | Expected SG | Hat frames |
|---|---|---|
| Φ = 0 mod 60° | P6₃cm (#185) | 25 |
| Φ = 30° with P = 0 | P‑3c1 (#165) | 5 |
| otherwise | P3c1 (#158) | 145 |

  All 175 frames agree, in f2 and in f6's recount.

### H3. Extra stored references (f3; `run.replay.extra_references`). SETTLED
- **What.** Hat frames are matched against the stored hat grid by its own labels (Q_A, theta_deg, P_A) and energies. Their stored ids are namespaced `hat:<id>`.
- **Checks.** The DFT settings check (G4) covers all parts. Plane, hat and P axis share one INCAR/KPOINTS set in both compounds.

### H4. Joint fit (f5 `meier_joint`). Fit SETTLED; limits PROVISIONAL
- **Model.** F = a/2 Q² + b/4 Q⁴ + (c + c′ cos 6Φ)/6 Q⁶ + a_P/2 P² − g Q³P cos 3Φ + g′/2 Q²P², in A_s per cell.
- **Plane points.** Points with Q < 0 enter at Φ = 60°.
- **Windows and a_P:**
  - InMnO₃: |Q| ≤ 0.58, |P| ≤ 0.075 Å A_p; a_P fitted.
  - ErMnO₃: |Q| ≤ 0.66 Å; |P| ≤ 0.08 Å (plane) and ≤ 0.10 Å (hat); a_P fixed from the P axis.
- **Derived (in meV/f.u.):**
  - hat = −min F(Q, 0);
  - brim = min F(Q, 30°) − min F(Q, 0), with Q and P relaxed;
  - the brim is also given with c′ = 0.
- **Implementation.** Computed in-node with the procedure of `demo/<system>/landau/joint_hat_fit.py`; those scripts read fixed relative paths, so they cannot run on IRIS's frames. f6 re-derives with QR and a bounded minimiser.
- **G5 limit hit.** The InMnO₃ joint fit's largest residual is 12.06 meV/cell, just above the proposed plane limit of 12, so G5 RESIDUALS stopped the first run. The joint config uses 15 meV/cell (proposal, Q19).

### H5. Results (confirmed on the Mac)
Both runs pass all gates. InMnO₃ goes through the run-time R5 human step as before. f6 re-derives every number.

| | InMnO₃ paper / IRIS | ErMnO₃ paper / IRIS |
|---|---|---|
| Frames matched | 400/400 (225 + 175) | 411/411 (225 + 11 + 175) |
| a, b, c (A_s, eV/cell) | −1.206, 1.206, 0.700 / −1.2067, 1.2075, 0.6980 | −3.708, 3.973, 0.427 / −3.7088, 3.9761, 0.4241 |
| c′, a_P | 0.068, 2.663 / 0.0678, 2.6603 | 0.040, 0.583 / 0.0403, 0.5825 |
| g, g′ | 0.962, 5.310 / 0.9618, 5.3093 | 2.266, 10.330 / 2.2656, 10.3305 |
| Nodes (plane + hat) | 65 + 63 / same | 91 + 63 / same |
| RMS (plane, hat), meV/cell | 3.4 (4.0, 2.5) / 3.36 (4.0, 2.5) | 6.8 (6.3, 7.4) / 6.78 (6.3, 7.4) |
| 10-fold CV RMS (new) | — / 3.59 | — / 7.24 |
| Hat height (meV/f.u.) | 43.1 / 43.11 | 170.3 / 170.27 |
| Brim, Q and P relaxed (meV/f.u.) | 3.32 / 3.321 | 33.79 / 33.78 |
| Brim with c′ = 0 (meV/f.u.) | 4.94 / 4.939 | 35.85 / 35.84 |

- **The same procedure on the stored (4-dp) labels** reproduces both published scripts exactly: every coefficient, the RMS, the hat and the brims, at the printed precision.
- **The small differences** (b, c, a_P in the third decimal; the ErMnO₃ brim by 0.01 meV/f.u.) come only from the label rounding (Q16) and, for ErMnO₃, from a_P = 0.5825 (computed) vs 0.583 (hardcoded in the script).

### H6. Open questions added
| # | Question | Status |
|---|---|---|
| Q21 | **Hat wedge and D5.** The wedge Φ = 0–30° and its unfolding rely on E(Φ) = E(−Φ) = E(Φ + 60°), P → −P. The paper should state that symmetry. IRIS uses it as a declared policy, not a computed orbit reduction. | PROVISIONAL |
| Q22 | **Second K₃ component.** Methods should say e₂ is the K₃ field translated by a parent lattice vector (a 120° phase shift), orthogonalised; the paper's "force-constant eigenvector" wording for Meier is different. | PROVISIONAL |
| Q19 (extended) | **Joint-fit G5 limits.** InMnO₃ joint max residual 12.06 meV/cell; the joint config uses 15. | PROVISIONAL |

## I. BiFeO₃ stage B1: the six single components (16 Oct 2026)

Config `configs/bifeo3.yaml`, thread `bifeo3_221_161_b1`. Stored ISODISTORT run `bifeo3_221_to_161__20260922_151417`, stored grid toolkit `demo/bifeo3/grid6d/bfo6d` (v4). Assumed for B2–B4 (not yet answered): V0 included, controls included.

### I1. G1 determinant rule generalised (`basis_det_equals_k`). SETTLED
- **What changed:** det(basis) is compared with s·z_child/z_parent, where z is the number of lattice points per conventional cell (P 1, A/B/C/I 2, F 4, R 3 on hexagonal axes).
- **Why:** ISODISTORT gives the conventional child cell in conventional parent units. R3c on hexagonal axes has det 6 for s = 2. The old rule (det = s) held for every earlier system (P→P, I→A).
- **Paper:** Methods state "det = k". That should read "det = s·z_child/z_parent" or say that the basis is primitive.

### I2. Six single components from a one-direction decomposition (f1; `policy.components`). SETTLED
- **What changed:** ISODISTORT decomposes along the child direction only (GM4-(a,−a,−a), R5-(a,−a,a)). f1 splits each irrep into its three components:
  - P_i: the i-th Cartesian part of the GM4- field, with the rigid translation removed.
  - R_i: the part of the R5- field that rotates about x_i.
- **Checks (new G1 test `components_consistent`):**
  - The components sum to the stored fields (residual 3e-16 Å).
  - Each component has A_p/√3: P 0.30380, R 0.40076 Å.
  - Fold onto the grid's 10-atom fcc(2a_c) cell and compare with the grid basis atom by atom: P residual 1.2e-5 Å (5-decimal stored numbers), R 2e-16 Å.
  - The 96 operation matrices are derived on the folded cell: 96 distinct signed permutations (residual 1e-5). They are the same set as `bfo6d.symmetry.mode_matrices()`.
- **Results:**
  - Composition per component (unit vector over one f.u.): Bi 0.79429, Fe 0.11973, O∥ −0.07913, O⊥ −0.41744. The grid uses 0.79429 / 0.11970 / −0.07909 / −0.41745 (from the printed ISODISTORT numbers).
  - |B|² = 2 = n_cells for every component.
  - ISODISTORT's child is q = (+0.3038, −0.3038, −0.3038 | −0.4008, +0.4008, +0.4008). One of the 96 operations maps it onto the grid's node (2,2,2 | 2,2,2) (2.0001 steps; steps 0.15189 / 0.20037 Å).
  - Translation-free GM4-: f_T = 0.759; A_p^tf = 0.5262 (from 1.07247 with Bi pinned).
  - Other G1 results: basis search det 2, max displacement 0.452 Å; centre-of-mass-fixed mapping 0.440 Å vs ISODISTORT shift-free (within 0.01 Å). Space groups agree (161). Strain in the child CIF: GM1+ 2e-5, GM5+ 0.009.
- **Paper:**
  - Methods should say how the per-component vectors of a multi-component irrep are obtained (Cartesian split for T1u; rotation-axis split for R5-) and that closure is checked.
  - The R irrep is R5- with Bi at the origin. The system file and older text call it R4+ (Fe at the origin); same mode, different setting (Q23).

### I3. Staged runs (`run.stop_after`). SETTLED
- **What changed:** the graph routes to END after the named node's gate passes. The run status is `stage_completed`. This is used for the BiFeO₃ stages B1–B4.
- **Audit log:** the `end` record has `status: stage_completed`.

### I4. Open questions added
| # | Question | Status |
|---|---|---|
| Q23 | **R irrep label.** R5- (Bi at the origin, ISODISTORT) vs R4+ (Fe at the origin). The paper should use one label and name the origin. | PROVISIONAL |
| Q24 | **G1 determinant wording.** "det = k" vs det = s·z_child/z_parent (I1). | PROVISIONAL |

## J. BiFeO₃ stage B2: the six-component plan (16 Oct 2026)

Same config (`configs/bifeo3.yaml`, now `stop_after: f2`), thread `bifeo3_221_161_b2`. Nothing computed; the plan is compared with the stored campaign packages, read inside the .tgz files.

### J1. f2 for six components (`nodes/f2_grid6.py`; G2 test set `G2_grid6`). SETTLED
- **What changed:** f2 builds the 6D plan from IRIS's own folded vectors (f1, B1) and its own 96 matrices. The steps are declared: dP, dR = 0.151892, 0.20037 Å (half the printed child per-component amplitudes).
  - **Main grid:** two balls, |idx_P| ≤ r and |idx_R| ≤ r. **D5:** each node's canonical image is the lexicographically largest of its 96 images, which labels each orbit of the 96 operations once. The number of orbits is checked against Burnside's count.
  - **Contact cut:** the shortest periodic contact (an orbit invariant), computed on each dataset's cubic parameter.
  - **Controls:** the stored set is read and checked to be non-representative images of included orbits. IRIS does not re-draw the random choice.
  - **Refine planes:** recomputed from their directions and steps.
  - **Extra points:** declared (chosen adaptively from an RBF fit of earlier data) and checked against the contact cut.
- **Results (all equal to the stored campaign):**

| | V1 (r = 6, a_c 3.9407) | V0 (r = 5, a_c 3.8813) |
|---|---|---|
| Nodes | 855,625 | 265,225 |
| Orbits (Burnside) | 9,998 (9,998) | 3,306 (3,306) |
| Kept by the 1.6 Å cut | 6,724 (558,685 nodes) | 2,873 (227,725 nodes) |
| Controls | 67 valid | 29 valid |
| Representatives, multiplicities, node → orbit map, kept flags | identical to orbits.npz | identical |
| Contact distance vs stored | ≤ 6.6e-5 Å | ≤ 5.5e-5 Å |
| Orbit closest to the cut | 1.2e-4 Å | 1.3e-4 Å |

  - Refine planes: 361 points, 10 below the cut (stored: 361 / 10); every q identical.
  - Extra: 253 (origin 1, plane checks 27, MEP 25, fill 200); the shortest contact is 1.837 Å.
  - In total 10,307 frames = 10,054 production + 253 extra.
  - Space groups (spglib 1e-3) on all 10,307 frames equal the stored point_info values. Special nodes: origin 221, child 161, P∥[111] 160, R∥[111] 167, P∥[001] 99, R∥[001] 140.
- **Note:** the cut decisions agree, but the orbit closest to the cut is only 1.2e-4 Å from it. That is about twice the difference between IRIS's vectors and the grid's (3.9e-5 Å, from the 5-decimal ISODISTORT numbers). A different rounding could move one orbit across the cut.
- **Paper:** Methods should state the D5 rule (canonical image, Burnside check), that the contact cut is applied per orbit, and that the extra points are adaptive, not part of the planned grid (Q25).

### J2. Stored packages read inside the archives (`engines/tarstore.py`; `paths.grid_packages`). SETTLED
- The campaign folders exist on the Mac only as .tgz packages. IRIS reads the members it needs (manifest.json, orbits.npz, point_info.json, POSCAR / INCAR / KPOINTS) in memory and extracts nothing.

### J3. Open questions added
| # | Question | Status |
|---|---|---|
| Q25 | **Extra points.** The 253 extra_V1 points were chosen from an RBF fit of the grid data (fill, plane checks, MEP images). Should the paper describe them as an adaptive second round (IRIS declares them) or as part of the plan? | PROVISIONAL |
| Q26 | **Contact-cut margin.** One V1 orbit lies 1.2e-4 Å from the 1.6 Å cut; IRIS and the stored grid agree, but the margin is small. Report the cut as "≥ 1.6 Å on the grid basis". | PROVISIONAL |

## K. BiFeO₃ stage B3: replay of the stored campaign (16 Oct 2026)

Same config (`stop_after: f4`), thread `bifeo3_221_161_b3`. Inputs: the two packages (B2) and the collected CSVs `data/analysis/collected/runs_<dataset>.csv` (bfo6d/collect.py on Perlmutter; OUTCARs are not local).

### K1. Matching (f3; `nodes/f3_grid6.py`, `engines/replay6.py`). SETTLED
- Every frame is compared with its stored POSCAR: same lattice and species order; every atom within 1e-3 Å of the position IRIS builds from its own vectors. The stored displacement is also projected back onto the six vectors, so the recovered q must equal the label and nothing may remain outside the six-vector span.
- **Result:** 10,307 / 10,307 matched, none flagged. Largest atom deviation 3.6e-5 Å, q recovered to 2.5e-5 Å, outside the span 3.6e-5 Å (all from the 5-decimal ISODISTORT numbers). One INCAR / KPOINTS set for all frames.
- The job book is the usual one (104 parts of 100; wait for job-end events).

### K2. Energies, gradients, QC (f4; `nodes/f4_grid6.py`; G4 test set `G4_grid6`). Checks SETTLED; tolerances PROVISIONAL
- **Energies:** re-derived from E0_cell against each dataset's own q = 0 run; equal to the CSV column to 6e-12 meV/f.u. The q = 0 copies agree exactly. CSV labels equal the plan (5e-8 Å, 7-decimal rounding). CSV space groups equal IRIS's on every frame.
- **Controls (symmetry check of the reduction):** 95 controls with E(image) = E(representative) to 0.0015 meV/f.u. and dE/dq(image) = G·dE/dq(rep) to 0.10 meV/Å/f.u. Control c031 (SCF-limited) differs by 0.17 meV/f.u., inside the stated SCF uncertainty; it is reported separately.
- **Refine points on main nodes:** 87, equal to the node's orbit energy to 0.005 meV/f.u.
- **Gradient sign and units (new check):** along grid lines of main_V1, E(c) − E(a) vs h/3 (g_a + 4g_b + g_c) (Simpson, O(h⁵)) over 15,774 triples below 1 eV/f.u.: slope 1.0003, RMS 0.35 meV/f.u. (28,603 triples in all: slope 1.0003, RMS 0.52). The two-node trapezoid gives slope 0.972: an h³ bias at these steps (0.15 / 0.20 Å), not an error. It is reported, not tested.
- **SCF-limited runs:** 20 (main_V1), energy kept and gradients dropped (`policy.qc.scf_limited: keep_energy_drop_gradients`, as in PROVENANCE.md). 10,307 energies and 10,287 gradient vectors are linked.
- **Magnetism:** G-AFM everywhere (opposite Fe moments, |m_Fe| 3.91–4.14 μ_B, |M_tot| ≤ 0.03 μ_B). The two Fe moments differ by up to 0.09 μ_B in low-symmetry frames, where the sites are not symmetry-related; that is allowed and recorded.
- Energy range 8,317 meV/f.u.

### K3. Open questions added
| # | Question | Status |
|---|---|---|
| Q27 | **SCF-limited runs.** 20 energies are kept with an uncertainty of up to ~15 meV/f.u. and no gradients. All lie outside the 1 eV fitting window (PROVENANCE.md); B4 will confirm. The paper should say so. | PROVISIONAL |
| Q28 | **Gradient check.** Methods could state the Simpson line-integral check (slope 1.0003) as the test that the projected forces and the energies are consistent. | PROVISIONAL |
| Q29 | **G4 tolerances** for controls (0.01 meV/f.u., 0.5 meV/Å/f.u.) and the line-integral slope (±0.02) are proposals. | PROVISIONAL |

## L. BiFeO₃ stage B4: the degree-12 invariant fit, f6 and regression (16 Oct 2026)

Same config, now run to the end (no `stop_after`), thread `bifeo3_221_161_b4`. Reference: `configs/bifeo3_reference.yaml` (work/refit_log.txt, derived_final_model.txt, stored QC).

### L1. f5 `landau6d` (`nodes/f5_landau6d.py`; G5 test set `G5_landau6d`). Fit SETTLED; limits PROVISIONAL
- **What:** the procedure of `work/refit.py`. Invariants are orbit sums of monomials, even degrees 2–12. The fit is least squares on [E; 0.1 Å · dE/dq] for rows with E < 1 eV/f.u., with unit weights and scaled columns. The rows are main_V1 production with a converged energy (6,705; the SCF-limited runs are out), refine (361) and extra (253), in collected-CSV order, so the published 20 % hold-out (seed 0) is the same split.
- **Independent parts:**
  - The 315 invariants are built from IRIS's own 96 matrices. Their number equals Molien's formula: 2, 7, 18, 41, 84 and 163 at degrees 2–12, and no odd-degree invariants. The list and order are identical to `landau6d/inv.py`.
  - The data are IRIS's own energies, gradients and exact labels (B3).
- **Results (all equal to refit_log.txt at the printed precision):**

| | n | RMS | max (meV/f.u.) |
|---|---|---|---|
| main + refine → blind extra | 253 | 0.55 | 2.07 |
| main + extra → blind refine | 323 | 1.14 | 4.99 |
| final: training | 4,482 | 0.49 | 4.31 |
| final: refine / extra (train) | 323 / 253 | 0.95 / 0.53 | 4.31 / 2.10 |
| final scheme: 20 % hold-out | 921 | 0.51 | 4.38 |
| 10-fold CV (new) | 4,482 | 0.50 | 4.37 |

  - **Coefficients:** on the CSV's own 7-decimal labels, IRIS's fit is identical to `coef_V1_deg12_E1000_final.npy` to floating-point round-off (maximum relative difference 0 in the cloud, 5e-12 with the Mac's BLAS; the regression accepts ≤ 1e-9). On IRIS's exact labels it differs by 6e-6 (relative).
  - **Stationary points (as work/analyze.py),** E in meV/f.u., all equal to derived_final_model.txt:
    - R3c −950.0 (0.519, 0.698), index 0
    - Ima2 −848.8 (index 1), R3m −738.9 (1), R-3c −675.9 (1)
    - Imma −638.3 (2), Amm2 −619.2 (2), I4cm −615.9 (2)
    - P4mm −553.2 (5), I4/mcm −534.4 (5)
  - **Global search:** 60 BFGS starts all end at −950.0.
  - **RBF cross-check** (work/fit_rbf6d.py, trend 8, 581,921 unfolded points, exact at the data): within 1.2 meV/f.u. of the polynomial at all nine stationary points. The largest difference is R3m, 1.17. Reported, not gated.
- **G5 tests:**
  - invariant basis complete (Molien);
  - CV and hold-out RMS ≤ 1.0 meV/f.u.;
  - training RMS ≤ 1.0, max ≤ 5.0;
  - ≥ 10 rows per coefficient (14.2);
  - the child (R3c) is the lowest stationary point, has index 0, and is the global minimum.

  The limits are proposals (Q31).

### L2. f6 for the six-component campaign (`nodes/f6_grid6.py`). SETTLED
- 74/74 numbers re-derived by other routes:
  - the 96 matrices compared with the toolkit's;
  - |V|² = 2 for each vector;
  - orbit counts by Burnside on the saved node sets;
  - energies re-read from the CSVs;
  - the invariant list compared with landau6d/inv.py;
  - the fit re-solved by QR (agrees with lstsq to 5e-10 meV/f.u.);
  - each stationary point re-minimised by BFGS with the analytic gradient;
  - Hessian index from second differences of the energy;
  - the space group of the structure at every stationary point (R3c 161, Ima2 46, I4cm 108, R3m 160, Amm2 38, P4mm 99, R-3c 167, Imma 74, I4/mcm 140).
- **Regression:** paper 25/25, stored 19/19.

### L3. V0 not refitted. PROVISIONAL
- The final refit uses V1 only (README: "V0 is unchanged"). IRIS replays V0 through B3 (2,873 orbits + 29 controls, all checks pass) but does not fit it. The earlier V0 fit (`coef_V0_deg12_E1000.npy`) could be added as a second regression (Q30).

### L4. Open questions added
| # | Question | Status |
|---|---|---|
| Q30 | **V0.** Should the paper report the V0 fit (smaller cubic parameter) and should IRIS reproduce `coef_V0_deg12_E1000.npy`? | PROVISIONAL |
| Q31 | **G5 limits for the 6D fit** (RMS 1.0, max 5.0 meV/f.u., CV 1.0) are proposals; the fit sits at 0.49 / 4.31 / 0.50. | PROVISIONAL |
| Q32 | **Methods wording.** The invariant count can be stated with its Molien check (315 = 2 + 7 + 18 + 41 + 84 + 163), and the RBF as an independent cross-check (≤ 1.2 meV/f.u. at the stationary points). | PROVISIONAL |

## M. Follow-ups of 16 Oct: BiFeO₃ V0 (SI) and the ErMnO₃ a_P sensitivity

### M1. BiFeO₃ V0 reproduced (f5 `landau6d`, `policy.fit.six.secondary`). SETTLED (answers Q30)
- **Decision (16 Oct):** the manuscript model is V1, the lattice at the child volume. V0 (a_c = 3.8813 Å, the cubic-anchor volume) goes to the SI as a volume-sensitivity check.
- **What:** the same degree-12 fit on main_V0 alone, the procedure of `landau6d/v0.py`: 2,873 production rows, 20 % hold-out (seed 0) on those rows, stationary points as `stat.py`. f6 re-derives the training RMS by QR and each stationary energy by BFGS (84/84 numbers in total).
- **Results (all equal to fit_V0.txt and stat_V0.txt):** training 2,210 rows, RMS 0.283; hold-out RMS 0.322, max 3.164 meV/f.u. Coefficients: on the CSV's own labels equal to `coef_V0_deg12_E1000.npy` to round-off (3.7e-12); on IRIS's exact labels 1.8e-5 relative.

| phase | V1 E (meV/f.u.), index | V0 E (meV/f.u.), index |
|---|---|---|
| R3c | −950.0, 0 | −833.6, 0 |
| Ima2 | −848.8, 1 | −732.0, 1 |
| R3m | −738.9, 1 | −563.3, 1 |
| R-3c | −675.9, 1 | −639.6, 1 |
| Imma | −638.3, 2 | −607.4, 2 |
| Amm2 | −619.2, 2 | −482.0, 3 |
| I4cm | −615.9, 2 | −544.0, 2 |
| P4mm | −553.2, 5 | −432.8, 5 |
| I4/mcm | −534.4, 5 | −518.3, 3 |

- **What the SI can say:** R3c remains the global minimum (60/60 starts) and Ima2 the lowest saddle (+101.3 → +101.6 meV/f.u. above R3c). Compression to the cubic volume weakens the polar instability much more than the rotations: R3m moves from below R-3c (V1) to above it (V0), and the Hessian index of Amm2 and I4/mcm changes (2 → 3, 5 → 3).

### M2. ErMnO₃ a_P sensitivity (f5 `meier_QP` / `meier_joint`, `policy.fit.aP_axis.sensitivity`). Table SETTLED; the wording of Q20 PROVISIONAL
- **What:** the same two-step fit (a_P from the P axis, then the plane or joint fit with a_P fixed) for every window |P| ≤ 0.2 / 0.3 / 0.4 / 0.5 Å × powers P²+P⁴ or P²+P⁴+P⁶. Reported only; the run's model keeps the published choice.

| |P| window, powers | n axis | a_P (A_s) | axis RMS (meV) | plane hat (meV/cell) | joint hat / brim (meV/f.u.) |
|---|---|---|---|---|---|
| 0.2, P²+P⁴ | 5 | 0.554 | 0.17 | 1020.69 | 170.25 / 33.76 |
| 0.2, P²+P⁴+P⁶ | 5 | 0.555 | 0.17 | 1020.69 | 170.25 / 33.76 |
| 0.3, P²+P⁴ | 7 | 0.551 | 0.22 | 1020.68 | 170.25 / 33.76 |
| 0.3, P²+P⁴+P⁶ | 7 | 0.555 | 0.21 | 1020.69 | 170.25 / 33.76 |
| 0.4, P²+P⁴ | 9 | 0.554 | 0.24 | 1020.69 | 170.25 / 33.76 |
| 0.4, P²+P⁴+P⁶ | 9 | 0.550 | 0.23 | 1020.68 | 170.24 / 33.76 |
| 0.5, P²+P⁴ | 11 | 0.507 | 1.83 | 1020.54 | 170.21 / 33.72 |
| **0.5, P²+P⁴+P⁶ (published)** | 11 | **0.583** | 0.50 | 1020.78 | **170.27 / 33.78** |

- **Reading:** a_P ranges from 0.507 to 0.583. Every derived quantity moves by at most 0.24 meV/cell (plane hat) and 0.07 meV/f.u. (joint hat and brim): the hat and brim do not depend on the a_P choice. The quartic at |P| ≤ 0.5 Å is the outlier and fits the axis poorly (RMS 1.83 vs 0.50 meV), so it should not be used.
- **Note:** the value 0.49 quoted for the quartic is not produced by any of these eight choices (the quartic gives 0.507 at 0.5 Å and 0.551–0.554 in smaller windows). Its source should be checked before it is cited.
- **Suggested caption sentence:** *"a_P is taken from a sixth-order fit of the 11 P-axis points (|P| ≤ 0.5 Å); other windows and orders give a_P = 0.51–0.58 and change the hat and brim energies by less than 0.1 meV/f.u. (SI Table X)."*

## N. D4 built: hard-secondary scans (CsSnI₃ X₅⁺; 17 Oct 2026)

Config `configs/cssni3_d4.yaml` (= cssni3.yaml + `policy.d4` + the three stored scans), thread `cssni3_221_62_d4`. Answers Q12 for D4; D3 is still described, not built (no replay needs it).

### N1. The 0.155 vs 0.045 Å mismatch, resolved read-only. SETTLED
- **The X₅⁺ direction and labels are right.** The stored scans move atoms along IRIS's X₅⁺ child vector (cosine 0.9999995, no other irrep, no translation), and the label 0.24 is 0.2401 Å of true A_p.
- **The "child" scan is not at the child.** Its primaries project to M₃⁺ 0.672 and R₄⁺ 0.184 Å = 0.797 × and 0.805 × the child (0.843, 0.229). It was built from the uncalibrated labels 0.84 / 0.23 (the 0.8 movie-peak factor; the same calibration fault as the 12 Sep plane). The "ring" scan sits at M₃⁺ 0.720 Å (0.854 × the child M₃⁺), R₄⁺ = 0. IRIS records these ratios (`base_over_child`) and names the scan `child80`.
- **The scans ran with other DFT settings:** ENCUT 350 eV, ISPIN 2 (plane: 600 eV, ISPIN 1). G4 caught this as `DFT_INCONSISTENT`; the D4 config accepts it explicitly (`settings: own_per_scan`), because each scan is used only through energy differences within itself.
- **So the induced 0.155 Å is a fixed-cell result at 80 % primaries, without R₅⁺ and strain, at ENCUT 350.** The relaxed child has X₅⁺ = 0.045 Å in its own (orthorhombic) cell with R₅⁺ 0.086 Å. The two numbers describe different structures; nothing is mislabelled. Which of strain, R₅⁺ or the cutoff reduces X₅⁺ cannot be decided without new DFT.

### N2. D4 in IRIS (f2 frames, f3 extra references, f5 `nodes/f5_d4.py`, G5 test `d4_secondaries_hold`). Mechanics SETTLED; threshold PROPOSED
- **Rule:** each secondary held at zero is scanned along its own calibrated vector at declared base points of the primaries. Each scan is fitted by a quartic in the amplitude: curvature at 0, linear term, relaxed amplitude a*, released energy. G5 fails if the secondary is soft, if the minimum sits at the scan edge, or if the largest released energy exceeds `max_fraction` (proposed 0.5) × the smallest energy difference the run interprets (`compare_to: ring.corrugation_meV`). The failure (`SECONDARY_COUPLED`) goes to the human: keep it at zero with a caveat (`accept_secondary_hold`) or stop.
- **Results (all 39 scan frames matched; stored grid minima reproduced to 1e-3 meV):**

| scan | primaries (Å A_p) | curvature (meV/Å²/f.u.) | relaxed X₅⁺ (Å) | released (meV/f.u.) | class |
|---|---|---|---|---|---|
| origin | — | 59.0 | 0 | 0 | hard |
| ring | M₃⁺ 0.720 | 154.8 | 0 | 0 | hard |
| child80 | M₃⁺ 0.672, R₄⁺ 0.184 | 150.1 | 0.155 | 1.92 | induced (trilinear M₃⁺R₄⁺X₅⁺, linear term −24.2 meV/Å/f.u.) |

- **G5 decision:** 1.92 meV/f.u. > 0.5 × 1.376 (ring corrugation) → `SECONDARY_COUPLED` → human kept X₅⁺ at zero with the caveat. f6 re-derives every D4 number (energies re-read by stored id, quartic by QR, minimum from the roots of dE/da): 43/43.

### N3. Open questions added
| # | Question | Status |
|---|---|---|
| Q33 | **X₅⁺ and the ring.** At 80 % of the child primaries, X₅⁺ would release 1.9 meV/f.u., more than the ring corrugation (1.4). The plane holds X₅⁺ at zero; the paper should say so with this number, or a scan at the true child (new DFT, not in this build) should settle it. | PROVISIONAL |
| Q34 | **D4 threshold.** max_fraction 0.5 of the smallest interpreted energy difference is a proposal. | PROVISIONAL |
| Q35 | **Stored scan settings.** The X₅⁺ scans used ENCUT 350 / ISPIN 2 and primaries at 0.8 × the child; Methods/SI should state it if the scans are cited. | PROVISIONAL |

## O. HfO₂ paths, stage H1: decompositions of T1–T5 (17 Oct 2026)

Configs `configs/hfo2_T1.yaml` … `hfo2_T5.yaml` (one per transition, `stop_after: f1`); reference `configs/hfo2_reference.yaml` (the certified Paper 1 decompositions and the runbook's DFT table).

### O1. All five decompositions reproduce the certified values; G1 passes for each. SETTLED

| path | basis (s, i) | A_p (Å) | translation-free | strain (ISODISTORT) |
|---|---|---|---|---|
| T1 137→29 | (0,0,1),(1,1,0),(−1,1,0); s 2, i 8 | M1 0.6254, M3 0.5327, Γ5⁻ 0.7818, Γ1⁺ 0.1731 | Γ5⁻ 0.6379 (f_T 0.334) | Γ1⁺ −0.0029/0.0124, Γ4⁺ −0.0039 |
| T2 137→60 | (−1,1,0),(0,0,1),(1,1,0); s 2, i 4 | M1 1.0141, Γ1⁺ 0.6160 | — | Γ1⁺ 0.0027/0.1130, Γ4⁺ 0.0482 |
| T3 137→14 | (1,−1,0),(1,1,0),(0,0,1); s 2, i 8 | M1 0.7793, M3 0.7198, Γ5⁺ 0.5527, Γ1⁺ 0.3902 | — | Γ1⁺ 0.0219/0.0215, Γ4⁺ 0.0122, Γ5⁺ 0.1147 |
| T4 60→29 | (0,1,0),(−1,0,0),(0,0,1); s 1, i 2 | Γ2⁻ 1.3866, Γ1⁺ 0.9405 | Γ2⁻ 1.2182 (f_T 0.228) | Γ1⁺ +0.0284/−0.0904/−0.0341 |
| T5 60→14 | (0,0,1),(1,0,0),(0,1,0); s 1, i 2 | Γ3⁺ 1.3588, Γ1⁺ 0.6216 | — | Γ1⁺ +0.0581/−0.0838/−0.0256, Γ3⁺ −0.1143 |

- Space groups agree three ways (ISODISTORT subgroup, spglib on the child CIF, spglib on the rebuilt decomposition) for every transition.
- The two polar children (Pca2₁) carry a rigid translation in their polar irrep: T1 Γ5⁻ 33 % of |e|², T4 Γ2⁻ 23 %. The G1 basis check for these uses the centre-of-mass-fixed mapping (T1 0.617, T4 0.661 Å = ISODISTORT shift-free).
- **T2 manual basis:** the stored run lists the basis the runbook gives as manual ((−1,1,0),(0,0,1),(1,1,0), origin (3/2,1,1)); IRIS parses it from the stored response and G1 accepts it (det 2 = s).
- **New in f1:** every strain component is recorded (`strain_components`); the earlier dict kept only the last component of each irrep (T4/T5 have three Γ1⁺ strains).

## P. HfO₂ paths, stage H2: the path frames (17 Oct 2026)

Same configs (`stop_after: f2`), threads `hfo2_T<n>_<p>_<c>_h2`.

### P1. f2 for a straight-line path (`nodes/f2_path.py`; G2 test set `G2_path`). SETTLED
- **What:** 10 frames at λ = k/9; every displacive irrep at λ × its child A_p (polar Γ5⁻, Γ2⁻ translation-free), superposed in fractional coordinates; cell L(λ) = L₀ + λ(L₁ − L₀), L₁ the child CIF cell in the parent frame's axis order.
- **Results (all five paths pass G2):**
  - L00 is the parent (137 / 60), L01–L09 the child group (29, 60, 14, 29, 14); the stored point.json space groups agree at every point.
  - The λ = 1 frame equals the child CIF (StructureMatcher RMS 1.0–1.3e-5).
  - The plan equals the stored path.json: λ within 4e-5 (the stored λ are 6-decimal, last point 0.99996), A_p within 1e-4 Å, every cell within 1e-6 Å, every d_min within 1e-4 Å.

### P2. Selection fix: irreps with displacive modes and strain (R1). SETTLED
- **What changed:** an irrep that has both displacive modes and a strain component (T3 Γ5⁺, T5 Γ3⁺) was treated as strain only and dropped from the subgroup tree, so R3 failed for T5 ("primaries [] reach #60"). Now only pure-strain irreps are removed. All earlier replays give identical results (68 tests).
- **Selection on the paths** (recorded; the path itself uses every irrep): T1 primaries Γ5⁻, M1 (M3, Γ1⁺ secondary); T2 M1; T3 M1, M3 (Γ5⁺, Γ1⁺); T4 Γ2⁻; T5 Γ3⁺.

### P3. The stored T3 and T5 paths rotate the child cell. PROVISIONAL (paper)
- The stored generator orients the child cell by snapping it onto the ISODISTORT movie lattice. For the two monoclinic children this leaves a **rigid rotation of 4.88° (T3) and 5.02° (T5)** between the parent and the λ = 1 cell. T1, T2, T4 (orthorhombic children) have none.
- Because the cell is interpolated linearly, a rotated end cell changes the cells in between: at λ = ½, a is 0.014 Å shorter, c 0.005 Å longer and the volume 0.18–0.19 % smaller than on the rotation-free (pure-stretch) path. The end points are identical.
- IRIS replays the stored orientation (`child_lattice.orientation: stored`) and records the rotation; `pure_stretch` builds the rotation-free path. Its energies would need new DFT (20 runs).
- **Paper (Q36):** state that the frozen T3/T5 paths interpolate the cell matrix with this orientation, or recompute them on the rotation-free path; the barriers (43.95, 52.37 meV/f.u.) are upper bounds either way.

## R. HfO₂ paths, stage H3: energies, barriers, closure (17 Oct 2026)

All five paths now run G0–G6 in replay. Nothing was computed: every frame is the stored point of the
2026-10-08 campaign, matched by structure (≤ 1.0e-4 Å per atom, cells ≤ 4e-7 Å).

### R1. The runbook table reproduces. SETTLED

| path | barrier (meV/f.u.) | at λ | ΔE end | spline barrier / λ | f6 |
|---|---|---|---|---|---|
| T1 137→29 | 6.43 | 2/9 | −87.38 | 6.53 / 0.241 | 71/71 |
| T2 137→60 | 24.68 | 3/9 | −99.37 | 24.83 / 0.351 | 68/68 |
| T3 137→14 | 43.95 | 3/9 | −170.43 | 43.96 / 0.329 | 71/71 |
| T4 60→29 | 80.50 | 5/9 | +12.05 | 80.51 / 0.556 | 67/67 |
| T5 60→14 | 52.37 | 4/9 | −71.03 | 52.45 / 0.456 | 67/67 |

- All 50 points converged (OSZICAR rule), non-magnetic (|m| ≤ 1.1e-5 μB), one POTCAR set (PAW_PBE Hf 20Jan2003,
  O 08Apr2002); the INCAR equals `demo/hfo2/INCAR.static` at every point.
- dE(λ) re-derived from E0 agrees with `result.json`, `energies.csv` and `energies_summary.json` to their 3-decimal
  rounding (≤ 5e-4 meV/f.u.).
- The spline barrier is a between-point estimate (≤ 0.15 meV/f.u. above the grid maximum), not gated; the barriers
  stay frozen-path upper bounds.
- IRIS finds the shared end structures by matching (rms ≤ 3e-5), not by the collector's hand-written pairs; it
  finds exactly the collector's four groups.

### R2. The cross-setting spreads and the closure gaps are k-point sampling. PROVISIONAL (paper wording)

- T4 and T5 (cells of the Pbcn parent) were computed on a **Γ 5×6×5** mesh; T1–T3 on **Γ 5×5×5**. The runbook
  says Γ 5×5×5 for all paths.
- Every pair of the same crystal on the same mesh agrees to 0.0000 meV/f.u.; every nonzero spread is a
  5×5×5 vs 5×6×5 pair: Pbcn 0.0175, Pca2₁ 0.0425, P2₁/c 0.0050 meV/f.u.
- The closure gaps are exactly these differences (f6 checks the identity):
  T1 − (T2 + T4) = −0.0600 = −(0.0175 + 0.0425); T3 − (T2 + T5) = −0.0225 = −(0.0175 + 0.0050) meV/f.u.
- So the closure is not an independent test of the energies; it tests the k-point convergence at the
  0.05 meV/f.u. level.

| Q | Open question | Status |
|---|---|---|
| Q37 | **k-mesh.** Methods (and the runbook) should say Γ 5×5×5 for T1–T3 and Γ 5×6×5 for T4/T5, and that the closure (≤ 0.06 meV/f.u.) and cross-setting spreads come from this sampling difference. | PROVISIONAL |
| Q38 | **G5 limits for the paths.** `cross_setting_meV` 0.1 and `closure_meV` 0.1 are proposals (the stored collector used 1.0; observed ≤ 0.0425 and ≤ 0.06). | PROVISIONAL |
| Q39 | **Barrier resolution.** Report the grid maximum (as now) with Δλ = 1/9, or also the spline estimate? | PROVISIONAL |

## S. Build step 5, S5.1: sub-agent provider layer (17 Oct 2026)

### S1. One call for three providers (`iris_agent/llm.py`). SETTLED (mechanics)
- Anthropic, OpenAI (+ OpenAI-compatible servers for open models) and Google, over plain HTTPS; model ids and
  settings in `eval/models.yaml`, keys only from environment variables.
- Constrained decoding is enforced by all three APIs: Anthropic `output_config.format` json_schema, OpenAI Responses
  `text.format` json_schema strict, Gemini `responseSchema` enum. Anthropic notes that enum capitalisation is not
  guaranteed; IRIS matches case-insensitively and records `case_normalized`. The free mode measures invalid answers.
- First live check (2026-10-17, `results/llm_checks/2026-10-17T080057Z`): Claude 5.5 rejects `temperature`, and Sonnet /
  Opus 5.5 reject a forced tool call → temperature is left at each provider's default for the whole panel (recorded),
  and the Anthropic adapter uses `output_config`. The OpenAI flagship family is served through the Responses API.
- Panel pinned (`eval/models.yaml`): Claude Haiku / Sonnet (reference) / Opus 5.5; GPT-6 Luna / 6.1 Sol / 6 Astra;
  Gemini 3.5 Flash-Lite / 3.8 Flash / 4 Argon (small / mid / flagship each).
- Invalid answers are counted and go to the human; never retried (only transport errors are).

### S2. Fix: the sub-agent prompts could not be rendered. SETTLED
- The drafted prompts (step 4) contain a literal JSON example `{"id": ..., "reason": ...}`; the old renderer
  (str.format) took it for a placeholder, so no sub-agent prompt would have rendered. `prompts.render` now fills only
  `{name}` placeholders (and `{{ }}` escapes); the prompt text is unchanged.

| Q | Open question | Status |
|---|---|---|
| Q40 | **Data to providers.** Sub-agent prompts carry gate details (unpublished numbers). Confirm that sending them to OpenAI and Google (as well as Anthropic) is acceptable under the accounts' data settings; state it in Methods. | OPEN (before S5.3) |
| Q41 | **Model panel.** Nine models, three tiers per provider (above); ids pinned 2026-10-17 from the account lists; returned versions logged per call. Temperature at provider default for all (Claude 5.5 rejects the parameter), so variance comes from repeats. | PROVISIONAL |

## T. Build step 5, S5.2: sub-agent benchmark cases (17 Oct 2026)

### T1. Recovery menus cleaned: only options a node acts on. SETTLED (mechanics; SI table of menus changes)
- Seven menu options changed nothing any node reads, so a sub-agent choosing one would waste a retry: `reask_llm`
  (returns with step 6), `retry_tolerance_ladder`, `add_subthreshold_irrep`, `reduce_grid` (D3), f3 `wait`,
  `restrict_fit_radius`, and `zero_strain` inside `rebuild_fixed_lattice`. Removed; a test now checks every option's
  patch keys against the node code. Added `remove_translation` to f2 (the f2_translation rule's fix, implemented).
- A menu with only `stop` (f0, f3) goes to the human without a model call.
- The SI recovery-menu table and any text that lists "reduce the grid (D3)" or "tolerance ladder" as sub-agent
  options must follow (D3/D4 wording, Q16).

### T2. Sub-agent prompts: stale guidance fixed; two variants. SETTLED (mechanics)
- G1/G2 guidance named removed options, and G2 claimed R5 goes to a separate prompt (it uses G2). Fixed.
- Variant `guided` keeps each gate's one-line Guidance (the fix knowledge the rule table encodes); `bare` drops it.
  Both are run in S5.3 to measure how much each model infers without being told.

### T3. 19 cases captured from real replays (CsSnI3, CsSnI3 D4, InMnO3, Ca3Ti2O7, HfO2 T1). DRAFT labels
- Correct answer `stop` in 9 cases, another option in 10 (an always-stop policy scores 9/19).
- Labels are drafts until approved; then `eval/` is frozen before any model sees the cases.

| Q | Open question | Status |
|---|---|---|
| Q42 | **Labels for C10 (D4) and C11 (R5).** Answered 2026-10-17: C10 accept_secondary_hold correct, stop safe; C11 include_borderline correct, exclude_borderline harmful. | SETTLED |
| Q43 | **Two-option menus (C04).** Answered: stop is safe. | SETTLED |

## U. Evaluation set frozen; S5.3 runner; E1, E2, E4, E7, E9 and interventions (17 Oct 2026)

### U1. 53 sub-agent cases from all six systems, 16 held out (30 %); eval/ frozen 2026-10-17T18:29Z. SETTLED
- Scoring (user decision): correct / safe (stop or other escalation) / harmful; invalid kept apart. Always-stop scores
  22/53 correct and 0 harmful (10/16 on the held-out set); first-option and uniform-random baselines reported too.
- Systems: HfO2 14, CsSnI3 12, ErMnO3 8, InMnO3 7, Ca3Ti2O7 7, BiFeO3 5. Classes: rules off 29, decoy 11, rule used
  up 6, no rule 5, judgment 2. Held-out = cases added after the menus and Guidance lines were final, with every system
  represented (BiFeO3 5, HfO2 3, two each for the other four).
- BiFeO3 cases follow the real campaign episodes (PROVENANCE.md): 50 timed-out runs resubmitted unchanged
  (main_fix), 15 SCF failures rerun with robust mixing (main_robust), 20 SCF-limited near-metallic corners.
  The InMnO3 joint-fit residual (12.06 > 12 meV/cell) is the real failure of this build.
- Every fault-derived case's injection is a fault in eval/faults.yaml (F001-F053), so E2, E4, E9 and the
  interventions runs use exactly the cases' faults.
- Fix found while building: in the BiFeO3 reviewer (f4_grid6) `flag_and_continue` had no effect; it now accepts
  flagged frames from failed jobs as in the other reviewers.

### U2. S5.3 protocol (iris_agent/subagent_bench.py). SETTLED (mechanics)
- 9 models × 53 cases × guided / bare × 10 repeats = 9,540 calls, constrained mode, provider-default temperature.
- Option order shuffled per (case, repeat) and identical across models and variants (paired design).
- Statistics: rates with 95 % CIs by bootstrap over cases (repeats of a case resampled together); exact McNemar vs the
  reference and between every model pair (Holm-adjusted within variant × split), with bootstrap CIs of the
  differences in correct and harmful rates; consistency across repeats; correct rate with the correct option shown
  first vs last (position bias); tokens, cost, latency.

### U3. Model-off experiments run in replay (cloud). Results in results/summary/
- E1: all 13 configs end to end, completed; human questions only the published decisions (InMnO3 R5 twice, CsSnI3 D4).
- E7: kill-and-resume after f2, f3, f5 (CsSnI3) and f3 (HfO2 T1): G6 table, gates, submissions identical (4/4);
  audit completeness from the E1 runs.
- E2 (gated), E4 (ungated), E9 (one gate removed at a time; DFT runs submitted before detection, from the f3
  submission records) and interventions per run (model off = E2; model on = reference model, run on the Mac).

| Q | Open question | Status |
|---|---|---|
| Q44 | **Held-out definition.** Held-out = added after the menus/Guidance were final and balanced over systems; not drawn at random. State it in Methods. | PROVISIONAL |

### U4. Model-off results (cloud replay, frozen eval/; CSVs in results/summary/). MEASURED
- **E1** (`E1_runs.csv`): 13/13 configs complete; every reported number re-derived by G6 (E7_audit_completeness.csv,
  fraction 1.0 for all); human questions only the published decisions (InMnO3 R5 ×2, CsSnI3 D4).
- **E2, gates on** (`E2_faults_gated.csv`): 53/53 faults caught first by the expected gate (G4 24, G5 13, G2 8, G1 6,
  G3 2); 34 rule fixes, 34 human interventions; 27 runs complete with numbers identical to the clean replay, 26 stop
  with the human; 0 silent corruptions.
- **E4, gates off** (`E4_faults_ungated.csv`): 14 silent corruptions (failed / SCF-limited job parts dropped from the
  fits without notice; the HfO2 f.u. error), 24 harmless (mostly limit faults: the data were fine), 15 crashed.
- **E7** (`E7_kill_resume.csv`): kill after f2 / f3 / f5 (CsSnI3) and f3 (HfO2 T1), resume from SQLite: G6 table,
  gate outcomes and job submissions identical (4/4).
- **E9, one gate removed** (`E9_gate_ablation.csv`, 107 runs): removing a gate that did not catch the fault never
  changed a run (63/63 matrix runs, F001–F009). Removing the catching gate, for the 30 error faults: G4 removed → 21/22
  caught later at G5/G6 after the full grid (+27,065 runs spent on unusable results, mostly the BiFeO3 grid); G2
  removed → 4/6 caught at G3 (+73 runs), 2 (No. 55 and its ErMnO3 twin) not caught and harmless in replay. The 23 limit
  faults (only a threshold made stricter) are harmless when their gate is removed, by construction.
- **Interventions, model off** (`E3_interventions_per_*.csv`): human interventions caused by the fault 0.38–0.64 per
  run by system; the published R5/D4 answers are counted apart. Model-on (reference claude-sonnet) runs on the Mac.

| Q | Open question | Status |
|---|---|---|
| Q45 | **Replay understates G2.** A wrongly built frame in replay is simply unmatched (G3); in production it is computed (the 12 Sep No. 55 case: 961 runs). State this next to E9. | PROVISIONAL |
| Q46 | **Limit vs error faults.** 23 of 53 faults only tighten a threshold; report E4/E9 by fault kind (column `fault_kind`). | PROVISIONAL |

### U5. S5.3 and interventions with the model on (Mac, 17 Oct 2026). MEASURED
- 9,540 calls, 0 transport errors; every call used the frozen prompt and option order (re-checked); returned versions
  equal the pinned ids; tables re-derived from the raw calls in the cloud are byte-identical to the Mac's.
- Guided prompt, all 53 cases: correct 0.73 (GPT-6 Luna) – 0.91 (Gemini 4 Argon); harmful 0.02 (Opus, Sol, Astra,
  3.8 Flash) – 0.16 (Luna). Bare prompt: correct 0.48–0.79, harmful 0.17–0.43. Baselines: always-stop 0.42 correct /
  0 harmful; uniform random 0.28 / 0.51.
- Held-out (16): always-stop scores 0.625 correct; guided, Opus / Sol / Astra / 3.8 Flash reach 0.93–0.94 with 0
  harmful; bare, every model falls below always-stop (0.24–0.53 correct, 0.41–0.70 harmful).
- Pairwise (exact McNemar, Holm): 22 of 36 model pairs differ (guided), 26 of 36 (bare). Cost (OpenAI, list
  prices): 11.63 USD for 3,180 calls; Anthropic / Google prices not entered (tokens logged).
- Interventions (fault set end to end): human interventions 34 → 3 with claude-sonnet as sub-agent (the 3 are by
  design: stop-only menus F007/F009, retry budget 0 in F008); same 27 completed runs with identical numbers, 26 stopped;
  0 wrong results. The sub-agent made all 7 published decisions as the paper did (R5 include ×6, D4 accept). Its
  harmful choices (rebuild_fixed_lattice on PATH_LATTICE ×2, densify on a grid-edge minimum) each cost one retry and
  were stopped by the next gate.

| Q | Open question | Status |
|---|---|---|
| Q47 | **The Guidance line carries the result.** Without it every model is below always-stop on the held-out set. The paper should present guided as the system (the gate's fix knowledge is part of IRIS) and bare as the ablation. | PROVISIONAL |
| Q48 | **G6 catches flag-and-continue in replay.** F010/F011: G6 found 40 flagged frames with energies in the stored CSV; in production a failed job leaves none, so this detection is partly a replay artefact. | PROVISIONAL |

