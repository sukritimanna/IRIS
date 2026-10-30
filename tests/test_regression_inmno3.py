"""InMnO3 (K3, GM2-) plane replay, stage 1: R5 decided by a (scripted) human at run time, f3 job wait,
Meier-form (Q, P) fit. Needs the real repo data; config configs/inmno3.yaml or $IRIS_INMNO3_CONFIG."""
import json
import os
import shutil
from pathlib import Path

import pytest

from iris_agent import config as cfgmod
from iris_agent.paths import from_config

from .conftest import AGENT

CFG = Path(os.environ.get("IRIS_INMNO3_CONFIG", AGENT / "configs" / "inmno3.yaml"))


def _available():
    try:
        P = from_config(cfgmod.load(CFG))
        g = P.repo("reference_grid")
        return (g / "grid_manifest.json").is_file() and any((g / "03_grid").glob("*/point_*/POSCAR")) \
            and P.repo("energies_csv").is_file()
    except Exception:
        return False


@pytest.mark.skipif(not _available(), reason="InMnO3 reference data not present")
def test_inmno3_plane_replay_r5_human_and_meier_fit():
    from iris_agent.jobend import event
    from iris_agent.regression import build
    from iris_agent.run import Session
    thread = "pytest_regression_inmno3"
    P = from_config(cfgmod.load(CFG))
    rd = P.agent_root / "test_runs" / thread
    if rd.exists():
        shutil.rmtree(rd)
    with Session(CFG, thread) as s:
        res = s.start()
        assert res["status"] == "interrupted" and res["interrupt"][0]["code"] == "R5_BORDERLINE"
        res = s.resume({"option": "include_borderline"})
        while res["status"] == "waiting_on_jobs":
            res = s.resume(event())
    assert res["status"] == "completed", res
    log = [json.loads(x) for x in (rd / "audit.jsonl").read_text().splitlines()]
    fx = [r for r in log if r["kind"] == "fix"]
    assert [(r["recovery_tier"], r["gate_code"], r["option_id"]) for r in fx] == [("human", "R5_BORDERLINE", "include_borderline")]
    out, _, _ = build(str(CFG), thread)
    rows = {r["quantity"]: r for r in out["rows"]}
    assert out["skeptic"]["n_ok"] == out["skeptic"]["n_numbers"]
    assert rows["primaries"]["iris"] == ["K3"] and rows["active set (axes)"]["iris"] == ["K3", "GM2-"]
    assert rows["frames matched to stored structures"]["iris"] == 225
    assert rows["refit on the stored 4-dp labels: max |Δcoef| vs stored fit (A_p)"]["stored_ok"]
    for q in ("a (A_s, eV/cell)", "g (A_s, eV/cell)", "fit RMS (meV/cell)", "K3 well Q* (Å, A_s)",
              "coupled minimum Q (Å, A_s)", "hat height (meV/cell)"):
        assert rows[q]["paper_ok"], q
