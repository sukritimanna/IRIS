"""f2 for a two-component plane of ONE multi-dimensional irrep (policy.plane2; live BaTiO3 GM4- (P_z, P_x)).

The first component e_1 is the child's displacement field of the irrep (decomposition, translation removed, per Å
of A_p, as nodes/f2_path.py builds it). The second component e_2 is its image under a parent point operation R
(policy.plane2.rotation, default the cubic 4-fold about y: (x, y, z) -> (z, y, -x), which carries a z-polarised
field into an x-polarised one): atom j = R-image of atom i receives displacement R d_i. G2 checks that R maps the
frame onto itself (every atom onto an equal atom) and that |e_2| = |e_1|.

Frames: Q_1, Q_2 on an n x n grid of the plane at the FIXED parent cell (strain policy P1), Q in Å of A_p in
[-q_max A_p, +q_max A_p]. The plane has 4mm symmetry (Q_1 -> -Q_1, Q_2 -> -Q_2, Q_1 <-> Q_2 when the two components
are related by a 4-fold), so only orbit representatives 0 <= Q_2 <= Q_1 are computed; every orbit's multiplicity
is recorded and G2 checks the count by Burnside and by brute force. Each frame carries its space group and d_min.
"""
from __future__ import annotations

import itertools

import numpy as np

from ..engines.frames import frame_frac
from .f2_path_planner import SYMPREC, _dmin, _sg

DEFAULT_ROTATION = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]       # cubic 4-fold about y (fractional, cubic cell)
GROUP = ((1, 1, False), (-1, 1, False), (1, -1, False), (-1, -1, False),      # (s1, s2, swap)
         (1, 1, True), (-1, 1, True), (1, -1, True), (-1, -1, True))          # the 4mm of the (Q1, Q2) plane


def image_field(f0, d, species, R, L, tol_A=1e-3, centre=None):
    """Displacement field R d on the R-image atoms, for the rotation about an axis through `centre` (fractional).
    centre None: every atom position is tried (the parent's rotation axes pass through atoms of a perovskite; the
    frame's origin is wherever ISODISTORT put it). Returns (field, centre). Raises if no centre maps the frame onto
    itself."""
    R = np.asarray(R, float)
    f0, d = np.asarray(f0, float), np.asarray(d, float)
    cands = [np.asarray(centre, float)] if centre is not None else [np.zeros(3)] + [f0[i].copy() for i in range(len(f0))]
    last = None
    for o in cands:
        out = np.zeros_like(d)
        ok = True
        for i in range(len(f0)):
            fi = (f0[i] - o) @ R.T + o
            diff = f0 - fi
            diff -= np.round(diff)
            j = int(np.argmin(np.linalg.norm(diff @ L, axis=1)))
            if np.linalg.norm(diff[j] @ L) > tol_A or species[j] != species[i]:
                ok, last = False, f"rotation about {o.round(5).tolist()} does not map atom {i} ({species[i]}) onto an equal atom"
                break
            out[j] = d[i] @ R.T
        if ok:
            return out, o
    raise ValueError(last)


def orbit_of(a: int, b: int) -> frozenset:
    pts = set()
    for s1, s2, sw in GROUP:
        x, y = (b, a) if sw else (a, b)
        pts.add((s1 * x, s2 * y))
    return frozenset(pts)


def burnside(levels: int) -> int:
    """Orbits of the (2m+1)^2 grid under 4mm (m = levels - 1 non-zero levels per side)."""
    m = levels - 1
    n = 2 * m + 1
    fixed = [n * n, n, n, 1, n, 1, 1, n]       # identity, sigma_x, sigma_y, C2, diag, C4, C4^3, anti-diag
    return sum(fixed) // 8


def f2_plane2(state: dict) -> dict:
    from pymatgen.core import Lattice, Structure
    cfg, dec = state["config"], state["decomposition"]
    pol = cfg["policy"]
    pp = pol["plane2"]
    irrep = pp["irrep"]
    r0 = dec["vectors"]["r0"]
    L0 = np.array(r0["lattice"])
    f0 = np.array(r0["frac"])
    N = len(r0["species"])
    d = np.array(dec["vectors"]["child_fields_frac"][irrep])
    d = d - d.mean(axis=0)                                        # translation-free
    ap = float(np.linalg.norm(d @ L0) / np.sqrt(dec["vectors"]["n_parent_primitive_cells"]))
    e1 = d / ap
    R = pp.get("rotation") or DEFAULT_ROTATION
    e2, centre = image_field(f0, e1, r0["species"], R, L0)
    c1, c2 = f"{irrep}@c1", f"{irrep}@c2"
    vec = {c1: e1, c2: e2}
    n1, n2 = float(np.linalg.norm(e1 @ L0)), float(np.linalg.norm(e2 @ L0))
    overlap = float(np.sum((e1 @ L0) * (e2 @ L0)) / (n1 * n2))
    levels = int(pp.get("levels", 5))                            # non-negative levels incl. 0 -> (2 levels - 1)^2 grid
    qmax = float(pp.get("q_max", 1.2)) * ap
    step = qmax / (levels - 1)
    reps = sorted({orbit_of(a, b) for a in range(-(levels - 1), levels) for b in range(-(levels - 1), levels)},
                  key=lambda o: max(o))
    frames = []
    for k, orb in enumerate(reps):
        a, b = max(orb)                                           # representative: 0 <= b <= a
        Q = {c1: round(a * step, 10), c2: round(b * step, 10)}
        fr = {"id": k, "name": f"P{k:02d}", "lambda": None, "Q": Q, "orbit": sorted(orb), "multiplicity": len(orb),
              "grid_index": [a, b], "tag": "", "strain_s": 0.0}
        s = Structure(Lattice(L0), r0["species"], frame_frac(fr, f0, vec, [c1, c2]))
        fr.update({"lattice": L0.tolist(), "sg": _sg(s), "d_min": round(_dmin(s), 4)})
        frames.append(fr)
    # expected space groups by position: origin = parent; axis = child (the irrep's isotropy subgroup for (a,0,0));
    # diagonal and general points are recorded, G2 only requires the origin and the axis
    psg, csg = int(cfg["expected"]["parent_sg"]), int(cfg["expected"]["child_sg"])
    for fr in frames:
        a, b = fr["grid_index"]
        fr["expected_sg"] = psg if (a == 0 and b == 0) else (csg if b == 0 else None)
    n_total = (2 * levels - 1) ** 2
    grid = {"built": True, "kind": "plane2", "active": [c1, c2], "irrep": irrep,
            "units": f"Q in Å of A_p({irrep}), translation-free; cell fixed at the parent",
            "n_frames": len(frames), "frames": frames, "vectors": {c1: e1.tolist(), c2: e2.tolist()},
            "Ap_child": {irrep: ap}, "rotation": np.asarray(R).tolist(), "rotation_centre": np.asarray(centre).tolist(),
            "components": {"norm_1_A": n1, "norm_2_A": n2, "overlap": overlap},
            "levels": levels, "q_max_A": qmax, "step_A": step, "n_grid_points": n_total,
            "orbits": {"n": len(reps), "burnside": burnside(levels), "multiplicity_sum": sum(len(o) for o in reps)},
            "lattice": {"orientation": "fixed_parent", "rigid_rotation_deg": 0.0},
            "sizing": {"n": 2, "m": levels, "N": len(frames), "budget": cfg["run"]["budget_runs"]}}
    return {"grid": grid, "last_node": "f2"}
