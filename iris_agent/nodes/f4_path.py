"""f4 Reviewer for a straight-line path (grid kind "path"; HfO2 H3).

Per point: the energy f3 linked from the stored result.json, the convergence numbers behind it (OSZICAR rule of
demo/hfo2/collect_paths.py: last |dE| < EDIFF in fewer than NELM steps), the magnetisation, and the stored
space group. Re-derived here: E per f.u. and dE(lambda) from E0 of the cell (IRIS: unrounded) against result.json
and the collector's energies.csv (both rounded to 3 decimals); f.u. per cell from the composition; one INCAR /
KPOINTS / POTCAR set across the path and the INCAR equal to the campaign template (paths.incar_template).
Nothing is recomputed; a point without a converged stored run is flagged.
"""
from __future__ import annotations

import csv
import math

from ..engines.replay6 import settings_hash
from ..paths import from_config
from .f4_reviewer import MAX_RANGE_MEV, MIN_RANGE_MEV


def f4_path(state: dict) -> dict:
    from pymatgen.core import Composition
    cfg, jobs, grid, dec = state["config"], state["jobs"], state["grid"], state["decomposition"]
    P, pol = from_config(cfg), cfg["policy"]
    qc = pol.get("qc") or {}
    per_fu = int(pol["fit"]["per_fu"])
    accept = bool(state.get("overrides", {}).get("f4", {}).get("flag_unconverged"))
    species = dec["vectors"]["r0"]["species"]
    n_fu = int(Composition("".join(species)).get_reduced_formula_and_factor()[1])
    mag_max = float(qc.get("mag_max_muB", 0.01))
    E, flagged, points = {}, [], []
    for fr in grid["frames"]:
        rec = jobs["matched"].get(str(fr["id"])) or {}
        st, r = rec.get("status", ""), rec.get("result") or {}
        if st.startswith("failed:"):
            flagged.append({"id": fr["id"], "code": st.split(":", 1)[1], "reason": f"job part {rec.get('part')} {st}",
                            "accepted": accept})
            continue
        e = rec.get("energy_eV")
        if e is None or not math.isfinite(e):
            flagged.append({"id": fr["id"], "reason": "no stored energy (unmatched or unfinished)"})
            continue
        conv = (r.get("scf_steps") is not None and r.get("last_dE") is not None
                and r["scf_steps"] < r["NELM"] and r["last_dE"] < r["EDIFF"])
        if not (r.get("converged") and conv):
            flagged.append({"id": fr["id"], "code": "NOT_CONVERGED", "accepted": accept,
                            "reason": f"scf {r.get('scf_steps')}/{r.get('NELM')}, last |dE| {r.get('last_dE')} vs EDIFF {r.get('EDIFF')}"})
            continue
        E[str(fr["id"])] = e
        points.append({"id": fr["id"], "name": fr["name"], "lambda": fr.get("lambda"), "Q": fr.get("Q"), "multiplicity": fr.get("multiplicity", 1), "E0_eV": e,
                       "E_per_fu_eV": e / per_fu, "stored": r, "sg_frame": fr["sg"]})
    e0 = E.get("0")
    for p in points:
        p["dE_meV"] = None if e0 is None else 1000 * (p["E0_eV"] - e0) / per_fu
    # the collector's CSV
    from ._layout import grid_policy
    lay = grid_policy(pol)
    col = P.repo_root / lay["collected"] / "energies.csv"
    pid = lay["stored"].rstrip("/").split("/")[-1]
    csv_rows = {}
    if col.is_file():
        with open(col) as fh:
            csv_rows = {r["point"]: r for r in csv.DictReader(fh) if r["path"] == pid}
    dev = {"E_per_fu_vs_result_meV": 0.0, "dE_vs_result_meV": 0.0, "dE_vs_csv_meV": 0.0, "E0_vs_csv_meV": 0.0}
    sg_bad, mags = [], []
    for p in points:
        r, c = p["stored"], csv_rows.get(p["name"])
        dev["E_per_fu_vs_result_meV"] = max(dev["E_per_fu_vs_result_meV"], 1000 * abs(p["E_per_fu_eV"] - r["E0_per_fu_eV"]))
        if p["dE_meV"] is not None:
            dev["dE_vs_result_meV"] = max(dev["dE_vs_result_meV"], abs(p["dE_meV"] - r["dE_meV_per_fu"]))
            if c:
                dev["dE_vs_csv_meV"] = max(dev["dE_vs_csv_meV"], abs(p["dE_meV"] - float(c["dE_meV_per_fu"])))
        if c:
            dev["E0_vs_csv_meV"] = max(dev["E0_vs_csv_meV"], 1000 * abs(p["E0_eV"] - float(c["E0_eV"])) / per_fu)
        if r.get("space_group") != p["sg_frame"]:
            sg_bad.append((p["name"], r.get("space_group"), p["sg_frame"]))
        mags.append(abs(r.get("mag") or 0.0))
        mags.append(abs(r.get("mag_outcar") or 0.0))
    tmpl = cfg["paths"].get("incar_template")
    th = settings_hash((P.repo_root / tmpl).read_text(), None).get("INCAR") if tmpl else None
    potcars = sorted({" + ".join(p["stored"].get("potcar") or ["NOT SET"]) for p in points})
    vals = list(E.values())
    energies = {"eV_per_cell": E, "flagged": flagged, "n": len(E), "origin_id": "0" if e0 is not None else None,
                "E0_eV": e0, "range_meV_per_fu": (max(vals) - min(vals)) * 1000 / per_fu if vals else None,
                "per_fu": per_fu, "per_fu_from_composition": n_fu,
                "sanity": {"min_range_meV": MIN_RANGE_MEV, "max_range_meV": MAX_RANGE_MEV},
                "points": [{k: v for k, v in p.items() if k != "stored"} |
                           {"scf_steps": p["stored"]["scf_steps"], "last_dE": p["stored"]["last_dE"],
                            "mag": p["stored"]["mag"], "dE_stored_meV": p["stored"]["dE_meV_per_fu"],
                            "dE_csv_meV": float(csv_rows[p["name"]]["dE_meV_per_fu"]) if p["name"] in csv_rows else None}
                           for p in points],
                "rederive_dev": dev, "csv": str(col), "csv_rows": len(csv_rows), "sg_mismatch": sg_bad,
                "max_abs_mag_muB": max(mags) if mags else None, "mag_max_muB": mag_max,
                "incar_template": tmpl, "incar_template_hash": th, "potcar_sets": potcars,
                "convergence_source": "stored result.json (collect_paths.py: OSZICAR last |dE| < EDIFF, N < NELM)",
                "stored_input_sets": jobs.get("stored_input_sets", {}),
                "stored_input_sets_by_group": jobs.get("stored_input_sets_by_group", {})}
    return {"energies": energies, "last_node": "f4"}
