"""f2 Path planner, straight-line irrep path between two polymorphs (policy.path; HfO2 T1-T5, stage H2).

Frames k = 0 .. n-1 at lambda = k/(n-1):
  displacements  every displacive irrep of the decomposition at lambda x its child amplitude (A_p; polar irreps
                 translation-free), superposed in fractional coordinates of the parent supercell frame r0;
  lattice        L(lambda) = L0 + lambda (L1 - L0) (one strain coordinate s = lambda), L0 = r0's lattice and L1 the
                 child cell (child CIF metric) in r0's axis order, oriented by policy.path.child_lattice:
                   orientation: stored        rotation of the child cell as the stored path built it (the stored
                                              generator's dL_child.npy: child CIF snapped onto the movie lattice);
                   orientation: pure_stretch  no rigid rotation relative to L0 (polar decomposition, F = U).
                 Both are recorded; their difference (rigid rotation, cell difference at lambda = 1/2) is reported.
Checks (G2_path): L1 has the child metric; the lambda = 1 frame is the child (StructureMatcher RMS); space groups
along the path (parent at 0, the child's group inside); the plan equals the stored path.json (lambda, A_p).
"""
from __future__ import annotations

import json

import numpy as np

from ..engines.frames import frame_frac
from ..paths import from_config
from .f2_path_planner import SYMPREC, _dmin, _sg


def _orient(C, target):
    """Rotation R (det +1) minimising |C R - target| (orthogonal Procrustes); returns C R."""
    U, _, Vt = np.linalg.svd(C.T @ target)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        U[:, -1] *= -1
        R = U @ Vt
    return C @ R


def rigid_rotation_deg(L0, L1) -> float:
    from scipy.linalg import polar
    F = L1.T @ np.linalg.inv(L0.T)            # column vectors: a1 = F a0
    R, _ = polar(F)
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def pure_stretch(L0, C):
    """Child cell with the metric of C in L0's axis order and no rigid rotation relative to L0: any orientation
    L1' = C R gives F = L1'^T L0^-T = R' U (polar decomposition); L1 = (U L0^T)^T keeps the metric
    (L1 L1^T = L0 U^2 L0^T = C C^T) and has F = U symmetric."""
    from scipy.linalg import polar
    F = _orient(C, L0).T @ np.linalg.inv(L0.T)
    _, U = polar(F)
    return (U @ L0.T).T


