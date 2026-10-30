"""D4 hard-secondary scans on the CsSnI3 replay (configs/cssni3_d4.yaml or $IRIS_CSSNI3_D4_CONFIG): the three
stored 13-point X5+ scans are matched, fitted in f5 and judged by G5. At the scaled child (0.80 x the child
primaries) X5+ is induced and releases 1.92 meV/f.u. > 0.5 x the ring corrugation, so G5 stops the run with
SECONDARY_COUPLED and the human keeps X5+ at zero with the caveat."""
import json
import os
import shutil
from pathlib import Path

import pytest

from iris_agent import config as cfgmod
from iris_agent.paths import from_config

from .conftest import AGENT

CFG = Path(os.environ.get("IRIS_CSSNI3_D4_CONFIG", AGENT / "configs" / "cssni3_d4.yaml"))


def _available():
    try:
        cfg = cfgmod.load(CFG)
        P = from_config(cfg)
        return all((P.repo_root / x["grid"] / "grid_manifest.json").is_file() and (P.repo_root / x["energies"]).is_file()
                   for x in cfg["run"]["replay"]["extra_references"]) and P.repo("energies_csv").is_file()
    except Exception:
        return False


@pytest.mark.skipif(not _available(), reason="CsSnI3 X5+ scans not present")
def test_d4_cssni3_x5_scans():
    from langgraph.checkpoint.sqlite import SqliteSaver
    import sqlite3

    from iris_agent.jobend import event
    from iris_agent.regression import build
    from iris_agent.run import Session
    thread = "pytest_d4_cssni3"
    P = from_config(cfgmod.load(CFG))
    rd = P.agent_root / "test_runs" / thread
    if rd.exists():
        shutil.rmtree(rd)
    with Session(CFG, thread) as s:
        res = s.start()
        while res["status"] == "waiting_on_jobs":
            res = s.resume(event())
        assert res["status"] == "interrupted" and res["interrupt"][0]["code"] == "SECONDARY_COUPLED", res
        res = s.resume({"option": "accept_secondary_hold"})
    assert res["status"] == "completed", res
    cv = SqliteSaver(sqlite3.connect(str(rd / "iris.sqlite"))).get_tuple({"configurable": {"thread_id": thread}}).checkpoint["channel_values"]
    d4, jobs = cv["model"]["d4"], cv["jobs"]
    assert jobs["n_matched"] == jobs["n_frames"] == 962 + 39
    sc = {x["name"]: x for x in d4["scans"]}
    assert sc["origin"]["class"] == "hard" and sc["ring"]["class"] == "hard" and sc["child80"]["class"] == "induced"
    assert sc["child80"]["deg4"]["a_star_A"] == pytest.approx(0.155, abs=2e-3)
    assert -sc["child80"]["deg4"]["gain_meV"] == pytest.approx(1.92, abs=0.01)
    assert sc["child80"]["base_over_child"]["M3+"] == pytest.approx(0.797, abs=1e-3)
    assert d4["accepted"] and cv["report"]["n_ok"] == cv["report"]["n_numbers"]
    assert set(jobs["stored_input_sets_by_group"]) == {"main", "d4_origin", "d4_ring", "d4_child80"}
    out, _, _ = build(str(CFG), thread)
    assert not [r for r in out["rows"] if r["quantity"].startswith("D4") and r["stored_ok"] is False]
    log = [json.loads(x) for x in (rd / "audit.jsonl").read_text().splitlines()]
    assert any(r.get("gate_code") == "SECONDARY_COUPLED" for r in log)
