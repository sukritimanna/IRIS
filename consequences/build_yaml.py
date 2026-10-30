"""Experiment C (1): write eval/consequences.yaml — the tolerance of every reported quantity (the precision f6 uses to
re-derive it, from the clean E1 replay of each config) and the consequence classes with their decision rules.

  python -m consequences.build_yaml       # then: python -m iris_agent.freeze_eval eval/ --refreeze --reason "..."
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CONFIGS = ["cssni3", "cssni3_d4", "ca3ti2o7", "inmno3", "inmno3_joint", "ermno3", "ermno3_joint", "bifeo3",
           "hfo2_T1", "hfo2_T2", "hfo2_T3", "hfo2_T4", "hfo2_T5"]

HEADER = """# Experiment C: consequence classes of a recovery option (frozen with eval/; written by consequences/build_yaml.py).
#
# A branch = the faulted run forked at the failed gate, the option injected through Command(resume=...), then run to END
# with all gates on, the same retry budget, rules on, no sub-agent; further human questions are answered with the
# published decision (R5 include_borderline, D4 accept_secondary_hold) or `stop` (then human_needed = true).
# Numbers are compared with the fault-free replay of the same config (E1), quantity by quantity, with the tolerance
# below: |value - clean| <= tol (tol = the precision f6 re-derives that quantity with; null = must be equal).
"""

CLASSES = {
    "stopped": "the option is `stop`: the run ends and the human takes over (nothing else happens)",
    "not-evaluable": "the branch needs data replay does not have (it ends at G3 UNMATCHED after the option asked for "
                     "frames that were never computed, e.g. densify) — production would have to compute them",
    "rejected": "after the option a gate fails again and the branch ends without completing (stop / retry budget / "
                "human), i.e. the gates refused the option's result",
    "scope-change": "the branch completes, but the result is about something else: the set of reported quantities, "
                    "the active irreps or the number of frames with an energy differ from the fault-free replay",
    "accepted-wrong": "the branch completes with the same scope, but at least one reported number differs from the "
                      "fault-free replay by more than its tolerance",
    "accepted-wasted": "the branch completes with every number within tolerance, but submits more DFT runs than the "
                       "cheapest branch of the same case that also completes correctly",
    "accepted-correct": "the branch completes with every number within tolerance at the lowest run count of its case",
}
ORDER = ["stopped", "not-evaluable", "rejected", "scope-change", "accepted-wrong", "accepted-wasted", "accepted-correct"]
# A branch contradicts its frozen label when its consequence is not in this list for that label (reported, never fixed).
COMPATIBLE = {
    "correct": ["accepted-correct", "stopped", "not-evaluable"],
    "safe": ["stopped", "accepted-correct", "accepted-wasted", "rejected", "not-evaluable"],
    "harmful": ["accepted-wrong", "accepted-wasted", "rejected", "scope-change", "not-evaluable"],
}


def tolerances() -> dict:
    from langgraph.checkpoint.sqlite import SqliteSaver
    out = {}
    for c in CONFIGS:
        th = f"E1_{c}"
        cv = SqliteSaver(sqlite3.connect(str(ROOT / "test_runs" / th / "iris.sqlite"))).get(
            {"configurable": {"thread_id": th}})["channel_values"]
        out[c] = {r["name"]: (None if r["tol"] is None else float(r["tol"])) for r in cv["report"]["rows"]}
    return out


def main():
    data = {"version": 1, "source": "f6 tolerances of the clean E1 replays (test_runs/E1_<config>)",
            "classes": CLASSES, "order": ORDER, "compatible_with_label": COMPATIBLE,
            "comparison": {"identical": "|Δ| <= 1e-12 (or equal for non-numbers)", "within_tolerance": "|Δ| <= tol",
                           "different": "|Δ| > tol for at least one quantity"},
            "tolerances": tolerances()}
    out = ROOT / "eval" / "consequences.yaml"
    out.write_text(HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=140))
    print(out, sum(len(v) for v in data["tolerances"].values()), "quantities")


if __name__ == "__main__":
    main()
