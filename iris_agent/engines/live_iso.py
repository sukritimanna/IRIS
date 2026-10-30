"""f1 live (run.mode live): the ISODISTORT decomposition computed during the run, not read from a stored campaign.

The staged walkthrough (demo/staged_walkthrough, the pipeline the stored campaigns were made with) is run as four
subprocesses, steps 0-3, inside agent_root:

  step0_input.py        input validation, parent/child determination, RUN_MANIFEST.json
  step1_standardize.py  spglib tolerance ladder + FINDSYM (iris.lib.findsym, iso.byu.edu)
  step2_subgroup.py     group-subgroup pre-screen (pymatgen ITA tables)
  step3_isodistort.py   live ISODISTORT (iris.lib.isodistort): modes, tree, movie, modes-details

Everything the server returned is kept verbatim under <run>/step3_isodistort/04_raw_isodistort/, the folder
nodes/f1_crystallographer.py reads (engines/stored_isodistort.load): f1, G1 and f2 are then the same code as in
replay — only the source of the decomposition changes, and decomposition["source"] records it.

The walkthrough writes demo/runs/<tag>__<timestamp>/ relative to its working directory, so it is run with the
working directory set to paths.isodistort_live (inside agent_root; Paths.out refuses anything else). A completed
run there (04_raw_isodistort/modes_details.txt present) is reused on a retry; overrides.f1.refresh_isodistort
forces a new call.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RAW = "step3_isodistort/04_raw_isodistort"
DONE_MARK = "modes_details.txt"


def _completed_run(cwd: Path) -> Path | None:
    runs = sorted((cwd / "demo" / "runs").glob("*__*")) if (cwd / "demo" / "runs").is_dir() else []
    for r in reversed(runs):
        if (r / RAW / DONE_MARK).is_file():
            return r
    return None


def _run(cmd: list[str], cwd: Path, env: dict, log: Path, title: str) -> str:
    with open(log, "a") as fh:
        fh.write(f"\n==== {title} [{datetime.now(timezone.utc).isoformat(timespec='seconds')}]\n$ {' '.join(cmd)}\n")
    out = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=1800)
    with open(log, "a") as fh:
        fh.write(out.stdout)
        if out.stderr:
            fh.write("\n--- stderr ---\n" + out.stderr)
        fh.write(f"\n==== exit {out.returncode}\n")
    if out.returncode != 0:
        tail = (out.stderr or out.stdout).strip().splitlines()[-6:]
        raise RuntimeError(f"{title} failed (exit {out.returncode}): " + " | ".join(tail))
    return out.stdout


def ensure_live_decomposition(P, cfg: dict, parent_cif: str, child_cif: str, refresh: bool = False) -> dict:
    """Run steps 0-3 once; return {"run_dir", "raw_dir", "reused", "log"} (absolute paths)."""
    cwd = P.out(P.repo_root / cfg["paths"]["isodistort_live"])
    cwd.mkdir(parents=True, exist_ok=True)
    log = P.out(cwd, "live_isodistort.log")
    done = None if refresh else _completed_run(cwd)
    if done is not None:
        return {"run_dir": str(done), "raw_dir": str(done / RAW), "reused": True, "log": str(log)}
    sw = P.repo("walkthrough")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(x for x in (str(P.repo_root), str(sw), os.environ.get("PYTHONPATH", "")) if x)}
    py = sys.executable
    system_json = P.repo("system_json")
    tag = f"{cfg['system']}_{cfg['expected']['parent_sg']}_to_{cfg['expected']['child_sg']}"
    out0 = _run([py, str(sw / "step0_input.py"), str(parent_cif), str(child_cif), tag, "--system", str(system_json)],
                cwd, env, log, "step 0 input")
    m = re.search(r"RUN DIRECTORY \(all results here\): (\S+?)/?\s*$", out0, re.M)
    if not m:
        raise RuntimeError("step 0 did not report its run directory")
    run_dir = (cwd / m.group(1)).resolve()
    if not run_dir.is_relative_to(P.agent_root):
        raise RuntimeError(f"walkthrough wrote outside agent_root: {run_dir}")
    _run([py, str(sw / "step1_standardize.py"), str(run_dir)], cwd, env, log, "step 1 standardize + FINDSYM")
    _run([py, str(sw / "step2_subgroup.py"), str(run_dir)], cwd, env, log, "step 2 subgroup pre-screen")
    s2 = run_dir / "step2_subgroup" / "step2_result.json"
    if s2.is_file() and json.loads(s2.read_text()).get("status") == "FAIL":
        raise RuntimeError(f"step 2: {json.loads(s2.read_text()).get('reason')}")
    _run([py, str(sw / "step3_isodistort.py"), str(run_dir), str(cfg["policy"].get("a_thr", 0.05))],
         cwd, env, log, "step 3 ISODISTORT (live)")
    raw = run_dir / RAW
    if not (raw / DONE_MARK).is_file():
        raise RuntimeError(f"step 3 ended without {RAW}/{DONE_MARK}")
    return {"run_dir": str(run_dir), "raw_dir": str(raw), "reused": False, "log": str(log)}


def live_paths(P, cfg: dict, info: dict):
    """A Paths view whose reference_run / isodistort_stored point at the live run (f1 reads them as in replay)."""
    from ..paths import Paths
    ent = {k: v for k, v in cfg["paths"].items() if k not in ("repo_root", "agent_root")}
    ent["reference_run"], ent["isodistort_stored"] = info["run_dir"], info["raw_dir"]
    return Paths(cfg["paths"]["repo_root"], cfg["paths"]["agent_root"], ent)
