# Results for the manuscript — 2026-10-19

All runs are **replay only**: no DFT, VASP, MACE or Slurm job was run; every energy is a stored campaign energy linked
by structure match. Files are copies; nothing in IRIS_AGENT or the repository was moved, deleted or changed by
packaging. Hashes below are sha256.

Contents
```
E/  E_requests.csv  E_calls.csv  E_summary.csv  E_endtoend.csv  intake_FROZEN.v1.sha256  intake_BASELINE.sha256
A/  A_cases.csv  A_runs.csv  policies_hashes.txt
C/  C_options.csv  C2_options.csv  G6_catches.csv  E9_gate_ablation_tagged.csv  adjustments.yaml (v3)  FROZEN.v1.sha256
provenance/cssni3_incar.md
README.md
```

---------------------------------------------------------------------------------------------------------------------
## Experiment A — non-LLM recovery policies

**What was run.** Two deterministic policies written and frozen before any scoring (`policies/FROZEN.sha256`, frozen
2026-10-19T02:07:17Z): `tree.py` (option chosen from gate, code, detail, menu and the Guidance lines of the frozen
prompts only; unknown → stop; sha256 `1e0883dc8c51f6dfd5577a08cb22fb25393f99d9ff751e1d3c225442f77e31c2`) and
`retrieval.py` (leave-one-out nearest frozen case: same gate + code, then TF-IDF cosine on the detail text; its
reference action if on the menu, else stop; sha256 `70a0096c0d12428f369b90e23be655704867d65c0856e01d52f7a07ab7ebe849`),
plus a seed-only-memory variant and a rules-only policy. (1) Scored on the 53 frozen sub-agent cases with the S5.3 scorer,
one run each (`A_cases.csv`). (2) Registered as sub-agent providers and run through the 53 faulted runs of E3
(`A_runs.csv`), next to rules + human (E2) and claude-sonnet (E3_on).

**Counts — cases (correct / safe / harmful, n = 53; held-out n = 16).** tree 0.943 / 0.038 / 0.019 (held-out 1.000 correct);
rules_only 0.962 / 0.038 / 0.000 (held-out 1.000); retrieval 0.811 / 0.151 / 0.038 (held-out 0.938); retrieval_seed
0.830 / 0.132 / 0.038 (held-out 0.938). No invalid answers.

**Counts — faulted runs (53 each; scored).** completed / completed without hand-off / hand-offs / extra runs:
rules + human 27 / 22 / 34 / 770; claude-sonnet 27 / 26 / 27 / 770; tree 23 / 22 / 31 / 690; retrieval 27 / 26 / 22 / 940.
Every completed run has numbers identical to the clean replay.

**Caveats.**
- *scripted_failures_ran_out*: a fault scripts its job failures; once they are used up every later job succeeds. Five
  retrieval runs (F010, F011, F027, F044, F045, all "fails again" faults) completed only because the scripted failures
  ran out after the policy resubmitted. Per the user's rule they are scored as **not completed for every policy**
  (`final_scored`; raw `final` and the flag column `completed_after_scripted_failures_ran_out` kept). Unscored,
  retrieval would show 32 completed / 31 without hand-off.
- tree answers `stop` at the two published decision points (InMnO₃ R5, CsSnI₃ D4), so F029, F036, F038, F040 stop where
  E2 completes them with the published decisions.
- The case labels were drafted by the author; the S5.3 aggregates had been seen before the policies were written
  (the policies use only prompts / frozen cases, not model answers). retrieval ignores the run history (identical
  details for first vs used-up failures).

**Columns — A_cases.csv.** policy; case (C01–C53); split (seed / held-out); class; system; gate; code; choice (option id
returned); label (correct / safe / harmful / invalid by the frozen labels); correct_options; reason (policy's stated
rule). Rows `ALL (<split>)` give the rates per policy and split.

**Columns — A_runs.csv.** setting; tag (test_runs prefix); fault (F001–F053); system; split; class; fault_kind (limit =
only a threshold tightened, error = real wrong input/job); final (raw end state); completed_without_handoff (completed,
no human question, no sub-agent stop; ran-out completions set false); handoffs = human_questions + subagent_stops;
human_questions; published_decisions (human answers at R5 / D4); subagent_stops; subagent_fixes; rule_fixes; attempts
(recover invocations); runs_submitted (DFT runs the campaign would submit, from the f3 submission records);
baseline_runs (clean E1 replay); runs_vs_clean; extra_runs (positive part); numbers_identical (vs E1, completed runs);
completed_after_scripted_failures_ran_out; subagent_choices (gate code:option, in order); final_scored. Rows
`ALL (<split>)` aggregate per setting.

