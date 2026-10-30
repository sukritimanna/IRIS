# What changed since the first Carbon install (28 Oct) — re-apply the patch to get all of it

Re-apply: `bash 01_patch/apply_patch.sh $IRIS_AGENT --go` (additive; backups *.pre_live). Then
`cd $IRIS_AGENT && python -m pytest -q tests` → 142 passed, 17 skipped.

## Fixes found by the first real runs
- `engines/live_vasp.py`: OUTCAR magnetization line has no value for ISPIN = 1; per-f.u. energies at full precision.
- `gates.py`: G1 accepts the basis-search det of a centred conventional child cell (Amm2 A-centred, R3m hexagonal).
- `engines/stored_isodistort.py`: ISODISTORT site symmforms (`Dx,-Dx,Dz`) applied correctly (hexagonal R3m cell).
- `engines/mp_fetch.py`: candidates symmetrised at MP's 0.1 Å and verified at 1e-3; AlphaIDs decoded (mp-2998).
- `chat.py` / `web.py`: thread name includes the campaign; errors shown on the page; chat column scrolls itself,
  board fixed; gate lines stream during ISODISTORT/VASP; classic mp ids; `--mock`, `--n-points`, `--part-size`.
- Templates: PBE (`GGA: PE`, matches the MP cells), your PBS header and module lines, 1 h walltime (20 min is
  enough: a 5-atom static takes 12 s), no mail lines, POTCAR = writePotcar library, KPOINTS = kpointsUtilities 0.20.

## New: the 2D slice (grid kind `plane2`)
- `nodes/f2_plane2.py`, `f5_plane2.py`, `f6_plane2.py`, gates `G2_plane2` / `G5_plane2`, `configs/live/_template_plane_live.yaml`.
- Two components of one irrep (Γ4−: z from the decomposition, x by the cubic 4-fold) on a (Q1, Q2) grid at the fixed
  cubic cell; 4mm orbit representatives only (17×17 → 45 statics; `--levels 5` → 9×9 → 15; `--levels 11` → 66).
- f5: Landau fit with the 4mm invariants (a, b, c, d, e), minimum, axis/diagonal energies; f6 refits and recounts.
- Page: heat map rebuilt from the representatives by symmetry, [001]/[101] marked, fitted minimum ringed.

## Running the plane (after T1–T3 in the same campaign)
```bash
# mock first (fake VASP, everything else real):
python -m iris_agent.web --campaign <campaign> --llm claude-sonnet --executor --port 8765 --plane --mock
# real:
python -m iris_agent.web --campaign <campaign> --llm claude-sonnet --executor --port 8765 --plane
```
Request: `Map the Γ4- polarization-rotation plane (Pz, Px) of BaTiO3 between cubic Pm-3m (221) and tetragonal P4mm (99)
at the fixed cubic cell, PBE` (the intake answers analysis = plane; `--plane` forces it either way). The ISODISTORT
responses of T1 are NOT reused (different folder); it runs again, ~4 min.

