"""Experiment A (3): score the non-LLM policies on the 53 frozen cases with the S5.3 scorer (one run each).

  python -m policies.score_cases          # -> results/A/A_cases.csv (+ results/A/summary/S5_3_*.csv from the S5.3 scorer)

Same protocol as S5.3: frozen eval/ (refused otherwise), case prompt inputs, option order of repeat 0, labels
correct / safe / harmful. Policies: tree, retrieval (leave-one-out, all cases), retrieval_seed (seed-only memory),
rules_only. Output rows: one per (policy, case) plus one aggregate row per (policy, split).
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from iris_agent import freeze_eval, subagent_bench as B  # noqa: E402
from iris_agent.llm import load_models  # noqa: E402

OUT = ROOT / "results" / "A"


def main():
    ok, probs = freeze_eval.verify(ROOT / "eval")
    if ok is not True:
        raise SystemExit(f"eval/ not frozen / changed: {probs}")
    models = load_models(ROOT / "policies" / "models.yaml")
    cases = B.load_bench_cases()
    B.run("A_cases", models, cases, ["guided"], 1, 1, False, out_root=OUT)
    B.summarize("A_cases", models, cases, 1, None, out_root=OUT, summary_dir=OUT / "summary")
    calls = [json.loads(x) for x in (OUT / "A_cases" / "calls.jsonl").read_text().splitlines()]
    by = {c["id"]: c for c in cases}
    rows = []
    for r in sorted(calls, key=lambda r: (list(models).index(r["model_name"]), r["case"])):
        c = by[r["case"]]
        rows.append({"policy": r["model_name"], "case": r["case"], "split": c["split"], "class": c["class"],
                     "system": c["system"], "gate": c["values"]["gate"], "code": c["code"], "choice": r.get("answered_id"),
                     "label": r["label"], "correct_options": ";".join(k for k, v in c["label_of"].items() if v == "correct"),
                     "reason": r.get("reason", "")})
    agg = []
    for pol in models:
        for sp in ("all", "seed", "held-out"):
            rr = [r for r in rows if r["policy"] == pol and (sp == "all" or r["split"] == sp)]
            cnt = Counter(r["label"] for r in rr)
            agg.append({"policy": pol, "case": f"ALL ({sp})", "split": sp, "class": "", "system": "", "gate": "", "code": "",
                        "choice": "", "label": f"n={len(rr)}",
                        "correct_options": f"correct {cnt['correct'] / len(rr):.4f} | safe {cnt['safe'] / len(rr):.4f} | "
                                           f"harmful {cnt['harmful'] / len(rr):.4f} | invalid {cnt['invalid'] / len(rr):.4f}",
                        "reason": ""})
    with open(OUT / "A_cases.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows + agg)
    for a in agg:
        print(f"{a['policy']:15s} {a['split']:9s} {a['label']:6s} {a['correct_options']}")
    print(OUT / "A_cases.csv")


if __name__ == "__main__":
    main()
