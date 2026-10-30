# Results

| Folder | Contents |
|---|---|
| `frozen_2026-10-19/` | the evaluation as frozen on 2026-10-19: sub-agent benchmark (A), option replay (C), intake (E), with provenance hashes |
| `final_2026-10-29/` | the re-run after the MISSING_FRAMES check and the applied R5 answer: option replay `C_options.csv` (208 branches), `C2_options.csv` (124 branches, gates off after the fork), gate ablation `E9_gate_ablation.csv` |
| `LOSO/` | leave-one-system-out: deterministic deciders (`loso_cases.csv`, `loso_summary.csv`) and the nine models with the own-system guidance sentence removed (`loso_llm_*.csv`, `loso_prompts.json`) |
| `E/parser_v2/` | the rule-based intake parser, second version (one declared fix); v1 numbers are in the paper and reproducible with `PARSER_V1=1 python -m intake.run_parser` |
| `summary/` | the per-experiment summary CSVs read by `scripts/figures/fig6_llm.py` (E1–E9, S5.3 model benchmark, `E_summary_v5.csv` with the parser row) |
| `DECOY/` | the decoy-remedy test: three guidance sentences (`remedy_prompts.json`), nine models x five repeats on the 53 cases (`decoy_remedy_summary.csv`, `decoy_remedy_cases.csv`) |
| `COST/` | tokens, latency and cost of every metered model call, per experiment and model (`cost_summary.csv`) |
| `ELIGIBILITY/` | the benchmark with the recovery menus filtered by the eligibility conditions of `recovery.yaml` (`for:`), frozen prompts; see its README |