## Operating notes learned today
- Stop a server with Ctrl-C, never Ctrl-Z (a suspended server keeps port 8765: `ss -ltnp | grep 8765` → `kill -9 <pid>`).
- Every new Carbon window: `source ~/.iris_env && source ~/anaconda3/etc/profile.d/conda.sh && conda activate iris && cd $IRIS_AGENT`.
- Do not `module load` the VASP modules in the window that runs the chat (Intel's Python shadows the env).
- The campaign CSV is shared by the paths and the plane; `--network` on the last path compares the cubic point across cells.

## 2026-10-28 (evening) — plane fix + richer page
- f2_plane2 / f6_plane2: the 4-fold rotation is taken about an atom position (ISODISTORT's origin offset); grid records `rotation_centre`.
- web.py: status line (current node, what it is doing, elapsed), node wall times on the board, PBS progress bar + per-part elapsed,
  heat map with diverging scale, colour bar, Landau-fit contours, Å ticks, A_p marker, direction labels and a written reading.
- Re-apply with 01_patch/apply_patch.sh (additive; *.pre_live backups kept).

## 2026-10-29 — plane network check
- f5_plane2.plane_network + G5_plane2 test `network`: the plane's cubic origin must agree per f.u. with lambda = 0 of every
  finished path of the campaign (policy.plane2.network_meV, default 1 meV); fails with NETWORK (catches a different
  functional/cut-off/POTCAR between runs — PL1/PL2 were PBEsol on the PBE campaign). f6_plane2 re-derives the diffs.
- 04_archive/live_summary.py: campaign summary for the manuscript.

## 2026-10-29 — MISSING_FRAMES (the seven replay-only catches of Supplementary Table S46)
- gates.g4_missing_frames_authorized, registered in EVERY G4 and G5 variant: frames dropped by `flag_and_continue`
  (energies.flagged[].accepted) fail with code MISSING_FRAMES unless policy.fit.allow_missing_frames is set (a recorded
  human decision). In production this replaces the replay-only G6 comparison that was the only thing stopping a fit
  on fewer frames (7 of the 22 wrong results in the 124-branch replay; C01, C02, C07, C08, C20, C40, C42). In G5 too so
  that the G4-ablation experiment keeps catching it.
- every f5 model records "dropped_frames" (n_dropped, n_planned, ids, authorised) so an authorised smaller grid is
  never silent; config schema key policy.fit.allow_missing_frames (bool); menu text of flag_and_continue updated.
- tests: test_g4_missing_frames_needs_human_authorisation; test_g3_g4_codes_for_cancel_and_failures updated.
- TO DO on the machine that holds test_runs/E2_* and the stored campaigns: `python -m consequences.fork` (all 208) and
  `--c2`, then rebuild Tables S46/S47/S51 and Fig. 6d. Expected: the 24 flag_and_continue branches stop at
  G4 MISSING_FRAMES; S46 row "Error / wrong" becomes 22 | 0 | 22 | 0.
- 2026-10-29 pm: G5 form `g5_missing_frames` counts every planned frame absent from the fit (not only accepted flags),
  so the check holds when G4 is ablated (E9 showed the first form did not). fork.py: config path for the D4/R5
  cases falls back to configs/. check_env: list-valued path entries. Re-run on the Mac: E1 13/13, E2 53/53
  identical to v12; C: only the 24 flag_and_continue branches moved (7 replay-only -> G4 MISSING_FRAMES);
  C2 unchanged; E9: the 9 G6-only catches -> G5 MISSING_FRAMES, replay-only now 3 (G3, G2 removed).

## 2026-10-29 — R5 operational
- rules/select_modes.select(..., r5_decision): include keeps the borderline active irreps as axes (sub-threshold ones
  stay out); exclude / anchor_only remove them from the axes and hold them at zero (R5_EXCLUDE_BREAKS_H if H is lost);
  anchor_only adds r5_anchors. f2 passes overrides.f2.r5_decision into select_for (the old bypass is gone) and builds
  one anchor frame per removed irrep at the child amplitudes (grid["r5"]). G2 test r5_decision_applied. f6 re-derives
  with the same decision. f5_meier reports r5_anchors (with the fit, or with the NO_FIT reason when the polar axis
  was removed). Tests: test_r5_decision_is_applied_to_the_active_set, test_r5_exclude_that_breaks_H_fails,
  test_g2_r5_decision_applied.

## 2026-10-29 — R5 answer applied (final evaluation)

- `rules/select_modes.py`: `select(..., r5_decision)`. include keeps the borderline active irreps as axes; exclude /
  anchor_only remove them (held at zero; `R5_EXCLUDE_BREAKS_H` if the remaining set no longer generates H);
  anchor_only fills `r5_anchors`.
- `f2_path_planner`: passes `overrides.f2.r5_decision` to `select_for`, adds one anchor frame per removed irrep
  (`grid["r5"]`). `gates.py`: `g2_r5_decision_applied` (`R5_NOT_APPLIED`; moot when the selection has no
  borderline); the old R5 bypass in `g2_c1` is removed. `f6_skeptic`/`f6_path` re-derive with the decision;
  `f5_meier` reports `r5_anchors`; `_layout.r5_anchor_report`.
- Tests: `tests/test_select_modes.py`, `tests/test_gates_recover.py` (+R5 cases).
- Re-run on the Mac: E1 13/13 and E2 53/53 identical; E9 identical to the MISSING_FRAMES run (27 stopped
  later: 23 production, 3 replay-only at G3, 1 crash; 3 not caught). C (208): 33 correct, 20 equivalent
  settings, 24 refused, 76 rejected, 2 not evaluable (InMnO3 anchor_only: frame not in the stored plane),
  53 stopped. C2 (124): 69 correct/equivalent, 20 silent wrong, 35 stopped. Only the InMnO3 R5 branches
  (C11, C36) moved: exclude -> one-axis grid -> G5 NO_FIT; anchor_only -> G3 UNMATCHED in replay.

## 2026-10-29 — transfer across systems and rule-based intake parser (review items)

- `eval_extra/loso.py`: leave-one-system-out scoring of rules / tree / retrieval on the 53 frozen cases, rule
  provenance from the SI rule table; `eval_extra/loso_llm.py`: the guided prompt with the case's own-system Guidance
  sentence removed (7 cases: C03, C05, C09, C20, C21, C22, C31), 9 models x 10 repeats. Results in `results/LOSO/`.
  Rules 51 -> 47/53 (all four lost cases stop, 0 harmful); models 85.2% -> 79.0% correct, 0.2% -> 2.5% harmful (bare 74.4% / 11.4%).
- `intake/parser.py` + `intake/run_parser.py` + `intake/PARSER.sha256`: rule-based parser written from the schema,
  tables and system prompt only; v1 frozen before scoring (25/39 clear), v2 one declared fix (profile id = system id
  is not a profile choice; 29/39). `PARSER_V1=1` reproduces v1. Results in `results/E/parser/`, `results/E/parser_v2/`.
  The runner tolerates the post-freeze `gates.py` (G0 unchanged).
- Fig. 6a now includes the parser bar (v1); `fig6_llm.py` reads `summary/E_summary_v5.csv`.
