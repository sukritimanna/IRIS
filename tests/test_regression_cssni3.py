"""Full CsSnI3 replay regression through the f3 job wait (needs the real repo data; skipped elsewhere).

Runs configs/cssni3.yaml (or $IRIS_REGRESSION_CONFIG) in thread `pytest_regression`:
start -> f3 waits on 25 parts -> job-end for parts 0-9 (fresh session) -> still waiting ->
a non-job answer is rejected -> job-end for the rest -> completes; then checks the paper's numbers.
"""
import json
import os
import shutil
from pathlib import Path

import pytest

from iris_agent import config as cfgmod
from iris_agent.paths import from_config

from .conftest import AGENT

CFG = Path(os.environ.get("IRIS_REGRESSION_CONFIG", AGENT / "configs" / "cssni3.yaml"))


def _available():
    try:
        P = from_config(cfgmod.load(CFG))
        return (P.repo("reference_grid") / "grid_manifest.json").is_file() and P.repo("energies_csv").is_file()
    except Exception:
        return False


@pytest.mark.skipif(not _available(), reason="CsSnI3 reference data not present")
def test_cssni3_replay_with_job_wait_reproduces_paper():
    from iris_agent.jobend import event
    from iris_agent.regression import build
    from iris_agent.run import Session
    thread = "pytest_regression"
    P = from_config(cfgmod.load(CFG))
    rd = P.agent_root / "test_runs" / thread
    if rd.exists():
        shutil.rmtree(rd)
    with Session(CFG, thread) as s:
        res = s.start()
    assert res["status"] == "waiting_on_jobs" and len(res["parts_pending"]) == 25
    with Session(CFG, thread) as s:                                       # as after a restart
        res = s.resume(event("0-9"))
        assert res["status"] == "waiting_on_jobs" and res["parts_pending"] == list(range(10, 25))
        res = s.resume({"option": "stop"})                               # not a job event: rejected
        assert res["status"] == "waiting_on_jobs" and len(res["parts_pending"]) == 15
    with Session(CFG, thread) as s:
        res = s.resume(event())
    assert res["status"] == "completed", res
    rec = json.loads((rd / "f3_jobs" / "submission.json").read_text())
    assert rec["n_submissions"] == 1                                     # never submitted twice
    log = [json.loads(x) for x in (rd / "audit.jsonl").read_text().splitlines()]
    assert [r.get("waiting_on") for r in log if r["kind"] == "interrupt"] == ["jobs"] * 3
    assert sum(r["kind"] == "resume" for r in log) == 3

    out, _, _ = build(str(CFG), thread)
    rows = {r["quantity"]: r for r in out["rows"]}
    assert out["skeptic"]["n_ok"] == out["skeptic"]["n_numbers"]
    for q in ("A_p M3+ (Å)", "A_p R4+ (Å)", "A_p R5+ (Å)", "A_p X5+ (Å)", "active set (axes)",
              "frames in #221", "frames in #127", "frames in #74", "frames in #62", "grid N",
              "Landau a1", "Landau a2", "Landau λ", "fit RMS (meV/f.u.)", "fit nodes (r ≤ 1.05 Å)",
              "fit ring depth below cubic (meV/f.u.)", "fit ring corrugation (meV/f.u.)"):
        assert rows[q]["paper_ok"], rows[q]
    for q in ("Landau a1", "Landau b1", "Landau c1", "Landau a2", "Landau b2", "Landau c2", "Landau λ",
              "Landau μ", "fit RMS (meV/f.u.)", "frames matched to stored structures"):
        assert rows[q]["stored_ok"], rows[q]
