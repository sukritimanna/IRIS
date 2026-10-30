"""Model-off evaluation tables (E2, E4, E7) as CSVs in results/summary/.

  python -m iris_agent.eval_summary --e2 E2 --e4 E4 --e7 E7_f2,E7_f3,E7_f5,E7_hfo2

E2  gated fault injection (test_runs/<tag>/inject_report.json): detection, handling tier, final status, submissions,
    numbers vs the stored fit, pass.
E4  the same faults with gates logged but never stopping the run: harmless / silent corruption / crashed / stopped.
E7  (a) kill-and-resume: test_runs/<tag>/resume_test.json per kill point; (b) audit completeness: for the latest
    completed run of every system in test_runs/, the number of reported quantities and how many G6 re-derived.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parents[1]
RUNS = AGENT_ROOT / "test_runs"
OUT = AGENT_ROOT / "results" / "summary"


def _write(name, rows):
    if not rows:
        return None
    OUT.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(OUT / name, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    return OUT / name


def e2_rows(tag):
    rep = json.loads((RUNS / tag / "inject_report.json").read_text())
    rows = []
    for r in rep["results"]:
        rows.append({"tag": tag, "frozen": rep.get("frozen"), "fault": r["id"], "name": r["name"], "class": r["class"],
                     "system": r["system"], "split": r["split"], "description": r["fault"],
                     "gate_failures": "; ".join(f"{n} {c}" for n, c in r["failures"]),
                     "detected_by": (lambda f: f"G{f[0][0][1]} {f[0][1]}" if f else "")(r["failures"]),
                     "handling": "; ".join(f"{t}{':' + rid if rid else ''}->{nx}" for t, rid, nx in r["fixes"]),
                     "human_interventions": sum(1 for t, _, _ in r["fixes"] if t == "human"),
                     "rule_fixes": sum(1 for t, _, _ in r["fixes"] if t == "rule"),
                     "subagent_fixes": sum(1 for t, _, _ in r["fixes"] if t == "subagent"),
                     "first_detected_by": r.get("detected_by"), "runs_before_detection": r.get("runs_before_detection"),
                     "runs_submitted_total": r.get("runs_submitted_total"),
                     "final": r["final"], "n_submissions": r["n_submissions"], "numbers_vs_stored": r["vs_stored"],
                     "numbers_identical": r["numbers_identical"],
                     **({"verdict": r["verdict"], "would_detect": r["would_detect"]} if "verdict" in r else
                        {"passed": r["passed"], "failed_checks": ";".join(k for k, v in r["checks"].items() if not v)})})
    return rows


def e7_resume_rows(tags):
    rows = []
    for t in tags:
        d = json.loads((RUNS / t / "resume_test.json").read_text())
        rows.append({"tag": t, "system": d["system"], "kill_after": d["kill_after"], "passed": d["passed"],
                     "g6_rows_compared": d["n_g6"], "reference_thread": d["reference_thread"],
                     "killed_thread": d["killed_thread"],
                     "checks": "; ".join(f"{k}={v}" for k, v in (d.get("checks") or {}).items() if not isinstance(v, (dict, list)))})
    return rows


def e7_audit_rows(e1_tag: str | None = None):
    """Audit completeness per run: the E1 threads (<tag>_<config>) when given, else the latest completed run per
    system (by end timestamp), excluding test / capture / evaluation threads."""
    best = {}
    for a in RUNS.glob(f"{e1_tag}_*/audit.jsonl" if e1_tag else "*/audit.jsonl"):
        th = a.parent.name
        if not e1_tag and th.startswith(("pytest", "cap_", "E1", "E2", "E4", "E7", "fi_", "S5")):
            continue
        ends = [json.loads(x) for x in a.read_text().splitlines() if '"kind": "end"' in x]
        ends = [e for e in ends if e.get("status") == "completed"]
        if not ends:
            continue
        e = ends[-1]
        key = th if e1_tag else (th.rsplit("_h3", 1)[0] if th.startswith("hfo2_") else (e.get("system"), "joint" in th, "d4" in th))
        if key not in best or e["ts"] > best[key]["end"]["ts"]:
            best[key] = {"thread": th, "end": e}
    rows = []
    for v in sorted(best.values(), key=lambda x: x["thread"]):
        g6 = v["end"].get("g6_table") or []
        rows.append({"system": v["end"].get("system"), "thread": v["thread"], "completed_utc": v["end"]["ts"],
                     "reported_quantities": len(g6), "rederived_and_matching": sum(1 for r in g6 if r.get("match")),
                     "fraction": round(sum(1 for r in g6 if r.get("match")) / len(g6), 4) if g6 else None})
    return rows


def interventions(off_tag, on_tag):
    """Interventions per run: the fault set end to end with the model off (rules + human) and on (reference model)."""
    per_run, per_sys = [], {}
    for cond, tag in (("model off (rules + human)", off_tag), ("model on (reference)", on_tag)):
        f = RUNS / tag / "inject_report.json" if tag else None
        if not f or not f.is_file():
            continue
        rep = json.loads(f.read_text())
        for r in rep["results"]:
            hum = sum(1 for t, _, _ in r["fixes"] if t == "human")
            nat = sum(1 for _, c in r["failures"] if c in ("R5_BORDERLINE", "SECONDARY_COUPLED"))   # the clean run's own decisions
            nat = min(nat, hum)
            row = {"condition": cond, "tag": tag, "llm": r.get("llm", "off"), "fault": r["id"], "name": r["name"],
                   "system": r["system"], "split": r["split"], "class": r["class"],
                   "rule_fixes": sum(1 for t, _, _ in r["fixes"] if t == "rule"),
                   "subagent_fixes": sum(1 for t, _, _ in r["fixes"] if t == "subagent"),
                   "human_interventions": hum, "human_published_decisions": nat, "human_for_the_fault": hum - nat,
                   "final": r["final"], "numbers_identical": r["numbers_identical"]}
            per_run.append(row)
            k = (cond, r["system"].split("_")[0])
            a = per_sys.setdefault(k, {"condition": cond, "system": k[1], "runs": 0, "human_interventions": 0,
                                       "human_published_decisions": 0, "human_for_the_fault": 0,
                                       "runs_with_human_for_the_fault": 0, "rule_fixes": 0, "subagent_fixes": 0,
                                       "completed": 0, "numbers_identical": 0})
            a["runs"] += 1
            a["human_interventions"] += hum
            a["human_published_decisions"] += nat
            a["human_for_the_fault"] += hum - nat
            a["runs_with_human_for_the_fault"] += (hum - nat) > 0
            a["numbers_identical"] += r["numbers_identical"] is True
            a["rule_fixes"] += row["rule_fixes"]
            a["subagent_fixes"] += row["subagent_fixes"]
            a["completed"] += r["final"] == "completed"
    for a in per_sys.values():
        a["human_per_run"] = round(a["human_interventions"] / a["runs"], 3)
        a["human_for_the_fault_per_run"] = round(a["human_for_the_fault"] / a["runs"], 3)
    return per_run, sorted(per_sys.values(), key=lambda x: (x["system"], x["condition"]))


LIMIT_KEYS = ("_meV", "_muB", "max_", "min_points", "tol", "edge_margin", "max_rigid_rotation_deg")


def fault_kind(f: dict) -> str:
    """limit: the injection only makes a threshold stricter (the data are fine; the gate fires by construction);
    error: inputs, jobs, vectors or configuration are actually wrong."""
    inj = f.get("injection") or {}
    keys = [k for k in (inj.get("patch") or {}) if k != "run.jobs.wait"]
    jobs = [j for j in inj.get("jobs", ["all"]) if j != "all"]
    if keys and not jobs and all(any(t in k.split(".")[-1] for t in LIMIT_KEYS) for k in keys):
        return "limit"
    return "error"


def augment_e9(e2_tag="E2"):
    """Add to E9_gate_ablation.csv: runs spent on an unusable result (the run stops, crashes or ends with wrong
    numbers: everything it submitted) for the gated run (E2) and the ablated run, and the difference."""
    f = OUT / "E9_gate_ablation.csv"
    if not f.is_file():
        return None
    e2 = {r["id"]: r for r in json.loads((RUNS / e2_tag / "inject_report.json").read_text())["results"]}
    import yaml
    fy = {x["id"]: x for x in yaml.safe_load((AGENT_ROOT / "eval" / "faults.yaml").read_text())["faults"]}
    rows = list(csv.DictReader(open(f)))
    for r in rows:
        g = e2[r["fault"]]
        g_unusable = (g.get("runs_submitted_total") or 0) if g["final"] != "completed" or g["numbers_identical"] is False else 0
        a_unusable = int(r["runs_submitted_total"]) if r["verdict"] in ("stopped", "crashed", "silent corruption") else 0
        r["gated_runs_on_unusable_result"] = g_unusable
        r["ablated_runs_on_unusable_result"] = a_unusable
        r["extra_runs_on_unusable_result"] = a_unusable - g_unusable
        r["is_detecting_gate"] = r["ablated_gate"] == (r["gated_detected_by"] or "").split(" ")[0]
        r["fault_kind"] = fault_kind(fy[r["fault"]])
    return _write("E9_gate_ablation.csv", rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--e2", default=None)
    ap.add_argument("--e4", default=None)
    ap.add_argument("--e7", default=None, help="comma list of resume_test tags")
    ap.add_argument("--e1", default=None, help="E1 tag: audit completeness from its threads")
    ap.add_argument("--e9", action="store_true", help="add the unusable-run columns to E9_gate_ablation.csv")
    ap.add_argument("--interventions", default=None, help="OFF_TAG,ON_TAG: the fault set with the model off / on")
    a = ap.parse_args(argv)
    out = []
    if a.e2:
        out.append(_write("E2_faults_gated.csv", e2_rows(a.e2)))
    if a.e4:
        out.append(_write("E4_faults_ungated.csv", e2_rows(a.e4)))
    if a.e7:
        out.append(_write("E7_kill_resume.csv", e7_resume_rows(a.e7.split(","))))
    out.append(_write("E7_audit_completeness.csv", e7_audit_rows(a.e1)))
    if a.e9:
        out.append(augment_e9(a.e2 or "E2"))
    if a.interventions:
        off, on = (a.interventions.split(",") + [None])[:2]
        pr, ps = interventions(off, on)
        out.append(_write("E3_interventions_per_run.csv", pr))
        out.append(_write("E3_interventions_per_system.csv", ps))
    for p in out:
        if p:
            print(p)


if __name__ == "__main__":
    sys.exit(main())
