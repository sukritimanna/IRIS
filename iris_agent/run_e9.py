"""E9 gate ablation: remove one gate at a time and record what happens to each fault.

  python -m iris_agent.run_e9 --e2 E2 --configs configs [--full-matrix F001,...,F009] [--only F010,...]

For every fault, the gate that caught it in the gated run (E2) is removed (`--ablate no-gN`: the gate still runs and
is logged, but does not stop the run) and the fault is replayed. Removing any other gate cannot change the run up to
that point (earlier gates passed, later gates are never reached), so this is the ablation that matters; for the
faults given in --full-matrix every gate G0..G6 is removed in turn as a check of that argument.
Per run: which gate catches it instead (or none), DFT runs submitted before detection (f3 submission records: the
runs a real campaign would have spent), final status, numbers vs the stored fit, verdict (harmless / silent
corruption / stopped / crashed). Writes results/summary/E9_gate_ablation.csv (appending rows of earlier calls).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .inject import load_faults, run_fault

AGENT_ROOT = Path(__file__).resolve().parents[1]
OUT = AGENT_ROOT / "results" / "summary" / "E9_gate_ablation.csv"
FIELDS = ["fault", "name", "class", "system", "split", "ablated_gate", "gated_detected_by", "gated_runs_before_detection",
          "detected_by", "runs_before_detection", "extra_runs_wasted", "runs_submitted_total", "final", "verdict",
          "numbers_identical", "human_interventions", "thread"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--e2", default="E2", help="tag of the gated model-off run (test_runs/<tag>/inject_report.json)")
    ap.add_argument("--faults", default=str(AGENT_ROOT / "eval" / "faults.yaml"))
    ap.add_argument("--configs", default=str(AGENT_ROOT / "configs"))
    ap.add_argument("--full-matrix", default="F001,F002,F003,F004,F005,F006,F007,F008,F009")
    ap.add_argument("--only", default=None)
    ap.add_argument("--tag", default="E9")
    a = ap.parse_args(argv)
    e2 = {r["id"]: r for r in json.loads((AGENT_ROOT / "test_runs" / a.e2 / "inject_report.json").read_text())["results"]}
    faults = [f for f in load_faults(a.faults) if f["id"] in e2 and (not a.only or f["id"] in a.only.split(","))]
    full = set(a.full_matrix.split(",")) if a.full_matrix else set()
    rows = list(csv.DictReader(open(OUT))) if OUT.is_file() else []
    done = {(r["fault"], r["ablated_gate"]) for r in rows}
    for f in faults:
        g = e2[f["id"]]
        gates = [f"G{i}" for i in range(7)] if f["id"] in full else ([g["detected_by"].split()[0]] if g.get("detected_by") else [])
        for gate in gates:
            if (f["id"], gate) in done:
                continue
            tag = f"{a.tag}_{gate.lower()}"
            r = run_fault(f, Path(a.configs), tag, AGENT_ROOT / "test_runs" / tag, ablations=[f"no-{gate.lower()}"])
            row = {"fault": f["id"], "name": f["name"], "class": f["class"], "system": f["system"], "split": f["split"],
                   "ablated_gate": gate, "gated_detected_by": g.get("detected_by"),
                   "gated_runs_before_detection": g.get("runs_before_detection"),
                   "detected_by": r.get("detected_by") or "none", "runs_before_detection": r["runs_before_detection"],
                   "extra_runs_wasted": r["runs_before_detection"] - (g.get("runs_before_detection") or 0),
                   "runs_submitted_total": r["runs_submitted_total"], "final": r["final"], "verdict": r.get("verdict"),
                   "numbers_identical": r["numbers_identical"], "human_interventions": r["human_interventions"],
                   "thread": r["thread"]}
            print(json.dumps(row))
            rows.append(row)
            OUT.parent.mkdir(parents=True, exist_ok=True)
            with open(OUT, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS)
                w.writeheader()
                w.writerows(rows)
    print(OUT)


if __name__ == "__main__":
    sys.exit(main())
