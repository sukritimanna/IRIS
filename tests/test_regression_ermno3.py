"""ErMnO3 (K3, GM2-) plane + P-axis replay: a_P fixed from the P axis, then the plane fit (published
procedure). Needs the real repo data; config configs/ermno3.yaml or $IRIS_ERMNO3_CONFIG."""
import json
import os
import shutil
from pathlib import Path

import pytest

from iris_agent import config as cfgmod
from iris_agent.paths import from_config

from .conftest import AGENT

CFG = Path(os.environ.get("IRIS_ERMNO3_CONFIG", AGENT / "configs" / "ermno3.yaml"))


def _available():
    try:
        cfg = cfgmod.load(CFG)
        P = from_config(cfg)
        dirs = [P.repo_root / d["dir"] for d in cfg["run"]["replay"]["poscar_dirs"]]
        return (P.repo("reference_grid") / "grid_manifest.json").is_file() and all(d.is_dir() for d in dirs) \
            and P.repo("energies_csv").is_file()
    except Exception:
        return False


@pytest.mark.skipif(not _available(), reason="ErMnO3 reference data not present")
def test_ermno3_plane_replay_fixed_aP():
    from iris_agent.jobend import event
    from iris_agent.regression import build
    from iris_agent.run import Session
    thread = "pytest_regression_ermno3"
    P = from_config(cfgmod.load(CFG))
    rd = P.agent_root / "test_runs" / thread
    if rd.exists():
        shutil.rmtree(rd)
    with Session(CFG, thread) as s:
        res = s.start()
        while res["status"] == "waiting_on_jobs":
            res = s.resume(event())
    assert res["status"] == "completed", res
    log = [json.loads(x) for x in (rd / "audit.jsonl").read_text().splitlines()]
    assert not [r for r in log if r["kind"] == "fix"]                     # no gate failure, no human
    out, _, _ = build(str(CFG), thread)
    rows = {r["quantity"]: r for r in out["rows"]}
    assert out["skeptic"]["n_ok"] == out["skeptic"]["n_numbers"]
    assert rows["frames matched to stored structures"]["iris"] == 236
    for k in ("a", "b", "c", "a_P", "g", "g'"):                           # published row from the stored labels
        assert rows[f"{k} (A_s) from the stored labels vs paper"]["paper_ok"], k
    for q in ("fit nodes in window", "K3 well Q* (Å, A_s)", "coupled minimum Q (Å, A_s)", "coupled minimum P (Å, A_s)",
              "hat height (meV/cell)", "well depth (meV/cell)"):
        assert rows[q]["paper_ok"], q