def f2_path(state: dict) -> dict:
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.core import Lattice, Structure
    cfg, dec = state["config"], state["decomposition"]
    P, pol = from_config(cfg), cfg["policy"]
    pp = pol["path"]
    irreps = dec["irreps"]
    r0 = dec["vectors"]["r0"]
    L0 = np.array(r0["lattice"])
    f0 = np.array(r0["frac"])
    N = len(r0["species"])
    # vectors: every displacive irrep, translation removed, per Å of A_p (translation-free)
    vec, ap, trans = {}, {}, {}
    for ir, d in dec["vectors"]["child_fields_frac"].items():
        d = np.array(d)
        ebar = d.mean(axis=0)
        fT = float(N * np.sum((ebar @ L0) ** 2) / np.sum((d @ L0) ** 2)) if np.sum(d ** 2) > 0 else 0.0
        d = d - ebar
        a = float(np.linalg.norm(d @ L0) / np.sqrt(dec["vectors"]["n_parent_primitive_cells"]))
        vec[ir], ap[ir] = d / a, a
        trans[ir] = {"f_T": fT, "Ap_tf_from_field": a, "Ap_tf_f1": irreps[ir].get("Ap_tf")}
    order = sorted(vec)
    # child cell in r0's axis order
    C = Structure.from_file(state["inputs"]["child_cif"]).lattice.matrix
    L1_stretch = pure_stretch(L0, C)
    cl = pp.get("child_lattice", {"orientation": "pure_stretch"})
    if cl.get("orientation") == "stored":
        dL = np.load(P.repo_root / cl["file"])
        L1 = _orient(C, L0 + dL)                 # the child metric, oriented as the stored path's cell
    else:
        L1 = L1_stretch
    lat_info = {"orientation": cl.get("orientation"), "source": cl.get("file"),
                "metric_dev_A2": float(np.abs(L1 @ L1.T - C @ C.T).max()),
                "rigid_rotation_deg": rigid_rotation_deg(L0, L1),
                "rigid_rotation_deg_pure_stretch": rigid_rotation_deg(L0, L1_stretch),
                "L1": L1.tolist(), "L1_pure_stretch": L1_stretch.tolist()}
    Lh, Lh_s = L0 + 0.5 * (L1 - L0), L0 + 0.5 * (L1_stretch - L0)
    lat_info["midpoint_vs_pure_stretch"] = {
        "abc_A": (np.array(Lattice(Lh).abc) - np.array(Lattice(Lh_s).abc)).tolist(),
        "angles_deg": (np.array(Lattice(Lh).angles) - np.array(Lattice(Lh_s).angles)).tolist(),
        "volume_rel": float(Lattice(Lh).volume / Lattice(Lh_s).volume - 1)}
    n = int(pp.get("n_points", 10))
    frames = []
    for k in range(n):
        lam = k / (n - 1)
        Q = {ir: round(lam * ap[ir], 10) for ir in order}
        fr = {"id": k, "name": f"L{k:02d}", "lambda": lam, "strain_s": lam, "Q": Q, "tag": ""}
        Lk = L0 + lam * (L1 - L0)
        s = Structure(Lattice(Lk), r0["species"], frame_frac(fr, f0, vec, order))
        fr.update({"lattice": Lk.tolist(), "sg": _sg(s), "d_min": round(_dmin(s), 4),
                   "expected_sg": int(cfg["expected"]["parent_sg"]) if k == 0 else int(cfg["expected"]["child_sg"])})
        frames.append(fr)
    # lambda = 1 frame vs the child CIF
    last = frames[-1]
    sl = Structure(Lattice(last["lattice"]), r0["species"], frame_frac(last, f0, vec, order))
    sm = StructureMatcher(primitive_cell=False, scale=False, attempt_supercell=True, ltol=0.05, stol=0.1, angle_tol=2)
    rms = sm.get_rms_dist(sl, Structure.from_file(state["inputs"]["child_cif"]))
    # the stored path.json
    stored = {}
    if pp.get("stored") and cfg["run"]["mode"] != "live":   # live: nothing stored to compare with
        pj = json.loads((P.repo_root / pp["stored"] / "path.json").read_text())
        st_l = pj["lambda"]
        ptj = [json.loads((P.repo_root / pp["stored"] / p / "point.json").read_text()) for p in pj["points"]]
        dAp = max(abs(pt["irreps"][ir]["Ap"] - frames[i]["Q"][ir]) for i, pt in enumerate(ptj) for ir in order)
        stored = {"n_points": len(pj["points"]), "lambda_max_dev": float(max(abs(a - f["lambda"]) for a, f in zip(st_l, frames))),
                  "Ap_max_dev_A": float(dAp), "irreps": sorted(ptj[0]["irreps"]),
                  "Ap_child_stored": {ir: ptj[0]["irreps"][ir]["Ap_child"] for ir in ptj[0]["irreps"]},
                  "sg_stored": [pt["space_group"]["symprec_1e-4_1e-3_1e-2"][-1] for pt in ptj],
                  "d_min_stored_A": [pt["d_min_A"] for pt in ptj],
                  "lattice_max_dev_A": float(max(np.abs(np.array(pt["structure"]["lattice"]) - np.array(f["lattice"])).max()
                                                 for pt, f in zip(ptj, frames)))}
    grid = {"built": True, "kind": "path", "active": order, "units": "Q in Å of A_p (translation-free); lattice linear in lambda",
            "n_frames": len(frames), "frames": frames, "vectors": {ir: v.tolist() for ir, v in vec.items()},
            "Ap_child": ap, "translation": trans, "lattice": lat_info,
            "child_match_rms": None if rms is None else [float(rms[0]), float(rms[1])], "stored": stored,
            "sizing": {"n": len(order), "m": n, "N": n, "budget": cfg["run"]["budget_runs"]}}
    return {"grid": grid, "last_node": "f2"}
