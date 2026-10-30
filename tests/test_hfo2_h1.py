"""HfO2 paths, stages H1-H3 (run to f6): decomposition of the five transitions from the stored ISODISTORT runs vs
the certified Paper 1 values (configs/hfo2_reference.yaml), the 10 path frames vs the stored path.json (H2), and the
replayed energies, barrier, end energy, cross-setting and closure checks vs the runbook table (H3). Configs
configs/hfo2_T<n>.yaml or $IRIS_HFO2_CONFIG_DIR/hfo2_T<n>.yaml."""
import os
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml

from iris_agent import config as cfgmod
from iris_agent.paths import from_config

from .conftest import AGENT

DIR = Path(os.environ.get("IRIS_HFO2_CONFIG_DIR", AGENT / "configs"))
REF = yaml.safe_load((AGENT / "configs" / "hfo2_reference.yaml").read_text())["transitions"]


def _available(t):
    try:
        P = from_config(cfgmod.load(DIR / f"hfo2_{t}.yaml"))
        return (P.repo("isodistort_stored") / "modes_details.txt").is_file()
    except Exception:
        return False


@pytest.mark.parametrize("t", ["T1", "T2", "T3", "T4", "T5"])
def test_hfo2_h1_decomposition(t):
    if not _available(t):
        pytest.skip("HfO2 runs not present")
    from langgraph.checkpoint.sqlite import SqliteSaver

    from iris_agent.jobend import event
    from iris_agent.run import Session
    cfgp = DIR / f"hfo2_{t}.yaml"
    thread = f"pytest_hfo2_h1_{t}"
    P = from_config(cfgmod.load(cfgp))
    rd = P.agent_root / "test_runs" / thread
    if rd.exists():
        shutil.rmtree(rd)
    with Session(cfgp, thread) as s:
        res = s.start()
        while res["status"] == "waiting_on_jobs":
            res = s.resume(event())
    assert res["status"] == "completed" and res["last_node"] == "f6", res
    cv = SqliteSaver(sqlite3.connect(str(rd / "iris.sqlite"))).get_tuple({"configurable": {"thread_id": thread}}).checkpoint["channel_values"]
    d, g = cv["decomposition"], cv["grid"]
    r = REF[t]
    for ir, v in r["Ap"].items():
        assert d["irreps"][ir]["Ap"] == pytest.approx(v, abs=6e-5), ir
    for ir, v in (r.get("Ap_tf") or {}).items():
        assert d["irreps"][ir]["Ap_tf"] == pytest.approx(v, abs=2e-4), ir
    for ir, comps in r["strain"].items():
        got = [x["amplitude"] for x in d["strain_components"][ir]]
        assert got[-len(comps):] == pytest.approx(comps, abs=6e-4), ir
    csg = int(cfgmod.load(cfgp)["expected"]["child_sg"])
    assert set(d["spacegroups"].values()) == {csg}
    # H2
    assert g["kind"] == "path" and g["n_frames"] == 10 and set(g["active"]) == set(r["Ap"])
    assert [f["sg"] for f in g["frames"]][1:] == [csg] * 9 and g["child_match_rms"][0] < 1e-4
    assert g["stored"]["Ap_max_dev_A"] < 2e-4 and g["stored"]["lattice_max_dev_A"] < 1e-5
    rot = g["lattice"]["rigid_rotation_deg"]
    assert (rot == pytest.approx(4.9, abs=0.2)) if t in ("T3", "T5") else rot < 1e-3
    # H3
    j, e, m, rep = cv["jobs"], cv["energies"], cv["model"], cv["report"]
    assert j["n_matched"] == 10 and j["max_dev_A"] < 2e-4 and len(j["stored_input_sets"]) == 1
    assert e["n"] == 10 and not e["flagged"] and max(e["rederive_dev"].values()) <= 6e-4
    b, lb = r["barrier"]
    assert m["barrier_meV"] == pytest.approx(b, abs=0.005) and m["barrier_lambda"] == pytest.approx(lb, abs=6e-4)
    assert m["dE_end_meV"] == pytest.approx(r["dE_end"], abs=0.005)
    net = m["network"]
    assert all(n >= 1 for n in net["n_partners"].values())
    assert all(abs(c["diff_meV"]) <= 0.05 for c in net["cross_setting"])
    ref_cl = yaml.safe_load((AGENT / "configs" / "hfo2_reference.yaml").read_text()).get("closure", {})
    assert len(net["closure"]) == (1 if t in ref_cl else 0)
    for c in net["closure"]:
        assert c["connected"] and c["sum_meV"] == pytest.approx(ref_cl[t][0], abs=0.005)
        assert abs(c["gap_meV"]) <= 0.0605
    assert rep["n_ok"] == rep["n_numbers"] >= 60
    assert [h["code"] for h in cv["history"] if "gate" in h] == ["OK"] * 7


def test_hfo2_h3_gates_catch_faults():
    """The H3 path gates fail on planted defects (state copies of a completed T1 run; nothing is recomputed)."""
    import copy

    if not _available("T1"):
        pytest.skip("HfO2 runs not present")
    from langgraph.checkpoint.sqlite import SqliteSaver

    from iris_agent.gates import run_gate
    from iris_agent.jobend import event
    from iris_agent.run import Session
    cfgp = DIR / "hfo2_T1.yaml"
    thread = "pytest_hfo2_h3_faults"
    rd = from_config(cfgmod.load(cfgp)).agent_root / "test_runs" / thread
    if rd.exists():
        shutil.rmtree(rd)
    with Session(cfgp, thread) as s:
        res = s.start()
        while res["status"] == "waiting_on_jobs":
            res = s.resume(event())
    assert res["status"] == "completed"
    cv = SqliteSaver(sqlite3.connect(str(rd / "iris.sqlite"))).get_tuple({"configurable": {"thread_id": thread}}).checkpoint["channel_values"]

    def gate(g, f):
        st = copy.deepcopy(cv)
        f(st)
        return run_gate(g, st)["code"]
    assert gate("G4", lambda st: None) == "OK" and gate("G5", lambda st: None) == "OK"
    assert gate("G3", lambda st: st["jobs"].update(n_matched=9, unmatched=[{"id": 4}])) == "UNMATCHED"
    assert gate("G4", lambda st: st["energies"]["flagged"].append({"id": 3, "code": "NOT_CONVERGED", "reason": "x"})
                or st["energies"].update(n=9)) == "NOT_CONVERGED"
    assert gate("G4", lambda st: st["energies"]["rederive_dev"].update(dE_vs_csv_meV=0.01)) == "ENERGY_MISMATCH"
    assert gate("G4", lambda st: st["energies"].update(per_fu_from_composition=2)) == "PER_FU"
    assert gate("G4", lambda st: st["energies"].update(max_abs_mag_muB=0.5)) == "MAGNETIC"
    assert gate("G4", lambda st: st["energies"]["stored_input_sets"].update({"INCAR x / KPOINTS y": 1})) == "DFT_INCONSISTENT"
    assert gate("G4", lambda st: st["energies"].update(potcar_sets=["NOT SET"])) == "DFT_INCONSISTENT"
    assert gate("G5", lambda st: st["model"]["network"]["cross_setting"][0].update(diff_meV=0.5)) == "CROSS_SETTING"
    assert gate("G5", lambda st: st["model"]["network"]["closure"][0].update(gap_meV=0.3)) == "CLOSURE"
    assert gate("G5", lambda st: st["model"]["network"]["closure"][0].update(connected=False)) == "CLOSURE"
