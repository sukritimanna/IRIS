"""Experiment A (4): the 53 faulted runs (E3 protocol) with each sub-agent setting, one row per (setting, fault).

  python -m policies.build_runs          # -> results/A/A_runs.csv

Settings (tag in test_runs/): rules + human, no sub-agent (E2); claude-sonnet (E3_on, run on the Mac); tree (A_tree);
retrieval, leave-one-out by fault (A_retrieval).
Columns per run:
  completed_without_handoff  completed, no question to the human and no sub-agent `stop`
  human_questions            interrupts answered by the (scripted) human; of which published_decisions = R5 / D4
  subagent_stops             sub-agent chose `stop` (ends the run: a hand-off to the human)
  handoffs                   human_questions + subagent_stops
  attempts                   recover invocations (rule, sub-agent and human fixes)
  runs_submitted             DFT runs the campaign would submit (f3 submission records; nothing is computed in replay)
  runs_vs_clean / extra_runs  runs_submitted minus the clean replay of the same config (E1); extra_runs = its positive
                             part (a run that stops early submits fewer, which is not a saving to add up)
  numbers_identical          every reported number equals the clean replay (only for completed runs)
Aggregate rows per setting follow the per-run rows.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from iris_agent.eval_summary import fault_kind  # noqa: E402
from iris_agent.inject import load_faults, submitted_runs  # noqa: E402

RUNS = ROOT / "test_runs"
SETTINGS = [("rules + human (no sub-agent)", "E2"), ("claude-sonnet", "E3_on"), ("tree", "A_tree"),
            ("retrieval (leave-one-out)", "A_retrieval")]
NATURAL = ("R5_BORDERLINE", "SECONDARY_COUPLED")


def _ran_out(f: dict, r: dict) -> bool:
    jobs = [j for j in (f.get("injection") or {}).get("jobs", []) if j != "all"]
    n_fail = sum(1 for j in jobs if isinstance(j, dict) and j.get("failed"))
    n_waits = sum(1 for x in r.get("steps", []) if x.startswith("jobs:"))
    return bool(r["final"] == "completed" and n_fail >= 2 and n_waits > len(jobs))


def baseline_runs(system: str) -> int:
    return sum(n for _, n in submitted_runs(RUNS / f"E1_{system}"))


def main():
    faults = {f["id"]: f for f in load_faults(ROOT / "eval" / "faults.yaml")}
    rows = []
    for name, tag in SETTINGS:
        rep = RUNS / tag / "inject_report.json"
        if not rep.is_file():
            print(f"skip {name}: {rep} missing")
            continue
        for r in json.loads(rep.read_text())["results"]:
            log = [json.loads(x) for x in (RUNS / r["thread"] / "audit.jsonl").read_text().splitlines()]
            fixes = [x for x in log if x["kind"] == "fix"]
            hq = [x for x in fixes if x["level"] == "human"]
            stops = [x for x in fixes if x["level"] == "subagent" and x.get("option_id") == "stop"]
            pub = sum(1 for x in hq if x.get("gate_code") in NATURAL)
            base = baseline_runs(r["system"])
            sub = r.get("runs_submitted_total")
            rows.append({"setting": name, "tag": tag, "fault": r["id"], "system": r["system"], "split": r["split"],
                         "class": r["class"], "fault_kind": fault_kind(faults[r["id"]]), "final": r["final"],
                         "completed_without_handoff": r["final"] == "completed" and not hq and not stops,
                         "handoffs": len(hq) + len(stops), "human_questions": len(hq), "published_decisions": pub,
                         "subagent_stops": len(stops),
                         "subagent_fixes": sum(1 for x in fixes if x["level"] == "subagent" and x.get("option_id") != "stop"),
                         "rule_fixes": sum(1 for x in fixes if x["level"] == "rule"), "attempts": len(fixes),
                         "runs_submitted": sub, "baseline_runs": base,
                         "runs_vs_clean": None if sub is None else sub - base,
                         "extra_runs": None if sub is None else max(0, sub - base),
                         "numbers_identical": r["numbers_identical"],
                         # the fault scripts its job failures; once they are used up every later job succeeds ("all").
                         # A run that completes only after that point completed because the script ran out, which
                         # replay assumes and production would not guarantee (e.g. a part that fails again and again)
                         "completed_after_scripted_failures_ran_out": _ran_out(faults[r["id"]], r),
                         "subagent_choices": ";".join(f"{x.get('gate_code')}:{x.get('option_id')}" for x in fixes
                                                      if x["level"] == "subagent")})
    for r in rows:     # a completion that only happened because the scripted failures ran out is not credited
        r["final_scored"] = ("not completed (scripted failures ran out)" if r["completed_after_scripted_failures_ran_out"]
                             else r["final"])
        if r["completed_after_scripted_failures_ran_out"]:
            r["completed_without_handoff"] = False
    agg = []
    for name, tag in SETTINGS:
        rr = [r for r in rows if r["setting"] == name]
        if not rr:
            continue
        for sp in ("all", "seed", "held-out"):
            s = [r for r in rr if sp == "all" or r["split"] == sp]
            agg.append({"setting": name, "tag": tag, "fault": f"ALL ({sp})", "split": sp, "system": f"n={len(s)}",
                        "completed_without_handoff": sum(bool(r["completed_without_handoff"]) for r in s),
                        "final": f"completed {sum(r['final'] == 'completed' for r in s)}",
                        "final_scored": f"completed {sum(r['final_scored'] == 'completed' for r in s)}",
                        "completed_after_scripted_failures_ran_out": sum(bool(r["completed_after_scripted_failures_ran_out"]) for r in s),
                        "handoffs": sum(r["handoffs"] for r in s), "human_questions": sum(r["human_questions"] for r in s),
                        "published_decisions": sum(r["published_decisions"] for r in s),
                        "subagent_stops": sum(r["subagent_stops"] for r in s),
                        "subagent_fixes": sum(r["subagent_fixes"] for r in s), "rule_fixes": sum(r["rule_fixes"] for r in s),
                        "attempts": sum(r["attempts"] for r in s),
                        "runs_submitted": sum(r["runs_submitted"] or 0 for r in s),
                        "extra_runs": sum(r["extra_runs"] or 0 for r in s),
                        "numbers_identical": f"{sum(r['numbers_identical'] is True and r['final_scored'] == 'completed' for r in s)} identical / "
                                             f"{sum(r['numbers_identical'] is False for r in s)} differ"})
    out = ROOT / "results" / "A" / "A_runs.csv"
    keys = list(rows[0])
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows + agg)
    for a in agg:
        if a["split"] == "all":
            print({k: a[k] for k in ("setting", "completed_without_handoff", "final", "final_scored", "handoffs", "human_questions",
                                     "subagent_stops", "attempts", "extra_runs", "numbers_identical")})
    print(out)


if __name__ == "__main__":
    main()
