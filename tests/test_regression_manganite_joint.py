"""Stage 2 of the manganite replays: plane (+ P axis) + polar hat wedge, joint Meier fit with c'.
Needs the real repo data; configs configs/{inmno3,ermno3}_joint.yaml or $IRIS_<SYS>_JOINT_CONFIG."""
import os
import shutil
from pathlib import Path

import pytest

from iris_agent import config as cfgmod
from iris_agent.paths import from_config

from .conftest import AGENT


def _cfg(sysname):
    return Path(os.environ.get(f"IRIS_{sysname.upper()}_JOINT_CONFIG", AGENT / "configs" / f"{sysname}_joint.yaml"))


def _available(cfgp):
    try:
        cfg = cfgmod.load(cfgp)
        P = from_config(cfg)
        x = cfg["run"]["replay"]["extra_references"][0]
        return (P.repo("reference_grid") / "grid_manifest.json").is_file() and (P.repo_root / x["grid"] / "03_grid").is_dir() \
            and (P.repo_root / x["energies"]).is_file()
    except Exception:
        return False


@pytest.mark.parametrize("sysname", ["inmno3", "ermno3"])
def test_manganite_joint_plane_and_hat(sysname):
    cfgp = _cfg(sysname)
    if not _available(cfgp):
        pytest.skip(f"{sysname} hat data not present")
    from iris_agent.jobend import event
    from iris_agent.regression import build
    from iris_agent.run import Session
    thread = f"pytest_joint_{sysname}"
    P = from_config(cfgmod.load(cfgp))
    rd = P.agent_root / "test_runs" / thread
    if rd.exists():
        shutil.rmtree(rd)
    with Session(cfgp, thread) as s:
        res = s.start()
        while res["status"] in ("waiting_on_jobs", "interrupted"):
            if res["status"] == "interrupted":
                assert res["interrupt"][0]["code"] == "R5_BORDERLINE"            # InMnO3 only
                res = s.resume({"option": "include_borderline"})
            else:
                res = s.resume(event())
    assert res["status"] == "completed", res
    out, _, _ = build(str(cfgp), thread)
    rows = {r["quantity"]: r for r in out["rows"]}
    assert out["skeptic"]["n_ok"] == out["skeptic"]["n_numbers"]
    assert rows["hat frames (Q x Phi x P)"]["iris"] == 175 and rows["DFT input sets across all frames"]["iris"] == 1
    for k in ("a", "b", "c", "c'", "a_P", "g", "g'"):                       # the published script, reproduced
        assert rows[f"stored labels: {k} (A_s)"]["paper_ok"], k
    assert rows["stored labels: RMS / hat / brim / brim c'=0"]["paper_ok"]
    assert rows["hat height (meV/f.u.)"]["paper_ok"] and rows["joint fit nodes (plane + hat)"]["paper_ok"]
