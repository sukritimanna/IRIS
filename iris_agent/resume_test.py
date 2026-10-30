"""E7: kill the process after a node, resume from the SQLite checkpoint, and check that the result is
identical to an uninterrupted run.

  python -m iris_agent.resume_test --config configs/cssni3.yaml --kill-after f3 --tag E7

1. reference thread <tag>_ref_<system>: runs start to end in this process (job waits answered with
   "all parts finished").
2. kill thread <tag>_kill_<system>: every step runs as a separate process (`python -m iris_agent.run`
   / `jobend`). With IRIS_KILL_BEFORE=<node after kill-after> the process hard-exits (os._exit 137) when it
   reaches that node — after the checkpoint of the kill-after node is written. A new process then
   continues the thread (`run --continue`) to the end.
3. compare: G6 table (every quantity, reported and re-derived value), the gate outcomes per node,
   final status, number of job submissions. Report: test_runs/<tag>/resume_test.{md,json}.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import config as cfgmod
from .graph import KILL_ENV
from .paths import from_config
from .state import NODES

AGENT_ROOT = Path(__file__).resolve().parents[1]


def _cli(module: str, args: list[str], env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop(KILL_ENV, None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-m", f"iris_agent.{module}", *args], cwd=str(AGENT_ROOT),
                          env=env, capture_output=True, text=True, timeout=1800)


def _status(proc) -> str:
    try:
        return json.loads(proc.stdout[proc.stdout.index("{"):])["status"]
    except Exception:
        return f"exit {proc.returncode}"


def _summary(cfg_path, thread):
    from .run import Session
    with Session(cfg_path, thread) as s:
        st = s.graph.get_state(s.cfg).values
        log = s.audit.read()
    gates = {}
    for r in log:
        if r["kind"] == "gate":
            gates[r["node"]] = r["outcome"]                 # last outcome per node
    end = [r for r in log if r["kind"] == "end"]
    g6 = end[-1]["g6_table"] if end else []
    return {"final": end[-1]["status"] if end else None, "gates": gates, "g6": g6,
            "n_submissions": (st.get("jobs") or {}).get("n_submissions"),
            "kills": sum(r["kind"] == "kill" for r in log), "resumes": sum(r["kind"] == "resume" for r in log)}


def run(cfg_path: str, kill_after: str, tag: str) -> dict:
    if kill_after not in NODES[:-1]:
        raise SystemExit(f"--kill-after must be one of {NODES[:-1]}")
    kill_before = NODES[NODES.index(kill_after) + 1]
    cfg = cfgmod.load(cfg_path)
    system = cfg["system"]
    P = from_config(cfg)
    ref_t, kill_t = f"{tag}_ref_{system}", f"{tag}_kill_{system}"
    cfg_abs = str(Path(cfg_path).resolve())

    # 1. uninterrupted reference
    from .run import Session
    with Session(cfg_abs, ref_t, tag=tag, fresh=True) as s:
        res = s.start()
        while res["status"] == "waiting_on_jobs":
            res = s.resume({"event": "job_end", "parts": "all"})

    # 2. killed and continued, every step a separate process
    steps, killed = [], False
    base = ["--config", cfg_abs, "--thread", kill_t]
    p = _cli("run", base + ["--tag", tag, "--fresh"], {KILL_ENV: kill_before})
    steps.append(("run start", p.returncode, _status(p)))
    killed = p.returncode == 137
    for _ in range(10):
        st = _status(p)
        if p.returncode == 137 and not steps[-1][0].startswith("run --continue"):
            killed = True
            p = _cli("run", base + ["--continue"], {})
            steps.append(("run --continue", p.returncode, _status(p)))
        elif st == "waiting_on_jobs":
            p = _cli("jobend", base, {} if killed else {KILL_ENV: kill_before})
            steps.append(("jobend (all parts)", p.returncode, _status(p)))
        else:
            break
    a, b = _summary(cfg_abs, ref_t), _summary(cfg_abs, kill_t)
    same_g6 = [(x["quantity"], x["reported"], x["rederived"]) for x in a["g6"]] == \
              [(x["quantity"], x["reported"], x["rederived"]) for x in b["g6"]]
    checks = {"killed": b["kills"] == 1, "both completed": a["final"] == b["final"] == "completed",
              "G6 table identical": bool(a["g6"]) and same_g6, "gate outcomes identical": a["gates"] == b["gates"],
              "submitted once": a["n_submissions"] == b["n_submissions"] == 1}
    out = {"tag": tag, "system": system, "kill_after": kill_after, "reference_thread": ref_t,
           "killed_thread": kill_t, "steps": steps, "checks": checks, "passed": all(checks.values()),
           "n_g6": len(a["g6"]), "reference": {k: a[k] for k in ("final", "gates", "n_submissions")},
           "killed": {k: b[k] for k in ("final", "gates", "n_submissions", "kills", "resumes")}}
    d = P.out(P.agent_root, "test_runs", tag)
    d.mkdir(parents=True, exist_ok=True)
    P.out(d, "resume_test.json").write_text(json.dumps(out, indent=1, default=str))
    md = [f"# E7 resume test — {system}, killed after {kill_after}", "",
          f"{'PASS' if out['passed'] else 'FAIL'}: " + ", ".join(f"{k} {'✓' if v else '✗'}" for k, v in checks.items()), "",
          "| step (separate process) | exit code | status |", "|---|---|---|"]
    md += [f"| {s} | {rc} | {st} |" for s, rc, st in steps]
    md += ["", f"G6 rows compared: {out['n_g6']}; reference thread `{ref_t}`, killed thread `{kill_t}`."]
    P.out(d, "resume_test.md").write_text("\n".join(md) + "\n")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--kill-after", default="f3")
    ap.add_argument("--tag", default="E7")
    a = ap.parse_args(argv)
    out = run(a.config, a.kill_after, a.tag)
    d = from_config(cfgmod.load(a.config))
    print((d.agent_root / "test_runs" / a.tag / "resume_test.md").read_text())
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
