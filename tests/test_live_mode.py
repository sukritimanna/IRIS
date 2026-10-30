"""Live mode (run.mode live) end to end with a fake scheduler and a fake VASP: no stored data, no network.

Synthetic BaTiO3 Pm-3m -> P4mm (one displacive irrep GM4-); f1 is replaced by a synthetic decomposition (live
ISODISTORT is exercised by test_live_isodistort when iris/lib is present) and G1 is ablated. The rest is the real
graph: f0 G0, f2_path G2, f3 live (inputs + wait), the live executor (fake qsub/qstat, fake vasp), f4 G4, f5 G5,
f6 G6, and the recovery rules for WALLTIME (resubmit the unfinished frames) and NELM (resubmit every point with
robust mixing, recovery_live.yaml).
"""
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

AGENT = Path(__file__).resolve().parents[1]
FAKES = AGENT / "tests" / "live_fakes"
sys.path.insert(0, str(AGENT))

SPECIES = ["Ba", "Ti", "O", "O", "O"]
F0 = np.array([[0, 0, 0], [.5, .5, .5], [.5, .5, 0], [.5, 0, .5], [0, .5, .5]], float)
D = np.array([[0, 0, 0], [0, 0, 0.015], [0, 0, -0.025], [0, 0, -0.015], [0, 0, -0.015]])
L0 = np.diag([4.0, 4.0, 4.0])
L1 = np.diag([4.0 * 0.997, 4.0 * 0.997, 4.0 * 1.012])


def fake_f1(state):
    dd = D - D.mean(axis=0)
    norm = float(np.linalg.norm(dd @ L0))
    dec = {"standardize": {"ladders": {}, "findsym_stored": {}},
           "subgroup": {"parent_sg": 221, "child_sg": 99, "t_index": 6, "is_true_subgroup": True},
           "isodistort": {"sg": 99, "i": 6, "s": 1, "det_basis": 1, "max_displacement_A": 0.1},
           "basis_search": {"skipped": True},
           "irreps": {"GM4-": {"Ap": norm, "As": norm, "As_tf": norm, "Ap_tf": norm, "kind": "displacive"}},
           "strain": {"GM1+": 0.004, "GM3+": 0.01}, "strain_components": {}, "overall": {},
           "tree": {"parent": 221, "child": 99, "chain": [{"sg": 221, "i": 1, "order_parameters": ""},
                                                          {"sg": 99, "i": 6, "order_parameters": "GM4-,GM1+,GM3+"}]},
           "spacegroups": {"isodistort_subgroup": 99, "spglib_child_cif": 99, "spglib_rebuilt_decomposition": 99},
           "vectors": {"r0": {"lattice": L0.tolist(), "species": SPECIES, "frac": F0.tolist()},
                       "child_fields_frac": {"GM4-": D.tolist()}, "norm_A": {"GM4-": norm},
                       "n_parent_primitive_cells": 1, "parent_primitive_atoms": 5, "mode_ids": {}},
           "source": "synthetic (test)"}
    return {"decomposition": dec, "last_node": "f1"}


@pytest.fixture
def live_repo(tmp_path, monkeypatch):
    from pymatgen.core import Lattice, Structure
    from pymatgen.io.cif import CifWriter
    repo = tmp_path / "repo"
    aroot = repo / "IRIS_AGENT"
    (aroot / "test_runs").mkdir(parents=True)
    shutil.copy(AGENT / "recovery.yaml", aroot / "recovery.yaml")
    shutil.copy(AGENT / "recovery_live.yaml", aroot / "recovery_live.yaml")
    (repo / "structures").mkdir()
    CifWriter(Structure(Lattice(L0), SPECIES, F0)).write_file(repo / "structures" / "parent.cif")
    CifWriter(Structure(Lattice(L1), SPECIES, F0 + D)).write_file(repo / "structures" / "child.cif")
    (repo / "structures" / "batio3.json").write_text(json.dumps({"name": "batio3", "composition": {"Ba": 1, "Ti": 1, "O": 3}}))
    fakeq = tmp_path / "fakeq"
    fakeq.mkdir()
    monkeypatch.setenv("FAKEQ", str(fakeq))
    monkeypatch.delenv("FAKE_FAIL", raising=False)
    monkeypatch.delenv("FAKE_FAIL_POINTS", raising=False)
    import iris_agent.nodes as N
    import iris_agent.graph as G
    monkeypatch.setitem(N.FUNCS, "f1", fake_f1)
    monkeypatch.setattr(G, "FUNCS", N.FUNCS)
    return repo


