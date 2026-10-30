# SI Table S3 — recovery menus per gate (generated from recovery.yaml)

| gate | node | rules tried first | sub-agent asked | option | what it does | config patch | next node | read by |
|---|---|---|---|---|---|---|---|---|
| G0 | f0 Intake | f0_schema_reask (SCHEMA) | no (stop only) | `stop` | Stop and ask the human for a corrected config |  | END (human) |  |
| G1 | f1 Crystallographer | f1_no_basis_dmax_ladder (NO_BASIS) | yes | `widen_basis_search` | Widen the atom-matching basis search (dmax 2.0 A) | `{"basis_dmax_A": 2.0}` | f1 | nodes/f1_crystallographer.py |
|  |  |  |  | `stop` | Stop and ask the human |  | END (human) |  |
| G2 | f2 Path Planner | f2_translation (TRANSLATION); f2_single_mode_sg_fixed_lattice (SINGLE_MODE_SG) | yes | `include_borderline` | R5: include the borderline irreps as axes | `{"r5_decision": "include"}` | f2 | nodes/f2_path_planner.py |
|  |  |  |  | `exclude_borderline` | R5: exclude the borderline irreps | `{"r5_decision": "exclude"}` | f2 | nodes/f2_path_planner.py |
|  |  |  |  | `anchor_only` | R5: keep the borderline irreps as anchor points only | `{"r5_decision": "anchor_only"}` | f2 | nodes/f2_path_planner.py |
|  |  |  |  | `rebuild_fixed_lattice` | Rebuild single-mode frames on the fixed parent lattice | `{"single_mode_check_on": "fixed_parent_lattice"}` | f2 | nodes/f2_path_planner.py |
|  |  |  |  | `remove_translation` | Subtract the rigid translation (mean displacement) from the polar mode vectors | `{"subtract_mean_displacement": true}` | f2 | nodes/f2_path_planner.py |
|  |  |  |  | `stop` | Stop and ask the human |  | END (human) |  |
| G3 | f3 Runner |  | no (stop only) | `stop` | Stop and ask the human |  | END (human) |  |
| G4 | f4 Reviewer | f4_walltime_resubmit (WALLTIME); f4_nelm_robust_mixing (NELM) | yes | `resubmit` | Resubmit the failed parts unchanged | `{"resubmit_failed": true}` | f3 | nodes/f3_runner.py |
|  |  |  |  | `robust_mixing` | Resubmit the failed parts with robust mixing | `{"resubmit_failed": true, "incar": {"AMIX": 0.2, "BMIX": 0.0001, "NELM": 300}}` | f3 | nodes/f3_runner.py |
|  |  |  |  | `flag_and_continue` | Flag the frames and continue without them | `{"flag_unconverged": true}` | f4 | nodes/f4_grid6.py; nodes/f4_path.py; nodes/f4_reviewer.py |
|  |  |  |  | `stop` | Stop and ask the human |  | END (human) |  |
| G5 | f5 Analyst | f5_thin_grid_densify (THIN_GRID) | yes | `densify` | Go back to f2 and densify the grid | `{"densify": 2}` | f2 | nodes/f2_path_planner.py |
|  |  |  |  | `accept_secondary_hold` | D4: keep the secondary at zero and report the energy it would release as a caveat | `{"d4_accept": true}` | f5 | nodes/f5_analyst.py |
|  |  |  |  | `stop` | Stop and ask the human |  | END (human) |  |
| G6 | f6 Skeptic |  | yes | `rerun_analysis` | Re-run f5 and re-check |  | f5 |  |
|  |  |  |  | `stop` | Stop and ask the human |  | END (human) |  |
