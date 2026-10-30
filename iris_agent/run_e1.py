"""E1: end-to-end replays of every system, model off; the human answers are the paper's decisions.

  python -m iris_agent.run_e1 --configs configs [--only cssni3,hfo2_T1] [--tag E1]

Thread E1_<config stem>; job waits are answered with "all parts finished". Scripted human answers (the published
decisions, asked at run time): R5_BORDERLINE -> include_borderline (InMnO3, both stages); SECONDARY_COUPLED ->
accept_secondary_hold (CsSnI3 D4). Any other human question stops the run (and is reported).
Writes results/summary/E1_runs.csv: status, gate trail, rule / sub-agent / human counts, wall time, G6 counts.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parents[1]
SYSTEMS = ["cssni3", "cssni3_d4", "ca3ti2o7", "inmno3", "inmno3_joint", "ermno3", "ermno3_joint", "bifeo3",
           "hfo2_T1", "hfo2_T2", "hfo2_T3", "hfo2_T4", "hfo2_T5"]
ANSWERS = {"R5_BORDERLINE": {"option": "include_borderline"}, "SECONDARY_COUPLED": {"option": "accept_secondary_hold"}}


def run_one(stem: str, cfg_dir: Path, tag: str) -> dict:
    from .run import Session
    thread = f"{tag}_{stem}"
    t0 = time.monotonic()
    asked = []
    with Session(cfg_dir / f"{stem}.yaml", thread, tag=tag, fresh=True) as s:
        res = s.start()
        while res["status"] in ("waiting_on_jobs", "interrupted"):
            if res["status"] == "waiting_on_jobs":
                res = s.resume({"event": "job_end", "parts": "all"})
                continue
            code = res["interrupt"][0].get("code")
            asked.append(code)
            if code not in ANSWERS:
                break
            res = s.resume(ANSWERS[code])
        log = s.audit.read()
    gates = [f"{r['gate']} {r.get('gate_code')}" for r in log if r["kind"] == "gate"]
    fixes = [r for r in log if r["kind"] == "fix"]
    end = next((r for r in reversed(log) if r["kind"] == "end"), {})
    g6 = end.get("g6_table") or []
    return {"config": stem, "thread": thread, "status": res["status"], "last_node": res.get("last_node"),
            "gate_trail": " > ".join(gates), "gate_failures": sum(1 for r in log if r["kind"] == "gate" and r.get("outcome") == "fail"),
            "rule_fixes": sum(1 for f in fixes if f["level"] == "rule"),
            "subagent_fixes": sum(1 for f in fixes if f["level"] == "subagent"),
            "human_interventions": sum(1 for f in fixes if f["level"] == "human"), "human_questions": ";".join(asked),
            "g6_quantities": len(g6), "g6_matching": sum(1 for r in g6 if r.get("match")),
            "wall_time_s": round(time.monotonic() - t0, 1)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default=str(AGENT_ROOT / "configs"))
    ap.add_argument("--only", default=None)
    ap.add_argument("--tag", default="E1")
    a = ap.parse_args(argv)
    stems = a.only.split(",") if a.only else SYSTEMS
    out = AGENT_ROOT / "results" / "summary"
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{a.tag}_runs.csv"
    rows = []
    if f.is_file():                                     # keep rows of systems not rerun now
        rows = [r for r in csv.DictReader(open(f)) if r["config"] not in stems]
    for st in stems:
        r = run_one(st, Path(a.configs), a.tag)
        print(json.dumps(r))
        rows.append(r)
    rows.sort(key=lambda r: SYSTEMS.index(r["config"]) if r["config"] in SYSTEMS else 99)
    with open(f, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f)


if __name__ == "__main__":
    sys.exit(main())
