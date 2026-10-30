"""Transfer across systems, LLM half: the guided sub-agent prompt with the Guidance sentences seeded by the case's own
system removed (same held-out sets as eval_extra/loso.py). For a BiFeO3 case the model is not told "Walltime: resubmit
unchanged. SCF step limit: resubmit with robust mixing."; for an HfO2 case not "If no basis was found, widening the
atom-matching search is the usual fix."; for a CsSnI3 case not the single-mode rebuild sentence. Every other sentence,
the user prompt, the menu and the option order (repeat r) are exactly those of S5.3. Cases of Ca3Ti2O7, ErMnO3 and
InMnO3 have no sentence seeded only by their own system, so their prompts are unchanged (they are re-run anyway so
that the whole table comes from one run).

  python -m eval_extra.loso_llm --models eval/models.yaml --repeats 10          # all 53 cases, 9 models
  python -m eval_extra.loso_llm --models eval/models.yaml --repeats 10 --affected-only   # the 31 cases whose prompt changes
  python -m eval_extra.loso_llm --summarize                                      # -> results/LOSO/loso_llm_summary.csv

API keys are read from the environment by iris_agent.llm, as in S5.3.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from iris_agent import freeze_eval, subagent_bench as B  # noqa: E402
from iris_agent.llm import load_models  # noqa: E402
from eval_extra.loso import GROUP, RULE_CODE, dropped_for  # noqa: E402

SENTENCE = {  # (gate, code) -> the Guidance sentence that transcribes the rule, verbatim from prompts/subagent_G*.md
    ("G1", "NO_BASIS"): "If no basis was found, widening the atom-matching search is the usual fix. ",
    ("G2", "SINGLE_MODE_SG"): "A strict single-mode space-group mismatch is usually the frame being built on the strained movie cell: rebuild on the fixed parent lattice. ",
    ("G2", "TRANSLATION"): "A rigid translation left in a polar vector is removed by subtracting the mean displacement. ",
    ("G4", "WALLTIME"): "Walltime: resubmit unchanged. ",
    ("G4", "NELM"): "SCF step limit: resubmit with robust mixing. ",
    ("G5", "THIN_GRID"): "A coverage failure means the grid is too thin where the fit needs it: go back to f2 and densify. ",
}
TAG = "A_loso_llm"
OUT = ROOT / "results" / "LOSO"


def loso_cases() -> tuple[list[dict], list[str]]:
    cases, affected = [], []
    for c in B.load_bench_cases():
        group = GROUP[c["system"]]
        held = {RULE_CODE[r] for r in dropped_for(group)}
        sysp = c["system_guided"]
        removed = []
        for key in held:
            sent = SENTENCE[key]
            if sent in sysp:
                sysp = sysp.replace(sent, "", 1)
                removed.append(key[1])
        # the sentence of a held-out code sits only in that gate's prompt; a G4 case of BiFeO3 loses both G4 sentences
        c2 = {**c, "system_guided": sysp, "loso_removed": removed, "loso_group": group}
        if removed:
            affected.append(c["id"])
        cases.append(c2)
    return cases, affected


def summarize(models: dict):
    calls = [json.loads(x) for x in (OUT / TAG / "calls.jsonl").read_text().splitlines()]
    cases, affected = loso_cases()
    by = {c["id"]: c for c in cases}
    rows = []
    for name in models:
        rr = [r for r in calls if r["model_name"] == name and r["variant"] == "guided"]
        for subset, ids in (("all", {c["id"] for c in cases}), ("prompt_changed", set(affected)),
                            ("prompt_unchanged", {c["id"] for c in cases} - set(affected))):
            sub = [r for r in rr if r["case"] in ids]
            if not sub:
                continue
            cnt = Counter(r["label"] for r in sub)
            n = len(sub)
            rows.append({"model": name, "subset": subset, "n_calls": n, "n_cases": len({r["case"] for r in sub}),
                         "correct": cnt["correct"], "safe": cnt["safe"], "harmful": cnt["harmful"],
                         "invalid": cnt["invalid"], "error": cnt["error"],
                         "correct_rate": round(cnt["correct"] / n, 4), "harmful_rate": round(cnt["harmful"] / n, 4)})
        # per held-out group
        for g in sorted(set(GROUP.values())):
            sub = [r for r in rr if by[r["case"]]["loso_group"] == g]
            if sub:
                cnt = Counter(r["label"] for r in sub)
                rows.append({"model": name, "subset": f"held-out {g}", "n_calls": len(sub),
                             "n_cases": len({r["case"] for r in sub}), "correct": cnt["correct"], "safe": cnt["safe"],
                             "harmful": cnt["harmful"], "invalid": cnt["invalid"], "error": cnt["error"],
                             "correct_rate": round(cnt["correct"] / len(sub), 4), "harmful_rate": round(cnt["harmful"] / len(sub), 4)})
    with (OUT / "loso_llm_summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    # per case x model: what the model chose without the sentence
    per = []
    for name in models:
        for cid in affected:
            sub = [r for r in calls if r["model_name"] == name and r["case"] == cid]
            cnt = Counter(r["label"] for r in sub)
            per.append({"model": name, "case": cid, "system": by[cid]["system"], "code": by[cid]["code"],
                        "removed": ";".join(by[cid]["loso_removed"]), "n": len(sub), "correct": cnt["correct"],
                        "safe": cnt["safe"], "harmful": cnt["harmful"],
                        "choices": ";".join(f"{k}:{v}" for k, v in Counter(r.get("answered_id") for r in sub).most_common())})
    with (OUT / "loso_llm_cases.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per[0]))
        w.writeheader()
        w.writerows(per)
    for r in rows:
        if r["subset"] in ("all", "prompt_changed"):
            print(f"{r['model']:18s} {r['subset']:15s} n={r['n_calls']:4d}  correct {r['correct_rate']:.3f}  harmful {r['harmful_rate']:.3f}")
    print(f"written: {OUT / 'loso_llm_summary.csv'}, {OUT / 'loso_llm_cases.csv'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=str(ROOT / "eval" / "models.yaml"))
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--affected-only", action="store_true")
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--retry-errors", action="store_true")
    a = ap.parse_args()
    ok, probs = freeze_eval.verify(ROOT / "eval")
    if ok is not True:
        raise SystemExit(f"eval/ not frozen / changed: {probs}")
    models = load_models(Path(a.models))
    if a.summarize:
        return summarize(models)
    cases, affected = loso_cases()
    print(f"{len(affected)} of {len(cases)} cases have a Guidance sentence removed: {' '.join(affected)}")
    if a.affected_only:
        cases = [c for c in cases if c["id"] in affected]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "loso_prompts.json").write_text(json.dumps(
        {c["id"]: {"group": c["loso_group"], "removed": c["loso_removed"], "system_prompt": c["system_guided"]}
         for c in cases}, indent=1))
    B.run(TAG, models, cases, ["guided"], a.repeats, a.workers, a.retry_errors, out_root=OUT)
    summarize(models)


if __name__ == "__main__":
    main()
