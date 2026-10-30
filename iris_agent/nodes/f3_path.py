"""f3 replay matching for a straight-line path (grid kind "path", nodes/f2_path.py; HfO2 H3). Called by f3_runner;
the job book, the wait and the collect step are f3_runner's own.

Frame k is matched to the stored point <policy.path.stored>/L<kk>/POSCAR: same species order, lattice within
tol_lattice_A, every atom within tol_A (minimum image, Cartesian). The energy and the run record come from that
point's result.json (written by demo/hfo2/collect_paths.py from OSZICAR/OUTCAR on Perlmutter); nothing is computed.
"""
from __future__ import annotations

import json

import numpy as np

from ..engines.frames import frame_frac
from ..engines.replay6 import settings_hash

RESULT_KEYS = ("finished", "converged", "E0_eV", "F_eV", "E0_per_fu_eV", "dE_meV_per_fu", "mag", "mag_outcar",
               "scf_steps", "last_dE", "EDIFF", "NELM", "potcar", "space_group", "flags", "lambda")


def _poscar(text: str):
    L = text.splitlines()
    scale = float(L[1].split()[0])
    lat = np.array([[float(x) for x in L[i].split()[:3]] for i in (2, 3, 4)]) * scale
    names, counts = L[5].split(), [int(x) for x in L[6].split()]
    i = 7
    if L[i].strip()[0] in "sS":
        i += 1
    direct = L[i].strip()[0] in "dD"
    n = sum(counts)
    xyz = np.array([[float(x) for x in L[i + 1 + k].split()[:3]] for k in range(n)])
    frac = xyz if direct else xyz @ np.linalg.inv(lat)
    species = [s for s, c in zip(names, counts) for _ in range(c)]
    return lat, species, frac


def match_path(state: dict, P, tol_A: float, tol_lattice_A: float, hidden=()) -> dict:
    cfg, grid = state["config"], state["grid"]
    from ._layout import grid_policy
    root = P.repo_root / grid_policy(cfg["policy"])["stored"]
    r0 = state["decomposition"]["vectors"]["r0"]
    f0 = np.array(r0["frac"])
    vec = {ir: np.array(v) for ir, v in grid["vectors"].items()}
    matched, unmatched, hashes = {}, [], {}
    worst = {"dev_A": 0.0, "lattice_A": 0.0}
    for fr in grid["frames"]:
        d = root / fr["name"]
        if fr["id"] in hidden or not (d / "POSCAR").is_file():
            unmatched.append({"id": fr["id"], "name": fr["name"], "why": "no stored POSCAR"})
            continue
        lat, species, frac = _poscar((d / "POSCAR").read_text())
        L = np.array(fr["lattice"])
        if species != list(r0["species"]):
            unmatched.append({"id": fr["id"], "name": fr["name"], "why": "species order differs"})
            continue
        df = frac - frame_frac(fr, f0, vec, grid["active"])
        df -= np.round(df)
        dev, dl = float(np.linalg.norm(df @ L, axis=1).max()), float(np.abs(lat - L).max())
        if dev > tol_A or dl > tol_lattice_A:
            unmatched.append({"id": fr["id"], "name": fr["name"], "dev_A": dev, "lattice_dev_A": dl})
            continue
        worst["dev_A"], worst["lattice_A"] = max(worst["dev_A"], dev), max(worst["lattice_A"], dl)
        res = json.loads((d / "result.json").read_text()) if (d / "result.json").is_file() else {}
        h = settings_hash((d / "INCAR").read_text() if (d / "INCAR").is_file() else None,
                          (d / "KPOINTS").read_text() if (d / "KPOINTS").is_file() else None)
        key = f"INCAR {h.get('INCAR')} / KPOINTS {h.get('KPOINTS')}"
        hashes[key] = hashes.get(key, 0) + 1
        matched[str(fr["id"])] = {"stored_id": str(d.relative_to(P.repo_root)), "dev_A": dev, "lattice_dev_A": dl,
                                  "energy_eV": res.get("E0_eV") if res.get("finished") else None,
                                  "result": {k: res.get(k) for k in RESULT_KEYS}}
    return {"matched": matched, "unmatched": unmatched, "max_dev_frac": worst["dev_A"], "tolerance_frac": tol_A,
            "max_dev_A": worst["dev_A"], "max_lattice_dev_A": worst["lattice_A"], "origin_dev_frac": 0.0,
            "stored_input_sets": hashes, "label_scale": 1.0, "modulo_translation": False, "max_rigid_shift_A": 0.0,
            "reference_grid": str(root), "energies_csv": str(root / "L*/result.json"), "extra_references": {}}