---------------------------------------------------------------------------------------------------------------------
## Experiment C — consequence of every menu option

**What was run.** For each of the 53 frozen cases the checkpoint where the gate failed was loaded (E2 thread for fault
cases; E1_cssni3_d4 for C10, E1_inmno3 for C11) and one new thread was forked per menu option (208 branches), the
option injected through `Command(resume=…)` at a one-shot human interrupt at the fork point. Run to END with all gates
on, rules on, no sub-agent, the same retry budget; remaining scripted job events, then "all finish"; later human
questions answered with the published decision (R5 include / D4 accept) or `stop` (then human_needed). Numbers compared
with the fault-free E1 replay using the frozen per-quantity tolerances (`eval/consequences.yaml`, 716 quantities, f6
precision). In the forks of rules-off cases no rule can fire before the injected option (checked in the audit of all
branches: the first fix after the fork is the injected human fix, rule_id null); after the fork rules are on.
C2: the 124 branches whose option is neither stop nor labelled correct were rerun with the downstream gates off after
the fork (`C2_options.csv`).

**Classes.** Frozen v1 (`eval/consequences.yaml`): stopped, not-evaluable, rejected, scope-change, accepted-wrong,
accepted-wasted, accepted-correct. Adjustments outside eval/ (`adjustments.yaml`, v3, sha256
`709e418e05e6f4a8d3e24eb75d75c654b3b8a5cc0a8147cf8558fbd28c2908b8`): **accepted_equivalent_settings** (option changes only
AMIX/BMIX/NELM and the replay branch completes identically) and **gate_refused_option** (wrong option, refused by the
first gate after the fork, then repaired by a rule or by the published decision). Both v1 and adjusted columns are kept.
The 57 case / label / fault / model files in eval/ are byte-identical to the 17 Oct freeze (`FROZEN.v1.sha256`,
sha256 `cb1544e8…2c6b`); the refreeze only added consequences.yaml.

**Counts (208 branches).** Adjusted: rejected 74, stopped 53, accepted-correct 35, gate_refused_option 26,
accepted_equivalent_settings 20. v1: accepted-correct 81, rejected 74, stopped 53. Label contradictions: 26 adjusted
(52 under v1) — 13 × `robust_mixing` (harmful) in accepted_equivalent_settings; 9 × unchanged `resubmit` after NELM
(harmful) completing (all flagged scripted_failures_ran_out); 3 × `densify` (correct; C06, C46, C47) rejected by G2
OVER_BUDGET (a real consequence: the densified grid exceeds the budget); 1 × C11 `exclude_borderline` (harmful)
identical (see C11 below). human_needed in 67 branches.
**C2 (124 branches):** 93 completed, 31 stopped; 22 silent wrong results (completed, numbers or scope different):
15 × `flag_and_continue` (fit without the frames of the failed part), C19 × 3 (resubmit / robust_mixing /
flag_and_continue: the wrong formula units per cell survives), C36 × 4 (the injected translation survives; 91 of 225
energies). 16 of the 22 would also be caught by a production-valid gate; 6 (C01, C02, C07, C08, C20, C42, all
flag_and_continue) only by the G6 replay oracle.

