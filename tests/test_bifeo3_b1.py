"""BiFeO3 stages B1-B4 (one run to the end).
B1: decomposition from the stored ISODISTORT run and the six single-component vectors, compared with the stored
6D grid basis (bfo6d). B2: the six-component plan (orbits, contact cut, controls, refine planes, extra points)
compared with the stored campaign packages. B3: every frame matched to its stored POSCAR, energies, gradients
and QC from the collected CSVs, checked by symmetry (controls), refine-on-node, Simpson line integrals. B4: the
degree-12 invariant fit (work/refit.py procedure), stationary points, f6 re-derivation, regression. Needs the real repo data; configs/bifeo3.yaml or $IRIS_BIFEO3_CONFIG."""
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from iris_agent import config as cfgmod
from iris_agent.paths import from_config

from .conftest import AGENT

CFG = Path(os.environ.get("IRIS_BIFEO3_CONFIG", AGENT / "configs" / "bifeo3.yaml"))


def _available():
    try:
        P = from_config(cfgmod.load(CFG))
        cfg = cfgmod.load(CFG)
        return (P.repo("isodistort_stored") / "modes_details.txt").is_file() and (P.repo("grid_toolkit") / "basis.py").is_file() \
            and all((P.repo_root / p).is_file() for p in cfg["paths"]["grid_packages"]) \
            and (P.repo("collected_dir") / "runs_main_V1.csv").is_file() and P.repo("reference_fit").is_file()
    except Exception:
        return False


@pytest.mark.skipif(not _available(), reason="BiFeO3 reference data not present")
def test_bifeo3_b1_components():
    from langgraph.checkpoint.sqlite import SqliteSaver

    from iris_agent.jobend import event
    from iris_agent.run import Session
    thread = "pytest_bifeo3_b1"
    P = from_config(cfgmod.load(CFG))
    rd = P.agent_root / "test_runs" / thread
    if rd.exists():
        shutil.rmtree(rd)
    with Session(CFG, thread) as s:
        res = s.start()
        while res["status"] == "waiting_on_jobs":
            res = s.resume(event())
    assert res["status"] == "completed" and res["last_node"] == "f6", res
    conn = sqlite3.connect(str(rd / "iris.sqlite"))
    cv = SqliteSaver(conn).get_tuple({"configurable": {"thread_id": thread}}).checkpoint["channel_values"]
    d, grid, jobs, en, model, rep = (cv[k] for k in ("decomposition", "grid", "jobs", "energies", "model", "report"))
    conn.close()
    assert d["isodistort"]["det_basis"] == 6 and d["isodistort"]["s"] == 2       # R3c on hexagonal axes
    assert d["vectors"]["n_parent_primitive_cells"] == 6
    c, g = d["components"], d["components"]["grid"]
    assert c["component_Ap"][0] == pytest.approx(0.30380, abs=2e-5)
    assert c["component_Ap"][3] == pytest.approx(0.40076, abs=2e-5)
    w = c["composition_unit_fu"]["P1"]
    assert (w["A"], w["B"], w["O_par"], w["O_perp"]) == pytest.approx((0.79429, 0.11973, -0.07913, -0.41744), abs=1e-4)
    assert g["matrices_equal_grid_toolkit"] and g["closure_distinct"] == 96
    assert max(g["fold_residual_A"]) < 2e-5
    assert [round(x) for x in g["child_node"]] == [2, 2, 2, 2, 2, 2]
    assert [round(x) for x in (abs(q) / q for q in g["child_q_isodistort_domain"])] == [1, -1, -1, -1, 1, 1]
    assert g["sign_from_convention"] == [1, -1, -1, -1, 1, 1] and g["vectors_vs_grid_max_A"] < 1e-4
    # B2
    ds = {x["name"]: x for x in grid["datasets"]}
    assert (ds["main_V1"]["n_orbits"], ds["main_V1"]["n_orbits_included"]) == (9998, 6724)
    assert (ds["main_V0"]["n_orbits"], ds["main_V0"]["n_orbits_included"]) == (3306, 2873)
    for x in ds.values():
        assert x["burnside"] == x["n_orbits"] and all(x["stored"][k] for k in
                                                       ("reps_equal", "mult_equal", "node_orbit_equal", "included_equal"))
    assert grid["n_by_role"] == {"control_img": 96, "fill": 200, "mep": 25, "origin": 1, "plane_check": 27,
                                 "production": 9597, "refine": 361}
    assert grid["n_sg_mismatch"] == 0 and grid["planes"]["skipped"] == 10
    # B3
    assert jobs["n_matched"] == jobs["n_frames"] == 10307 and not jobs["unmatched"]
    assert jobs["max_dev_A"] < 1e-4 and jobs["max_outside_span_A"] < 1e-4 and len(jobs["stored_input_sets"]) == 1
    assert en["n"] == 10307 and en["n_gradients"] == 10287 and en["n_scf_limited"] == 20
    assert en["controls"]["n"] == 95 and en["controls"]["max_dE_meV"] < 0.002 and en["controls"]["max_dgrad"] < 0.11
    assert en["refine_on_main"]["n"] == 87 and en["refine_on_main"]["max_dE_meV"] < 0.006
    assert abs(en["line_integral"]["slope"] - 1) < 1e-3 and en["line_integral"]["rms_meV"] < 0.5
    assert en["E_csv_max_dev_meV"] < 1e-6 and en["n_sg_mismatch"] == 0
    # B4
    assert model["n_invariants"] == 315 and model["n_fit"] == 4482
    assert model["vs_stored_coef"]["stored_labels_max_rel_diff"] < 1e-9 and model["vs_stored_coef"]["max_rel_diff"] < 1e-4
    assert round(model["tests"]["final scheme: hold-out"]["rms_meV"], 2) == 0.51
    assert round(model["stationary"]["R3c"]["E_meV"], 1) == -950.0 and model["stationary"]["R3c"]["index"] == 0
    assert rep["n_ok"] == rep["n_numbers"]
    v0 = model["secondary"]["V0"]
    assert v0["iris"]["training"]["n"] == 2210 and round(v0["iris"]["training"]["rms_meV"], 3) == 0.283
    assert round(v0["iris"]["stationary"]["R3c"]["E_meV"], 1) == -833.6 and v0["vs_stored_coef"]["stored_labels_max_rel_diff"] < 1e-9
    from iris_agent.regression import build
    out, _, _ = build(str(CFG), thread)
    assert all(r["paper_ok"] is not False and r["stored_ok"] is not False for r in out["rows"]), \
        [r for r in out["rows"] if r["paper_ok"] is False or r["stored_ok"] is False]
    events = [json.loads(x) for x in (rd / "audit.jsonl").read_text().splitlines()]
    assert events[-1]["status"] == "completed"
