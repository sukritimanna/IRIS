"""f6 for grid kind plane2: every reported number re-derived independently.

  decomposition   A_p = ||field|| / sqrt(n_cells); e_2 recomputed as the rotation image of e_1 and compared
  orbits          brute-force orbit count of the grid under 4mm vs the Burnside count vs the frames
  frames          space group and d_min of every stored POSCAR recounted
  energies        E0 and dE of every point from energies.csv; the fit refitted from the CSV with numpy's lstsq on
                  the explicit design matrix; minimum re-searched; axis/diagonal minima re-read
"""
from __future__ import annotations

import csv
import json

import numpy as np

from ..paths import from_config
from .f2_path_planner import SYMPREC
from .f2_plane2 import burnside, image_field, orbit_of
from .f3_path import _poscar
from .f5_plane2 import TERMS, design, minimum
from .f6_path import _row


def plane2_report(state: dict) -> dict:
    from pymatgen.core import Composition, Lattice, Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    cfg, dec, grid = state["config"], state["decomposition"], state["grid"]
    jobs, en, model = state["jobs"], state["energies"], state["model"]
    P, pol = from_config(cfg), cfg["policy"]
    pp = pol["plane2"]
    rows = []
    r0 = dec["vectors"]["r0"]
    L0 = np.array(r0["lattice"])
    s0 = Structure(Lattice(L0), r0["species"], r0["frac"])
    n_cells = len(s0) / len(SpacegroupAnalyzer(s0, symprec=1e-3).find_primitive())
    rows.append(_row("parent primitive cells in the frame", dec["vectors"]["n_parent_primitive_cells"], n_cells, 1e-9))
    ir = grid["irrep"]
    d = np.array(dec["vectors"]["child_fields_frac"][ir])
    d = d - d.mean(axis=0)
    ap = float(np.linalg.norm(d @ L0) / np.sqrt(n_cells))
    rows.append(_row(f"A_p {ir} (translation-free)", grid["Ap_child"][ir], ap, 2e-4, "Å"))
    c1, c2 = grid["active"]
    e1 = np.array(grid["vectors"][c1])
    e2, centre = image_field(np.array(r0["frac"]), e1, r0["species"], grid["rotation"], L0)
    rows.append(_row("rotation centre (first atom position that maps the frame onto itself)", grid["rotation_centre"], centre.tolist(), None))
    rows.append(_row("second component = rotation image of the first (max dev, frac)", 0.0,
                     float(np.abs(e2 - np.array(grid["vectors"][c2])).max()), 1e-9))
    rows.append(_row("|e_2| / |e_1|", 1.0, float(np.linalg.norm(e2 @ L0) / np.linalg.norm(e1 @ L0)), 1e-9))
    # orbits
    levels = int(grid["levels"])
    m = levels - 1
    orbits = {orbit_of(a, b) for a in range(-m, m + 1) for b in range(-m, m + 1)}
    rows.append(_row("orbits of the grid under 4mm (brute force)", grid["n_frames"], len(orbits), None))
    rows.append(_row("orbits by Burnside", grid["orbits"]["burnside"], burnside(levels), None))
    rows.append(_row("sum of orbit multiplicities = grid points", grid["n_grid_points"], sum(len(o) for o in orbits), None))
    # frames
    root = P.repo_root / pp["stored"]
    for fr in grid["frames"]:
        lat, sp, frac = _poscar((root / fr["name"] / "POSCAR").read_text())
        s = Structure(Lattice(lat), sp, frac)
        rows.append(_row(f"{fr['name']} space group (stored POSCAR)", fr["sg"],
                         SpacegroupAnalyzer(s, symprec=SYMPREC).get_space_group_number(), None))
        dm = s.distance_matrix + np.eye(len(s)) * 1e9
        rows.append(_row(f"{fr['name']} d_min (Å)", fr["d_min"], round(float(dm.min()), 4), 2e-4, "Å"))
        rows.append(_row(f"{fr['name']} cell = parent cell (max dev, Å)", 0.0, float(np.abs(lat - L0).max()), 1e-6))
    n_fu = int(Composition("".join(sp)).get_reduced_formula_and_factor()[1])
    rows.append(_row("f.u. per cell", en["per_fu"], n_fu, None))
    # energies from the CSV
    pid = pp["stored"].rstrip("/").split("/")[-1]
    with open(P.repo_root / pp["collected"] / "energies.csv") as fh:
        csv_ = {r["point"]: r for r in csv.DictReader(fh) if r["path"] == pid}
    e0 = float(csv_["P00"]["E0_eV"])
    pts = sorted(en["points"], key=lambda q: q["id"])
    q1 = np.array([p["Q"][c1] for p in pts])
    q2 = np.array([p["Q"][c2] for p in pts])
    w = np.array([p.get("multiplicity", 1) for p in pts], float)
    dEc = []
    for p in pts:
        c = csv_[p["name"]]
        rows.append(_row(f"{p['name']} E0 (eV/cell)", p["E0_eV"], float(c["E0_eV"]), 1e-9, "eV"))
        dd = 1000 * (float(c["E0_eV"]) - e0) / n_fu
        dEc.append(dd)
        rows.append(_row(f"{p['name']} dE (meV/f.u.)", round(p["dE_meV"], 3), float(c["dE_meV_per_fu"]), 6e-4, "meV/f.u."))
    dEc = np.array(dEc)
    # refit from the CSV energies
    A = design(q1, q2)
    sw = np.sqrt(w)
    coef, *_ = np.linalg.lstsq(A * sw[:, None], dEc * sw, rcond=None)
    for t, v in zip(TERMS, coef):
        rows.append(_row(f"Landau coefficient {t} (meV/f.u. per Å^n)", model["coefficients"][t], float(v), 1e-6))
    res = dEc - A @ coef
    rows.append(_row("fit rms (meV/f.u.)", model["rms_meV"], float(np.sqrt(np.sum(w * res ** 2) / np.sum(w))), 1e-6))
    mn = minimum(coef, float(grid["q_max_A"]))
    rows.append(_row("fitted minimum Q1 (Å)", model["minimum"]["Q1"], mn["Q1"], 1e-9))
    rows.append(_row("fitted minimum Q2 (Å)", model["minimum"]["Q2"], mn["Q2"], 1e-9))
    rows.append(_row("fitted minimum E (meV/f.u.)", model["minimum"]["E_meV"], mn["E_meV"], 1e-6))
    rows.append(_row("minimum lies on", model["minimum"]["where"], mn["where"], None))
    ax = min(float(csv_[p["name"]]["dE_meV_per_fu"]) for p in pts if abs(p["Q"][c2]) < 1e-12)
    rows.append(_row("lowest computed energy on the axis (meV/f.u.)", round(model["E_axis_min_meV"], 3), ax, 6e-4, "meV/f.u."))
    dg = [float(csv_[p["name"]]["dE_meV_per_fu"]) for p in pts if abs(p["Q"][c1] - p["Q"][c2]) < 1e-12]
    if dg:
        rows.append(_row("lowest computed energy on the diagonal (meV/f.u.)", round(model["E_diag_min_meV"], 3), min(dg), 6e-4, "meV/f.u."))
    net = model.get("network")
    if net:
        e_own = float(csv_["P00"]["E0_eV"]) / n_fu
        with open(P.repo_root / pp["collected"] / "energies.csv") as fh:
            l0 = {r["path"]: float(r["E0_per_fu_eV"]) for r in csv.DictReader(fh)
                  if r["path"] != pid and r.get("lambda") and abs(float(r["lambda"])) < 1e-12}
        for o in net["others"]:
            rows.append(_row(f"network: origin vs {o['path']} lambda=0 (meV/f.u.)", round(o["diff_meV"], 6),
                             round(1000 * (e_own - l0[o["path"]]), 6), 1e-6, "meV/f.u."))
    return {"rows": rows, "n_numbers": len(rows), "n_ok": sum(x["ok"] for x in rows),
            "summary": {"active": grid["active"], "frames": grid["n_frames"], "matched": jobs["n_matched"],
                        "coefficients": model["coefficients"], "rms_meV": model["rms_meV"], "minimum": model["minimum"],
                        "E_axis_min_meV": model["E_axis_min_meV"], "E_diag_min_meV": model["E_diag_min_meV"]}}