def live_config(repo: Path, case: str) -> Path:
    cfg = yaml.safe_load((AGENT / "configs" / "live" / "_template_live.yaml").read_text())
    cfg.update({"system": "batio3", "thread_id": f"batio3_live_{case}", "request": "BaTiO3 #221 -> #99 live path"})
    cfg["paths"].update({"repo_root": str(repo), "agent_root": str(repo / "IRIS_AGENT"), "parent_cif": "structures/parent.cif",
                         "child_cif": "structures/child.cif", "system_json": "structures/batio3.json"})
    cfg["paths"].pop("walkthrough", None)
    cfg["paths"].pop("isodistort_live", None)
    cfg["expected"] = {"parent_sg": 221, "child_sg": 99}
    cfg["run"]["live"].update({"submit_cmd": str(FAKES / "fake_qsub"), "queue_cmd": str(FAKES / "fake_qstat"),
                               "vasp_cmd": str(FAKES / "fake_vasp"), "potcar_dir": str(FAKES / "potpaw_el"), "poll_s": 5,
                               "job_header": "#!/bin/bash\n# fake header {job_name}\n"})
    cfg["run"]["live"]["incar"]["NELM"] = 100
    cfg["policy"]["path"].update({"stored": "{run}/live/T1_221-99__lin10", "collected": "{run}/live"})
    cfg["policy"]["path"].pop("network", None)
    cfg["policy"]["fit"]["per_fu"] = 1
    p = repo / "IRIS_AGENT" / f"live_{case}.yaml"
    p.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return p


def run_case(repo: Path, case: str):
    from iris_agent.live_executor import Executor
    from iris_agent.run import Session
    cfg_path = live_config(repo, case)
    thread = f"batio3_live_{case}"
    with Session(cfg_path, thread, mode="live", ablations=["no-g1"], fresh=True) as s:
        out = s.start()
    assert out["status"] == "waiting_on_jobs", out
    ex = Executor(str(cfg_path), thread, log=lambda m: None)
    for _ in range(200):
        ex.step()
        st = ex.thread_status()
        if not st["next"] and not st["interrupts"]:
            break
        if st["interrupts"] and not any(isinstance(i, dict) and i.get("kind") == "job_wait" for i in st["interrupts"]):
            break
        import time
        time.sleep(0.3)
    run = repo / "IRIS_AGENT" / "test_runs" / thread
    aud = [json.loads(x) for x in (run / "audit.jsonl").read_text().splitlines()]
    return st, run, aud


def gate_codes(aud):
    return [(e["gate"], e["gate_code"]) for e in aud if e.get("kind") == "gate"]


