"""f3 replay matching for the six-component grid (engines/replay6). Called by f3_runner; the job book, the
wait and the collect step are f3_runner's own. Frames are keyed by their position in grid["frames"]."""
from __future__ import annotations

import numpy as np

from ..engines.replay6 import compare, parse_poscar, run_name, settings_hash
from ..engines.tarstore import open_store
from .f2_grid6 import Cell


def stored_prefix(cfg: dict, dataset: str) -> str:
    six = cfg["policy"]["grid"]["six"]
    for d in six["datasets"]:
        if d["name"] == dataset:
            return d["stored"]
    if six.get("planes") and any(p["dataset"] == dataset for p in six["planes"]["sets"].values()):
        return six["planes"]["stored"]
    if six.get("extra") and six["extra"]["name"] == dataset:
        return six["extra"]["stored"]
    raise KeyError(dataset)


def match6(state: dict, P, tol_A: float, hidden=()) -> dict:
    cfg, grid = state["config"], state["grid"]
    cg = state["decomposition"]["components"]["grid"]
    store = open_store([str(P.repo_root / p) for p in cfg["paths"]["grid_packages"]])
    cells = {}
    matched, unmatched, hashes = {}, [], {}
    worst = {"dev_A": 0.0, "dq_A": 0.0, "outside_span_A": 0.0}
    for i, fr in enumerate(grid["frames"]):
        folder, _ = run_name(fr)
        base = f"{stored_prefix(cfg, fr['dataset'])}/{folder}"
        if fr["id"] in hidden or f"{base}/POSCAR" not in store.data:
            unmatched.append({"id": fr["id"], "why": "no stored POSCAR"})
            continue
        cell = cells.setdefault(fr["a_c"], Cell(cg, fr["a_c"]))
        c = compare(cell, fr["q_A"], *parse_poscar(store.text(f"{base}/POSCAR")))
        if not c["ok"] or c["dev_A"] > tol_A or c["dq_A"] > tol_A or c["outside_span_A"] > tol_A:
            unmatched.append({"id": fr["id"], **{k: v for k, v in c.items() if k != "q_recovered"}})
            continue
        for k in worst:
            worst[k] = max(worst[k], c[k])
        h = settings_hash(store.text(f"{base}/INCAR") if f"{base}/INCAR" in store.data else None,
                          store.text(f"{base}/KPOINTS") if f"{base}/KPOINTS" in store.data else None)
        key = f"INCAR {h.get('INCAR')} / KPOINTS {h.get('KPOINTS')}"
        hashes[key] = hashes.get(key, 0) + 1
        matched[str(i)] = {"frame_id": fr["id"], "stored_id": base, "dev_A": c["dev_A"], "dq_A": c["dq_A"],
                           "energy_eV": None}
    return {"matched": matched, "unmatched": unmatched, "max_dev_frac": worst["dev_A"], "tolerance_frac": tol_A,
            "max_dev_A": worst["dev_A"], "max_dq_A": worst["dq_A"], "max_outside_span_A": worst["outside_span_A"],
            "origin_dev_frac": 0.0, "stored_input_sets": hashes, "label_scale": 1.0, "modulo_translation": False,
            "max_rigid_shift_A": 0.0, "reference_grid": ", ".join(cfg["paths"]["grid_packages"]),
            "energies_csv": cfg["paths"].get("collected_dir"), "extra_references": {}}
