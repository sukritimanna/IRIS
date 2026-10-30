"""Eligibility conditions on the recovery menus, tested on the frozen benchmark with the frozen prompts.

Every non-stop option of recovery.yaml now names the error codes it is admissible for (`for:`), and
RecoveryTable.menu(node, code) offers a sub-agent or human only the admissible options; a failure whose admissible
menu is `stop` alone is decided in code and no model is asked. This script runs the 53 frozen cases with their
menus filtered the same way and the prompts unchanged: the code restricts what actions are scientifically
admissible, the model chooses among those.

  python -m eval_extra.eligibility --models eval/models.yaml --repeats 5      # calls only for cases with >1 admissible option
  python -m eval_extra.eligibility --summarize

Scored with the frozen labels (correct / safe / harmful per option). Cases decided by code are scored as the
label of `stop` with no call; the summary separates them. Disclosure: a first version of the conditions admitted
flag_and_continue for SCF_LIMITED; in the run that showed up as 23 of 27 remaining harmful decisions, all on C22,
and the condition was corrected to WALLTIME and NELM only (an SCF-limited frame keeps its energy, rule
NELM_AFTER_ROBUST, so there is nothing to continue without). --summarize applies the current conditions to the
saved calls, so C22 is now decided by code and its old calls are not scored. The script first checks that no case loses its correct
option to the filter (a filter that removed a correct fix would be a wrong eligibility condition, not a result).
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
from iris_agent.recover import RecoveryTable  # noqa: E402

TAG = "A_eligibility"
OUT = ROOT / "results" / "ELIGIBILITY"


def filtered_cases() -> tuple[list[dict], list[dict]]:
    """(cases with >1 admissible option, menus filtered), (cases decided by code: stop only)."""
    table = RecoveryTable(ROOT / "recovery.yaml")
    asked, decided = [], []
    for c in B.load_bench_cases():
        node = c["node"]
        admissible = {o["id"] for o in table.menu(node, c["code"])}
        menu = [o for o in c["menu"] if o["id"] in admissible]
        correct = [i for i, k in c["label_of"].items() if k == "correct"]
        assert any(i in admissible for i in correct), (c["id"], c["code"], correct, admissible)
        c2 = {**c, "menu": menu, "admissible": sorted(admissible)}
        (decided if [o["id"] for o in menu] == ["stop"] else asked).append(c2)
    return asked, decided


def summarize(models: dict):
    asked, decided = filtered_cases()
    calls = [json.loads(x) for x in (OUT / TAG / "calls.jsonl").read_text().splitlines()] if (OUT / TAG / "calls.jsonl").is_file() else []
    by = {c["id"]: c for c in asked + decided}
    asked_ids = {c["id"] for c in asked}
    calls = [r for r in calls if r["case"] in asked_ids]   # a case that the current conditions decide in code is not scored from old calls
    rows = []
    for name in models:
        rr = [r for r in calls if r["model_name"] == name]
        reps = max((r["repeat"] for r in rr), default=-1) + 1
        # code-decided cases count once per repeat with the label of stop
        code_rows = [{"case": c["id"], "label": c["label_of"].get("stop", "invalid")} for c in decided for _ in range(max(reps, 1))]
        for subset, picked in (("asked (model)", rr), ("decided by code", code_rows), ("all", rr + code_rows)):
            cnt = Counter(r["label"] for r in picked)
            n = len(picked)
            rows.append({"model": name, "subset": subset, "n": n, "correct": cnt["correct"], "safe": cnt["safe"], "harmful": cnt["harmful"],
                         "invalid": cnt["invalid"], "error": cnt["error"],
                         "correct_rate": round(cnt["correct"] / n, 4) if n else "", "harmful_rate": round(cnt["harmful"] / n, 4) if n else ""})
        for subset, pick in (("decoys", lambda c: c["class"] == "decoy"), ("non-decoys", lambda c: c["class"] != "decoy")):
            picked = [r for r in rr + code_rows if pick(by[r["case"]])]
            cnt = Counter(r["label"] for r in picked); n = len(picked)
            rows.append({"model": name, "subset": subset, "n": n, "correct": cnt["correct"], "safe": cnt["safe"], "harmful": cnt["harmful"],
                         "invalid": cnt["invalid"], "error": cnt["error"],
                         "correct_rate": round(cnt["correct"] / n, 4) if n else "", "harmful_rate": round(cnt["harmful"] / n, 4) if n else ""})
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "eligibility_summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    per = []
    for c in asked + decided:
        for name in models:
            sub = [r for r in calls if r["model_name"] == name and r["case"] == c["id"]]
            cnt = Counter(r["label"] for r in sub)
            per.append({"case": c["id"], "class": c["class"], "gate": c["values"]["gate"], "code": c["code"], "admissible": ";".join(c["admissible"]),
                        "decided_by": "code (stop only)" if c in decided else "model", "model": name, "n": len(sub),
                        "correct": cnt["correct"], "safe": cnt["safe"], "harmful": cnt["harmful"],
                        "choices": ";".join(f"{k}:{v}" for k, v in Counter(r.get("answered_id") for r in sub).most_common())})
    with (OUT / "eligibility_cases.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per[0])); w.writeheader(); w.writerows(per)
    print(f"{len(decided)} cases decided by code (stop only): {' '.join(c['id'] for c in decided)}")
    for r in rows:
        if r["subset"] in ("all", "decoys", "non-decoys"):
            print(f"{r['model']:18s} {r['subset']:16s} n={r['n']:4d}  correct {r['correct_rate']}  harmful {r['harmful_rate']}")
    print(f"written: {OUT / 'eligibility_summary.csv'}, {OUT / 'eligibility_cases.csv'}")


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
    asked, decided = filtered_cases()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "admissible_menus.json").write_text(json.dumps({c["id"]: {"code": c["code"], "admissible": c["admissible"],
                                                                     "decided_by": "code" if c in decided else "model"} for c in asked + decided}, indent=1))
    print(f"{len(asked)} cases go to the model with a filtered menu; {len(decided)} are decided by code (stop only)")
    B.run(TAG, models, asked, ["guided"], a.repeats, a.workers, a.retry_errors, out_root=OUT)
    summarize(models)


if __name__ == "__main__":
    main()