def test_live_normal(live_repo):
    st, run, aud = run_case(live_repo, "normal")
    assert st["last_node"] == "f6" and st["gate"]["ok"]
    assert gate_codes(aud)[-4:] == [("G3", "OK"), ("G4", "OK"), ("G5", "OK"), ("G6", "OK")]
    rows = (run / "live" / "energies.csv").read_text().splitlines()
    assert len(rows) == 11 and rows[0].startswith("path,point,lambda,E0_eV,E0_per_fu_eV")
    summ = json.loads((run / "live" / "energies_summary.json").read_text())["paths"]["T1_221-99__lin10"]
    assert summ["n_points"] == 10 and summ["barrier_meV_per_fu"] > 0
    for k in range(10):
        d = run / "live" / "T1_221-99__lin10" / f"L{k:02d}"
        assert all((d / f).is_file() for f in ("POSCAR", "INCAR", "KPOINTS", "POTCAR", "OSZICAR", "OUTCAR", "result.json"))
    from iris_agent.engines import kpoints_utilities as KU
    k0 = run / "live" / "T1_221-99__lin10" / "L00"
    assert KU.checkKpoints(str(k0 / "POSCAR"), str(k0 / "KPOINTS"), 0.20) == [8, 8, 8]      # a = 4 A: 2pi/4/0.2 = 7.85 -> 8
    assert (run / "live" / "T1_221-99__lin10" / "L09" / "KPOINTS").read_text() == (k0 / "KPOINTS").read_text()
    pot = (k0 / "POTCAR").read_text()
    assert [ln.split("=")[1].split()[0] for ln in pot.splitlines() if "TITEL" in ln] == ["PAW_PBE", "PAW_PBE", "PAW_PBE"]
    assert not (run / "live" / "T1_221-99__lin10" / "path.json").exists()     # nothing stored was read or written


def test_live_walltime_resubmits_unfinished_frames(live_repo, monkeypatch):
    monkeypatch.setenv("FAKE_FAIL", "kill")
    monkeypatch.setenv("FAKE_FAIL_POINTS", "L04")
    st, run, aud = run_case(live_repo, "walltime")
    assert st["last_node"] == "f6" and st["gate"]["ok"]
    assert ("G4", "WALLTIME") in gate_codes(aud)
    fixes = [e["rule"] for e in aud if e.get("kind") == "fix"]
    assert fixes == ["f4_walltime_resubmit"]
    assert (run / "f3_jobs" / "submission_r1.json").is_file()
    assert (run / "live" / "T1_221-99__lin10" / "L04" / "attempt_r0").is_dir()
    sub1 = json.loads((run / "f3_jobs" / "submission_r1.json").read_text())
    assert sub1["resubmitted_parts"] == [0] and not sub1["rerun_all"]


def test_live_nelm_robust_mixing_whole_path(live_repo, monkeypatch):
    monkeypatch.setenv("FAKE_FAIL", "nelm")
    monkeypatch.setenv("FAKE_FAIL_POINTS", "L07")
    st, run, aud = run_case(live_repo, "nelm")
    assert st["last_node"] == "f6" and st["gate"]["ok"]
    codes = gate_codes(aud)
    assert ("G4", "NELM") in codes and ("G4", "DFT_INCONSISTENT") not in codes
    assert [e["rule"] for e in aud if e.get("kind") == "fix"] == ["f4_nelm_robust_mixing_all"]
    sub1 = json.loads((run / "f3_jobs" / "submission_r1.json").read_text())
    assert sub1["rerun_all"] and sub1["incar_patch"]["NELM"] == 300
    for k in range(10):
        assert "AMIX" in (run / "live" / "T1_221-99__lin10" / f"L{k:02d}" / "INCAR").read_text()


def plane_config(repo: Path, case: str) -> Path:
    cfg = yaml.safe_load(live_config(repo, case).read_text())
    cfg["policy"].pop("path")
    cfg["policy"]["analysis"] = "plane2"
    cfg["policy"]["strain_policy"] = "P1"
    cfg["policy"]["plane2"] = {"irrep": "GM4-", "levels": 5, "q_max": 1.2, "stored": "{run}/live/PL_221-99__9x9",
                               "collected": "{run}/live"}
    p = repo / "IRIS_AGENT" / f"plane_{case}.yaml"
    p.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return p


