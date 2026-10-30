"""Ca3Ti2O7 replay of the manuscript (X3-, X2+) plane in true A_p, through the f3 job wait
(needs the real repo data; skipped elsewhere). Config: configs/ca3ti2o7.yaml or $IRIS_CA3_CONFIG."""
import json
import os
import shutil
from pathlib import Path

import pytest

from iris_agent import config as cfgmod
from iris_agent.paths import from_config

from .conftest import AGENT

CFG = Path(os.environ.get("IRIS_CA3_CONFIG", AGENT / "configs" / "ca3ti2o7.yaml"))


def _available():
    try:
        P = from_config(cfgmod.load(CFG))
        return (P.repo("reference_grid") / "grid_manifest.json").is_file() and P.repo("energies_csv").is_file()
    except Exception:
        return False


@pytest.mark.skipif(not _available(), reason="Ca3Ti2O7 reference data not present")
def test_ca3ti2o7_replay_in_Ap_reproduces_manuscript_plane():
    from iris_agent.jobend import event
    from iris_agent.regression import build
    from iris_agent.run import Session
    thread = "pytest_regression_ca3ti2o7"
    P = from_config(cfgmod.load(CFG))
    rd = P.agent_root / "test_runs" / thread
    if rd.exists():
        shutil.rmtree(rd)
    with Session(CFG, thread) as s:
        res = s.start()
        while res["status"] == "waiting_on_jobs":
            res = s.resume(event())
    assert res["status"] == "completed", res
    assert json.loads((rd / "f3_jobs" / "submission.json").read_text())["n_submissions"] == 1
    out, _, _ = build(str(CFG), thread)
    rows = {r["quantity"]: r for r in out["rows"]}
    assert out["skeptic"]["n_ok"] == out["skeptic"]["n_numbers"]
    assert all(r["paper_ok"] in (True, None) for r in out["rows"])
    assert rows["primaries (translation-free walk)"]["iris"] == ["X3-", "X2+"]
    assert rows["held at zero"]["iris"] == ["GM5-"]
    assert rows["frames matched to stored structures"]["iris"] == 1372
    assert rows["figure CSV max |ΔE| (meV/f.u.)"]["stored_ok"]
