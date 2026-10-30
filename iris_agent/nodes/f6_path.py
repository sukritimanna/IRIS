"""f6 Skeptic for a straight-line path (grid kind "path"; HfO2 H3). Every reported number again, by another route:

  decomposition   A_p = ||field|| / sqrt(n_cells) from the stored mode matrix vs f1
  selection       select_modes re-run from the raw amplitudes
  frames          space group and shortest contact recounted (spglib) on the STORED POSCARs, not IRIS's frames
  energies        re-read from the collector's energies.csv (not result.json, which f3/f4 used)
  barrier, end    max / last of the CSV profile; the stored energies_summary.json; spline maximum by a bounded
                  scalar optimiser (not the grid search of f5)
  per f.u.        from the POSCAR species count
  network         cross-setting differences and closure gaps from the CSV; the closure identity
                  gap = end diff - start diff - sum junction diffs
"""
from __future__ import annotations

import csv
import json

import numpy as np

from ..paths import from_config
from ..rules.select_modes import select_for
from .f3_path import _poscar
from .f2_path_planner import SYMPREC
from .f6_grid6 import _row


def path_report(state: dict) -> dict:
    from pymatgen.core import Composition, Lattice, Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    from scipy.interpolate import CubicSpline
    from scipy.optimize import minimize_scalar
    cfg, dec, sel, grid = state["config"], state["decomposition"], state["selection"], state["grid"]
    jobs, en, model = state["jobs"], state["energies"], state["model"]
    P, pol = from_config(cfg), cfg["policy"]
    pp = pol["path"]
    rows = []
    # decomposition
    r0 = dec["vectors"]["r0"]
    s0 = Structure(Lattice(r0["lattice"]), r0["species"], r0["frac"])
    n_cells = len(s0) / len(SpacegroupAnalyzer(s0, symprec=1e-3).find_primitive())
    rows.append(_row("parent primitive cells in the frame", dec["vectors"]["n_parent_primitive_cells"], n_cells, 1e-9))
    for ir, v in dec["irreps"].items():
        rows.append(_row(f"A_p {ir}", abs(v["Ap"]), dec["vectors"]["norm_A"][ir] / np.sqrt(n_cells), 2e-4, "Å"))
    again = select_for(dec, pol, state.get("overrides", {}).get("f2", {}).get("r5_decision"))
    rows.append(_row("active set", sel["active"], again["active"], None))
    rows.append(_row("path irreps = every displacive irrep", sorted(grid["active"]), sorted(dec["vectors"]["child_fields_frac"]), None))
    # frames: the stored POSCARs recounted
    root = P.repo_root / pp["stored"]
    for fr in grid["frames"]:
        lat, sp, frac = _poscar((root / fr["name"] / "POSCAR").read_text())
        s = Structure(Lattice(lat), sp, frac)
        rows.append(_row(f"{fr['name']} space group (stored POSCAR)", fr["sg"],
                         SpacegroupAnalyzer(s, symprec=SYMPREC).get_space_group_number(), None))
        dm = s.distance_matrix + np.eye(len(s)) * 1e9
        rows.append(_row(f"{fr['name']} d_min (Å)", fr["d_min"], round(float(dm.min()), 4), 2e-4, "Å"))
    n_fu = int(Composition("".join(sp)).get_reduced_formula_and_factor()[1])
    rows.append(_row("f.u. per cell", en["per_fu"], n_fu, None))
    # energies from the CSV
    pid = pp["stored"].rstrip("/").split("/")[-1]
    with open(P.repo_root / pp["collected"] / "energies.csv") as fh:
        allrows = list(csv.DictReader(fh))
    csv_ = {r["point"]: r for r in allrows if r["path"] == pid}
    e0 = float(csv_["L00"]["E0_eV"])
    dEc = []
    for p in sorted(en["points"], key=lambda q: q["id"]):
        c = csv_[p["name"]]
        rows.append(_row(f"{p['name']} E0 (eV/cell)", p["E0_eV"], float(c["E0_eV"]), 1e-9, "eV"))
        d = 1000 * (float(c["E0_eV"]) - e0) / n_fu
        dEc.append(d)
        rows.append(_row(f"{p['name']} dE (meV/f.u.)", round(p["dE_meV"], 3), float(c["dE_meV_per_fu"]), 6e-4, "meV/f.u."))
        rows.append(_row(f"{p['name']} converged (CSV)", True, c["converged"] == "True", None))
    dEc = np.array(dEc)
    k = int(np.argmax(dEc))
    rows.append(_row("barrier (meV/f.u.)", model["barrier_meV"], float(dEc[k]), 1e-9, "meV/f.u."))
    rows.append(_row("barrier point", model["barrier_point"], f"L{k:02d}", None))
    rows.append(_row("dE end (meV/f.u.)", model["dE_end_meV"], float(dEc[-1]), 1e-9, "meV/f.u."))
    summ = json.loads((P.repo_root / pp["collected"] / "energies_summary.json").read_text())
    ss = summ["paths"][pid]
    rows.append(_row("barrier vs energies_summary.json (meV/f.u.)", round(model["barrier_meV"], 3), ss["barrier_meV_per_fu"], 6e-4, "meV/f.u."))
    rows.append(_row("barrier lambda vs energies_summary.json", model["barrier_lambda"], ss["barrier_at_lambda"], 1e-4))
    rows.append(_row("dE end vs energies_summary.json (meV/f.u.)", round(model["dE_end_meV"], 3), ss["dE_end_meV_per_fu"], 6e-4, "meV/f.u."))
    lam = np.array(model["lambda"])
    cs = CubicSpline(lam, dEc)
    lo, hi = lam[max(k - 1, 0)], lam[min(k + 1, len(lam) - 1)]
    o = minimize_scalar(lambda x: -cs(x), bounds=(lo, hi), method="bounded", options={"xatol": 1e-8})
    rows.append(_row("spline barrier (meV/f.u.)", model["barrier_spline"]["meV"], float(-o.fun), 0.01, "meV/f.u."))
    rows.append(_row("spline barrier lambda", model["barrier_spline"]["lambda"], float(o.x), 2e-4))
    # network
    net = model.get("network")
    if net:
        e_csv = {f"{r['path']}:{r['point']}": float(r["E0_per_fu_eV"]) for r in allrows}
        end = f"L{len(grid['frames']) - 1:02d}"
        for c in net["cross_setting"]:
            d = 1000 * (e_csv[f"{pid}:{c['own']}"] - e_csv[c["other"]])
            rows.append(_row(f"cross-setting {pid}:{c['own']} - {c['other']} (meV/f.u.)", c["diff_meV"], d, 1e-6, "meV/f.u."))
        for cl in net["closure"]:
            ch = cl["chain"]
            legs = sum(1000 * (e_csv[f"{x}:{end}"] - e_csv[f"{x}:L00"]) for x in ch)
            own = 1000 * (e_csv[f"{pid}:{end}"] - e_csv[f"{pid}:L00"])
            nm = " + ".join(x.split("__")[0] for x in ch)
            rows.append(_row(f"closure gap {pid.split('__')[0]} - ({nm}) (meV/f.u.)", cl["gap_meV"], own - legs, 1e-6, "meV/f.u."))
            ident = cl["end_diff_meV"] - cl["start_diff_meV"] - sum(cl["junction_diff_meV"].values())
            rows.append(_row(f"closure gap = cross-setting differences ({nm})", cl["gap_meV"], ident, 1e-9, "meV/f.u."))
    return {"rows": rows, "n_numbers": len(rows), "n_ok": sum(x["ok"] for x in rows),
            "summary": {"active": grid["active"], "frames": grid["n_frames"], "matched": jobs["n_matched"],
                        "profile_meV": model["dE_meV"], "barrier_meV": model["barrier_meV"],
                        "barrier_lambda": model["barrier_lambda"], "dE_end_meV": model["dE_end_meV"],
                        "barrier_spline": model["barrier_spline"], "barrier_kind": model["barrier_kind"],
                        "lattice_orientation": grid["lattice"]["orientation"],
                        "rigid_rotation_deg": grid["lattice"]["rigid_rotation_deg"],
                        "network": None if not net else {"cross_setting": [{k: c[k] for k in ("own", "other", "diff_meV")}
                                                                           for c in net["cross_setting"]],
                                                         "closure": [{k: c[k] for k in ("chain", "gap_meV", "connected")}
                                                                     for c in net["closure"]]}}}