def test_live_plane2(live_repo):
    from iris_agent.live_executor import Executor
    from iris_agent.run import Session
    cfg_path = plane_config(live_repo, "plane")
    thread = "batio3_live_plane"
    with Session(cfg_path, thread, mode="live", ablations=["no-g1"], fresh=True) as s:
        out = s.start()
    assert out["status"] == "waiting_on_jobs", out
    ex = Executor(str(cfg_path), thread, log=lambda m: None)
    import time
    for _ in range(200):
        ex.step()
        st = ex.thread_status()
        if not st["next"] and not st["interrupts"]:
            break
        if st["interrupts"] and not any(isinstance(i, dict) and i.get("kind") == "job_wait" for i in st["interrupts"]):
            break
        time.sleep(0.3)
    run = live_repo / "IRIS_AGENT" / "test_runs" / thread
    aud = [json.loads(x) for x in (run / "audit.jsonl").read_text().splitlines()]
    assert st["last_node"] == "f6" and st["gate"]["ok"], (st, [e for e in aud if e.get("kind") == "gate"][-1])
    assert gate_codes(aud)[-4:] == [("G3", "OK"), ("G4", "OK"), ("G5", "OK"), ("G6", "OK")]
    with Session(cfg_path, thread, mode="live") as s:
        v = s.graph.get_state(s.cfg).values
    g, m = v["grid"], v["model"]
    assert g["kind"] == "plane2" and g["n_frames"] == 15 and g["orbits"]["burnside"] == 15 and g["n_grid_points"] == 81
    assert m["kind"] == "plane2" and m["n_full_points"] == 81 and m["rms_meV"] < 0.01       # the fake energy IS the model form
    assert m["minimum"]["where"] == "axis" and m["anisotropy_c_minus_2b"] > 0                 # fake: c = 25000 > 2b = 20000
    assert v["report"]["n_ok"] == v["report"]["n_numbers"]


def test_live_refused_outside_live_mode(live_repo):
    from iris_agent import config as C
    p = live_config(live_repo, "schema")
    cfg = yaml.safe_load(p.read_text())
    cfg["run"]["mode"] = "replay"
    assert any("live submission is disabled" in e for e in C.validate(cfg))
    cfg["run"]["mode"], cfg["run"]["allow_live_submission"] = "live", False
    assert any("run.mode: live needs" in e for e in C.validate(cfg))


def test_plane2_network_gate(tmp_path):
    """The plane's cubic origin must agree per f.u. with lambda = 0 of the campaign's paths (G5 NETWORK)."""
    import csv
    from iris_agent.nodes.f5_plane2 import plane_network
    from iris_agent.gates import g5q_network
    repo = tmp_path
    col = repo / "live_runs" / "c"
    col.mkdir(parents=True)
    with open(col / "energies.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["path", "point", "lambda", "E0_eV", "E0_per_fu_eV", "dE_meV_per_fu", "converged"])
        w.writerow(["T1_221-99__lin10", "L00", "0.0", "-39.605167", "-39.605167000000", "0.000", "True"])
        w.writerow(["T1_221-99__lin10", "L09", "1.0", "-39.637362", "-39.637362000000", "-32.195", "True"])
        w.writerow(["T3_221-38__lin10", "L00", "0.0", "-79.210406", "-39.605203000000", "0.000", "True"])
    cfg = {"paths": {"repo_root": str(repo), "agent_root": str(repo / "IRIS_AGENT")},
           "policy": {"plane2": {"irrep": "GM4-", "stored": "live_runs/c/PL_221-99__21x21", "collected": "live_runs/c"}}}
    pts = [{"name": "P00", "Q": {"GM4-@c1": 0.0, "GM4-@c2": 0.0}, "E0_eV": -39.4035},
           {"name": "P01", "Q": {"GM4-@c1": 0.018, "GM4-@c2": 0.0}, "E0_eV": -39.4041}]
    net = plane_network(cfg, pts, {"per_fu": 1})
    assert net and len(net["others"]) == 2 and abs(net["others"][0]["diff_meV"] - 201.667) < 0.01
    code = g5q_network({"model": {"kind": "plane2", "network": net}})
    assert code and code[0] == "NETWORK"
    pts[0]["E0_eV"] = -39.605200
    net = plane_network(cfg, pts, {"per_fu": 1})
    assert g5q_network({"model": {"kind": "plane2", "network": net}}) is None
    assert plane_network(cfg, pts, {"per_fu": 1}) is not None
    (col / "energies.csv").unlink()
    assert plane_network(cfg, pts, {"per_fu": 1}) is None
