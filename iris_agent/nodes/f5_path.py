"""f5 Analyst for a straight-line path (policy.analysis = path; HfO2 H3).

Profile dE(lambda) per f.u. relative to the lambda = 0 frame (f4, unrounded), the frozen-path barrier (largest
dE on the 10 points; an upper bound: straight line in amplitude + strain space, nothing relaxed) and its lambda,
dE at the end. A not-a-knot cubic spline through the points gives the barrier between grid points (reported,
not gated).

Network (policy.path.network), read-only on the other stored paths:
  cross-setting   this path's end structures are matched (StructureMatcher, tight tolerances) against the end
                  points L00 / L09 of the other stored paths; the same crystal computed in a different
                  ISODISTORT setting / cell must have the same E per f.u. (stored collect_paths.py pairs the ends by
                  hand; IRIS finds them by structure).
  closure         for each chain [Ta, Tb, ...]: the chain must connect this path's start to its end by structure
                  (Ta.L00 = own L00, Ta.L09 = Tb.L00, ..., last.L09 = own L09); then
                  gap = dE_end(own) - sum dE_end(chain). Identity: gap = (E_own,end - E_last,end)
                  - (E_own,start - E_first,start) - sum over junctions (E_a,L09 - E_b,L00), i.e. the closure gap is
                  made of the cross-setting differences at the shared structures (f6 checks this).
"""
from __future__ import annotations

from ._layout import dropped_frames

import json

import numpy as np

from ..engines.frames import frame_frac
from ..paths import from_config
from .f3_path import _poscar


def _structure(lat, species, frac):
    from pymatgen.core import Lattice, Structure
    return Structure(Lattice(lat), species, frac)


def _load_point(root, pid, pt):
    d = root / pid / pt
    lat, sp, fr = _poscar((d / "POSCAR").read_text())
    r = json.loads((d / "result.json").read_text())
    return _structure(lat, sp, fr), r


def _kmesh(d):
    k = (d / "KPOINTS")
    return " x ".join(k.read_text().splitlines()[3].split()[:3]) if k.is_file() else None


def f5_path(state: dict) -> dict:
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from scipy.interpolate import CubicSpline
    cfg, grid, en, dec = state["config"], state["grid"], state["energies"], state["decomposition"]
    P, pp = from_config(cfg), cfg["policy"]["path"]
    per_fu = en["per_fu"]
    pts = sorted(en["points"], key=lambda p: p["id"])
    lam = np.array([p["lambda"] for p in pts])
    dE = np.array([p["dE_meV"] for p in pts])
    k = int(np.argmax(dE))
    cs = CubicSpline(lam, dE)
    xs = np.linspace(0, 1, 9001)
    ks = int(np.argmax(cs(xs)))
    model = {"fitted": True, "kind": "path", "n_points": len(pts), "dropped_frames": dropped_frames(state), "lambda": lam.tolist(), "dE_meV": dE.tolist(),
             "barrier_meV": float(dE[k]), "barrier_index": k, "barrier_lambda": float(lam[k]),
             "barrier_point": pts[k]["name"], "dE_end_meV": float(dE[-1]),
             "barrier_spline": {"meV": float(cs(xs[ks])), "lambda": float(xs[ks]),
                                "note": "not-a-knot cubic spline through the 10 points; between-point estimate, not gated"},
             "barrier_kind": "upper bound: frozen straight line in amplitude + strain space (no relaxation)",
             "per_fu": per_fu}
    net = pp.get("network")
    if not net:
        return {"model": model, "last_node": "f5"}
    root = P.repo_root / pp["collected"]
    me = pp["stored"].rstrip("/").split("/")[-1]
    m = net.get("match", {})
    sm = StructureMatcher(primitive_cell=True, scale=False, attempt_supercell=True, ltol=m.get("ltol", 0.02),
                          stol=m.get("stol", 0.05), angle_tol=m.get("angle_tol", 1.0))
    # own ends: the frames IRIS built (they equal the stored POSCARs to < 1e-4 Å, G3)
    r0 = dec["vectors"]["r0"]
    vec = {ir: np.array(v) for ir, v in grid["vectors"].items()}
    own = {}
    for fr, pt in ((grid["frames"][0], "L00"), (grid["frames"][-1], f"L{len(grid['frames']) - 1:02d}")):
        own[pt] = (_structure(fr["lattice"], r0["species"], frame_frac(fr, np.array(r0["frac"]), vec, grid["active"])),
                   en["eV_per_cell"][str(fr["id"])] / per_fu)
    end = f"L{len(grid['frames']) - 1:02d}"
    others = {}
    for pid in net["paths"]:
        if pid == me:
            continue
        for pt in ("L00", end):
            s, r = _load_point(root, pid, pt)
            others[f"{pid}:{pt}"] = (s, r["E0_per_fu_eV"], r)
    same = {}
    cross = []
    for op, (s_own, e_own) in own.items():
        for key, (s, e, _) in others.items():
            rms = sm.get_rms_dist(s_own, s)
            if rms is not None:
                same[(op, key)] = True
                pa, pb = key.split(":")
                cross.append({"own": op, "other": key, "rms": [float(rms[0]), float(rms[1])],
                              "kmesh_own": _kmesh(root / me / op), "kmesh_other": _kmesh(root / pa / pb),
                              "E_own_per_fu_eV": e_own, "E_other_per_fu_eV": e,
                              "diff_meV": 1000 * (e_own - e)})

    def same_struct(a, b):
        return sm.get_rms_dist(others[a][0], others[b][0]) is not None

    closures = []
    for chain in net.get("closure") or []:
        links = [("own:L00", f"{chain[0]}:L00", (("L00", f"{chain[0]}:L00") in same))]
        for a, b in zip(chain, chain[1:]):
            links.append((f"{a}:{end}", f"{b}:L00", same_struct(f"{a}:{end}", f"{b}:L00")))
        links.append((f"{chain[-1]}:{end}", f"own:{end}", ((end, f"{chain[-1]}:{end}") in same)))
        legs = {pid: 1000 * (others[f"{pid}:{end}"][1] - others[f"{pid}:L00"][1]) for pid in chain}
        gap = model["dE_end_meV"] - sum(legs.values())
        junction = {f"{a}:{end} - {b}:L00": 1000 * (others[f"{a}:{end}"][1] - others[f"{b}:L00"][1])
                    for a, b in zip(chain, chain[1:])}
        closures.append({"chain": chain, "connected": all(x[2] for x in links),
                         "links": [{"from": a, "to": b, "same_structure": bool(c)} for a, b, c in links],
                         "legs_dE_end_meV": legs, "sum_meV": sum(legs.values()), "own_meV": model["dE_end_meV"],
                         "gap_meV": gap, "junction_diff_meV": junction,
                         "start_diff_meV": 1000 * (own["L00"][1] - others[f"{chain[0]}:L00"][1]),
                         "end_diff_meV": 1000 * (own[end][1] - others[f"{chain[-1]}:{end}"][1])})
    model["network"] = {"root": str(root), "paths": net["paths"], "cross_setting": cross,
                        "n_partners": {op: sum(1 for c in cross if c["own"] == op) for op in own},
                        "closure": closures,
                        "cross_setting_tol_meV": float(net.get("cross_setting_meV", 0.1)),
                        "closure_tol_meV": float(net.get("closure_meV", 0.1)),
                        "match": {"ltol": sm.ltol, "stol": sm.stol, "angle_tol": sm.angle_tol}}
    return {"model": model, "last_node": "f5"}