**Caveats (tags).**
- *replay_assumed* (80 branches): the branch submits runs after the fork whose energies replay supplies from the stored
  campaign; production would compute them (with the option's settings).
- *accepted_equivalent_settings / mixing_caveat_system*: identical numbers after `robust_mixing` are assumed by replay.
  Mixing does not change the converged energy except in magnetic or near-metallic systems; BiFeO₃ and the manganites
  (InMnO₃, ErMnO₃, plane and joint) are marked.
- *scripted_failures_ran_out* (40 branches): after the fork every job event was the default success (the fault's
  scripted failures were used before the fork); replay supplied the outcome of the resubmitted jobs. An unchanged
  NELM resubmit would most likely fail again in production.
- *gate_refused_option* (26): C03, C05, C12 (G2 TRANSLATION / SINGLE_MODE_SG, repaired by rule f2_translation /
  f2_single_mode_sg_fixed_lattice) and C11 rebuild_fixed_lattice / remove_translation (G2 R5_BORDERLINE again,
  repaired by the published decision include_borderline); `repair` column.
- *replay_oracle*: G6 MISMATCH compares the reported numbers with a re-derivation by a second route (valid in
  production) but in replay that second route re-reads the stored campaign CSV for every matched frame, including frames
  the faulted run lost or flagged; several rows compare directly with campaign files ("linked energies equal to the
  CSV", "energies differing from the collected CSV", "frames matched to stored structures / POSCARs", path "E0 / dE /
  converged (CSV)", "… vs energies_summary.json"). **Every G6 catch is replay_oracle (16 in G6_catches.csv).** In C:
  C01, C02, C07, C08, C20, C40, C42 flag_and_continue. G3 UNMATCHED is replay-only too (production computes the frame).
- *stored_reference*: G5 CLOSURE and CROSS_SETTING read the stored energies of the other HfO₂ paths (read-only network);
  valid in production only if those paths are computed in the same campaign. C15, C16, C52 (the case gate itself,
  `fork_gate_tag`) and their accept_secondary_hold / densify branches.
- G5 THIN_GRID / CV_ERROR / NODE_ERROR use only the run's own data: every frame without an energy at those catches is a
  frame of an injected failed job part; none lacks a stored energy.
- *ablation_artifact* (E9 only): F036 with G2 removed → G3 NODE_ERROR (KeyError 'frames') because removing G2 also removes
  InMnO₃'s own R5 decision point; f2 then builds no frames. Not a replay-only stop and not a catch of the fault.

**E9 (tagged copy).** Of the detecting-gate ablations caught by a later gate: 13 production-valid (F009 at G4; F013,
F014, F023, F027, F029, F037, F038, F039, F041, F043, F044, F045 at G5), 12 replay_oracle (G6: F001, F002, F007, F010,
F011, F020, F021, F040, F042; G3 UNMATCHED: F003, F012, F035), 1 stored_reference (F019, G5 CROSS_SETTING), 1
ablation_artifact (F036). With G4 removed, 21 of 22 error faults are still caught later, but only 12 by gates valid in
production (all at G5); 8 only by the G6 oracle; F019 needs the other paths' stored energies; 1 not caught.

**C11 — why `exclude_borderline` gives identical numbers for InMnO₃.** In both `inmno3` and `inmno3_joint` the selection
(rules/select_modes.py) gives active = {K3, GM2⁻}, R5 gap 0.0759 Å < margin 0.1 Å, borderline = {GM1⁺, GM2⁻, K1}
(GM2⁻ active at 0.099 Å; GM1⁺ and K1 inactive at 0.023 Å), code R5_BORDERLINE. The R5 option only sets
`overrides.f2.r5_decision` = include / exclude / anchor_only. The **only two places that read it** are
`nodes/f2_path_planner.py` line 90 (`if sel["code"] != "OK" and not (sel["code"] == "R5_BORDERLINE" and
over.get("r5_decision")): grid not built`) and `gates.py` G2 `c1_active_set_generates_H` (the same truthiness test).
Both test only that a decision exists; its **value is never read**. The grid is then built from `sel["active"]` and the
per-irrep axes in `policy.grid.axes` (K3, GM2⁻). So: excluding GM2⁻ does **not** change the active set or the grid (225
plane frames; 400 for the joint config), and the published decision "include" does **not** change anything in E1
either — it only lets the run proceed; GM1⁺ and K1 are never added. include / exclude / anchor_only are all the same
code path and give identical numbers (C11 branches). This is an implementation gap (the options are no-ops beyond
unblocking), not a physics result; the frozen labels were not changed. The earlier test "every option's patch is read by
a node" passed because the key is read (as a truthiness check).

**Columns — C_options.csv (C2_options.csv has the same plus silent_wrong, gates_would_fail).**
case; split; class; system; fault; gate; code (failed gate code at the fork); option; label (frozen); source_thread;
fork_checkpoint (UTC); thread (branch thread); final (completed / stopped / …); next_gate (first gate after the fork:
gate code outcome); gates_after_fork (failing gates after the fork); runs_submitted; baseline_runs (E1); extra_runs
(positive part); runs_after_fork; attempts_after_fork (fixes from the fork on); human_needed (a later human question
had no published answer → stop); replay_assumed (runs_after_fork > 0); steps (scripted events used); consequence
(adjusted class); consequence_v1; contradicts_label_v1; scf_only_option; mixing_caveat_system; gate_refused_option;
repair; scripted_failures_ran_out; contradicts_label (adjusted); g6_caught; replay_oracle; g6_oracle_rows;
post_fork_catch_tags (gate code: tag for non-"none" tags); stored_reference; fork_gate_tag (tag of the case's own gate);
numbers (identical / within tolerance / different, completed branches); max_abs_dev; max_dev_over_tol;
n_quantities_differ; n_within_tol_not_identical; first_differing; scope_change (quantity set / active set / number of
energies vs E1). C2 only: silent_wrong (completed and numbers different or scope changed); gates_would_fail (gates
that failed with outcome fail_ignored).

**Columns — G6_catches.csv.** thread; checkpoint; n_rows_failing; oracle_rows_failing (rows comparing with stored
campaign files); rederive_rows_failing (second-route rows); frames_flagged_or_unlinked; replay_oracle.

**Columns — E9_gate_ablation_tagged.csv.** The E9 columns (fault; name; class; system; split; ablated_gate;
gated_detected_by; gated_runs_before_detection; detected_by; runs_before_detection; extra_runs_wasted;
runs_submitted_total; final; verdict; numbers_identical; human_interventions; thread; gated_ / ablated_ /
extra_runs_on_unusable_result; is_detecting_gate; fault_kind) plus detection_tag (none / replay_oracle /
stored_reference / ablation_artifact for the later gate that caught it); g6_caught; g6_oracle_rows; replay_oracle;
production_valid_detection.

---------------------------------------------------------------------------------------------------------------------
## Experiment E — plain-language intake (build step 6), v1

**What was run.** 50 frozen requests (`intake/FROZEN.sha256` v1, sha256
`2d697afcfec01b3a410924de7b05f02243bee9186cae31a2e367ea033a2a910c`, copied here as intake_FROZEN.v1.sha256): 39 paraphrases
(13 E1 configs × expert / terse / non-specialist), 5 underspecified, 3 out-of-scope, 3 new materials. The model returns
a schema-constrained draft intent (system, structures, transition, analysis, strain policy in the paper's names,
profile, budget, outputs; or a question / refusal); code fills the rest from the E1 config as template and records the
source of each field; f0 + G0 (new codes AMBIGUOUS, OUT_OF_SCOPE, NEEDS_NEW_DFT; consistency errors as SCHEMA).
Models claude-sonnet (reference), gpt-sol, gemini-argon, claude-opus, 5 repeats each (1,000 calls, 0 invalid), plus the
keyword baseline once (50). End to end: every distinct config with all critical fields right ran the full workflow in
replay once (14 configs).

**Counts (paraphrases all critical right).** sonnet 186/195, opus 185/195, gemini 181/195, gpt-sol 180/195, baseline
20/39. Terse and non-specialist 65/65 each for every model except gemini terse 61/65. Underspecified correct (ask, or
U01 → bifeo3): 23, 25, 25, 25 of 25; baseline 4/5. Out of scope refused or asked: 15/15 each; baseline 1/3. New
material (needs new DFT, no borrowed profile): 15/15 each; baseline 0/3. Wrong field passed G0: sonnet 9, opus 9,
gemini 10, gpt-sol 15. End to end: 812 calls → 752 completed with numbers identical to the clean replay (13 configs
incl. the accepted alternatives cssni3_d4, inmno3_joint, ermno3_joint), 60 new-material calls "would need new DFT"
(NO_STORED_DATA); no G3 UNMATCHED; no profile mismatch run.

**Caveats.**
- The dominant miss is E10 / E13 (InMnO₃ "LDA+U A-AFM profile"): 37 of 40 model calls chose `inmno3_aafm` (PBEsol+U),
  not `inmno3_aafm_v2`. The frozen v1 prompt described all six InMnO₃ profiles with the same text ("Mn³⁺ d4
  magnetic"); this is a prompt defect, so a v2 rerun with functional / magnetic order / U scheme in each description
  was run as a declared sensitivity check (status below). G0 passes these (valid profile of the right system).
- gpt-sol E16 × 5: joint fit for "plane … plus the GM2⁻ axis" (no hat requested) — a real misreading.
- The keyword baseline was rebuilt from the tables only and hashed before the freeze (`intake_BASELINE.sha256`, sha256
  of baseline.py `f833d408…69b4`); it was then **run once on N01 during a harness test, after hashing and before the
  calls**; nothing was changed after that.
- The freeze was made twice before any answer: the second only removed hard-coded paths (machine-independent config
  hash); requests, prompt, schema and baseline byte-identical (first freeze `fb66f1fa…f08f0d`).
- Strain policies use the paper's names. The E1 configs carry older code labels (code P2 = paper P1 fixed lattice,
  code P5 = paper P3 strain-interpolated); no node reads the label, so no number depends on it. P4 is not implemented
  (G0 OUT_OF_SCOPE); P5 (fixed-lattice bias statement) is accepted but **not implemented: f6 does not state the bias**.
- *BiFeO₃ `_r2`*: the BiFeO₃ end-to-end replay is recorded under thread E2E_c887f1640ec9b090 but ran in
  E2E_c887f1640ec9b090_r2 (the first attempt was interrupted when the job was restarted; the folder is kept).
- New materials build the same minimal config, so they share one config hash; the note gives each row its material.
  The end-to-end step for them is a wrapper outside the frozen files (`intake/e2e.py`).

**Columns — E_requests.csv.** id; kind (paraphrase / underspecified / out_of_scope / new_material); style; text;
attachments; reference_config (E1 config); reference (intent JSON); acceptable (per field: stated → listed values,
unstated → also null; outcome for the other kinds); expected_outcome; defensible_guesses.

**Columns — E_calls.csv.** model; repeat; request; kind; style; valid; error; outcome (intake status: ok / ambiguous /
out_of_scope / needs_new_dft); g0_ok; g0_code; config_hash (machine-independent); template (E1 config selected);
model_question; clarify_field; g0_question (the listed question G0 asks); out_of_scope_reason; for each field
(structures, transition, analysis, strain_policy, system_profile, budget, outputs) the resolved value and
source_<field> (request / model / default) and match_<field>; same_config_as_reference; accepted_config;
critical_all_right; wrong_critical_fields; wrong_caught_by_g0; wrong_passed_g0; clarification (none / unnecessary
question / asked / guessed / refused / accepted / valid, needs new DFT); defensible_different; correct_outcome;
new materials: match_formula, match_parent_sg, match_child_sg, borrowed_profile.

**Columns — E_summary.csv.** per model: calls; invalid; paraphrase_all_critical_right; match_<critical field> and
match_outputs; wrong_caught_by_g0; wrong_passed_g0; unnecessary_questions; underspecified_asked / _guessed / _correct;
out_of_scope_refused_or_asked; new_material_correct; new_material_borrowed_profile; blind_correct (no blind requests
yet); all_critical_right_<style>.

**Columns — E_endtoend.csv.** request; model; repeat; config_hash; template; final_status (completed / would need new
DFT); numbers_identical (vs the clean E1 replay, rel 1e-6); stop_code (NO_STORED_DATA / UNMATCHED / PROFILE / gate code);
thread; note.

---------------------------------------------------------------------------------------------------------------------
## Status of C2 and E v2

- **C2: finished** (124 branches) — included here as `C/C2_options.csv`.
- **E v2: calls finished, but not complete.** v2 (frozen `39216b8655297ddd8f96de0efb41af4bea07c3329b69b3c0eb8a1dfad562ed43`,
  only the profile descriptions changed) ran 1,050 calls; **58 gemini-argon calls failed with HTTP 402 (prepaid credits
  depleted)**, so gemini's v2 numbers are not usable yet. First results for the other models: E10/E13 now get no wrong
  profile (G0-passed wrong fields: opus 0, sonnet 3, gpt-sol 5); instead the models ask which of the two LDA+U A-AFM
  variants to use (`inmno3_aafm_v2` Dudarev vs `inmno3_aafm_v2_lt1` Liechtenstein), which the scorer counts as an
  unnecessary question; gemini picks `inmno3_aafm_v2`. v2 end to end: every config hash equals a v1 one (results reused).
  `results_for_manuscript_part2.zip` will follow after the 58 gemini calls are rerun (needs Google credits).
- Author-written blind requests: none received yet (`intake/requests_blind.yaml`, frozen separately when added).
