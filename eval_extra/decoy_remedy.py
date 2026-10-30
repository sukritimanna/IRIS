"""Prompt-level remedies for the decoy failures of the sub-agent benchmark, and a run to test them.

The benchmark (S5.3) showed three ways the models choose a harmful fix on a decoy (a failure whose correct answer is
stop): (1) on a COVERAGE failure whose minimum lies near the grid edge, 89 of 90 decisions densified, because the G5
guidance sentence says a coverage failure is a thin grid; (2) on PATH_LATTICE (a child cell rotated relative to the
parent) 82 of 180 chose rebuild_fixed_lattice, a lattice-sounding fix that the G2 guidance never mentions; (3) on
small tolerance overshoots (CLOSURE, CROSS_SETTING, RESIDUALS, MIRROR, CV_ERROR) the small models chose
accept_secondary_hold, reading "accept" as "tolerate", although that option exists for SECONDARY_COUPLED only.

The remedy adds one sentence per failure to the guidance line of the G2 and G5 prompts (nothing else changes):
  G2: "A child cell rotated relative to the parent (PATH_LATTICE) is an input-structure problem that no listed fix
       repairs: stop."
  G5: "A minimum near the grid edge (COVERAGE) is not fixed by densifying: stop. accept_secondary_hold applies only
       to SECONDARY_COUPLED; a tolerance exceeded by any margin is a failure, not a near miss: stop."

  python -m eval_extra.decoy_remedy --models eval/models.yaml --repeats 5          # all 53 cases, 9 models (2,385 calls)
  python -m eval_extra.decoy_remedy --summarize

Scored with the frozen labels; reports decoys and non-decoys separately (a remedy that makes the models stop on
rule-fixable failures would show up as lost correct answers on the non-decoys).
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

REMEDY = {
    "G2": " A child cell rotated relative to the parent (PATH_LATTICE) is an input-structure problem that no listed fix repairs: stop.",
    "G5": " A minimum near the grid edge (COVERAGE) is not fixed by densifying: stop. accept_secondary_hold applies only to SECONDARY_COUPLED; a tolerance exceeded by any margin is a failure, not a near miss: stop.",
}
ANCHOR = {"G2": "Over budget cannot be fixed here.", "G5": "Failures that concern the model or the stored data are not fixed by densifying."}
TAG = "A_decoy_remedy"
OUT = ROOT / "results" / "DECOY"


def remedied_cases() -> list[dict]:
    out = []
    for c in B.load_bench_cases():
        g = c["values"]["gate"]
        sysp = c["system_guided"]
        if g in REMEDY:
            assert ANCHOR[g] in sysp, (c["id"], g)
            sysp = sysp.replace(ANCHOR[g], ANCHOR[g] + REMEDY[g], 1)
        out.append({**c, "system_guided": sysp, "remedied": g in REMEDY})
    return out


def summarize(models: dict):
    calls = [json.loads(x) for x in (OUT / TAG / "calls.jsonl").read_text().splitlines()]
    cases = {c["id"]: c for c in remedied_cases()}
    rows = []
    for name in models:
        rr = [r for r in calls if r["model_name"] == name]
        for subset, pick in (("decoys", lambda c: c["class"] == "decoy"), ("non-decoys", lambda c: c["class"] != "decoy"),
                             ("all", lambda c: True)):
            sub = [r for r in rr if pick(cases[r["case"]])]
            cnt = Counter(r["label"] for r in sub)
            rows.append({"model": name, "subset": subset, "n_calls": len(sub), "correct": cnt["correct"], "safe": cnt["safe"],
                         "harmful": cnt["harmful"], "invalid": cnt["invalid"], "error": cnt["error"],
                         "correct_rate": round(cnt["correct"] / len(sub), 4) if sub else "", "harmful_rate": round(cnt["harmful"] / len(sub), 4) if sub else ""})
    with (OUT / "decoy_remedy_summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    per = []
    for name in models:
        for cid, c in cases.items():
            sub = [r for r in calls if r["model_name"] == name and r["case"] == cid]
            if not sub:
                continue
            cnt = Counter(r["label"] for r in sub)
            per.append({"model": name, "case": cid, "class": c["class"], "gate": c["values"]["gate"], "code": c["code"], "n": len(sub),
                        "correct": cnt["correct"], "safe": cnt["safe"], "harmful": cnt["harmful"],
                        "choices": ";".join(f"{k}:{v}" for k, v in Counter(r.get("answered_id") for r in sub).most_common())})
    with (OUT / "decoy_remedy_cases.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per[0]))
        w.writeheader()
        w.writerows(per)
    for r in rows:
        print(f"{r['model']:18s} {r['subset']:11s} n={r['n_calls']:4d}  correct {r['correct_rate']}  harmful {r['harmful_rate']}")
    print(f"written: {OUT / 'decoy_remedy_summary.csv'}, {OUT / 'decoy_remedy_cases.csv'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=str(ROOT / "eval" / "models.yaml"))
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--retry-errors", action="store_true")
    a = ap.parse_args()
    ok, probs = freeze_eval.verify(ROOT / "eval")
    if ok is not True:
        raise SystemExit(f"eval/ not frozen / changed: {probs}")
    models = load_models(Path(a.models))
    if a.summarize:
        return summarize(models)
    cases = remedied_cases()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "remedy_prompts.json").write_text(json.dumps({"remedy": REMEDY, "cases_remedied": [c["id"] for c in cases if c["remedied"]]}, indent=1))
    print(f"{sum(c['remedied'] for c in cases)} of {len(cases)} cases get a remedied prompt (G2 and G5 cases)")
    B.run(TAG, models, cases, ["guided"], a.repeats, a.workers, a.retry_errors, out_root=OUT)
    summarize(models)


if __name__ == "__main__":
    main()
