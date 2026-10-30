"""f5 for a two-component plane of one irrep (grid kind plane2): Landau fit with the 4mm invariants, minimum, the
energies along the axis ([001]-type) and the diagonal ([101]-type) directions, and the full grid rebuilt from the
orbit representatives by symmetry (for the page and for f6).

  E(Q1, Q2) = a (Q1^2 + Q2^2) + b (Q1^4 + Q2^4) + c Q1^2 Q2^2 + d (Q1^6 + Q2^6) + e (Q1^4 Q2^2 + Q1^2 Q2^4)   [meV/f.u.]

Weighted least squares over the orbit representatives (weight = orbit multiplicity), E(0,0) = 0 fixed. The sign of
(c - 2b) decides whether the minimum lies on the axis (c > 2b: P4mm-type) or on the diagonal (c < 2b: Amm2-type)
at 4th order; the fitted minimum is found numerically on the full invariant expansion. Nothing is gated here; G5
checks coverage, fit quality and that the minimum lies inside the grid.
"""
from __future__ import annotations

from ._layout import dropped_frames

import numpy as np

from .f2_plane2 import GROUP

TERMS = ("a", "b", "c", "d", "e")


def design(q1, q2):
    q1, q2 = np.asarray(q1, float), np.asarray(q2, float)
    return np.stack([q1 ** 2 + q2 ** 2, q1 ** 4 + q2 ** 4, q1 ** 2 * q2 ** 2, q1 ** 6 + q2 ** 6,
                     q1 ** 4 * q2 ** 2 + q1 ** 2 * q2 ** 4], axis=1)


def fit(q1, q2, E, w):
    """Weighted least squares; returns coefficients, fitted values, rms (weighted), max |residual|."""
    A, y, w = design(q1, q2), np.asarray(E, float), np.asarray(w, float)
    sw = np.sqrt(w)
    coef, *_ = np.linalg.lstsq(A * sw[:, None], y * sw, rcond=None)
    fitv = A @ coef
    res = y - fitv
    rms = float(np.sqrt(np.sum(w * res ** 2) / np.sum(w)))
    return coef, fitv, rms, float(np.abs(res).max())


def evaluate(coef, q1, q2):
    return design(q1, q2) @ coef


def minimum(coef, qmax):
    """Numerical minimum of the fitted surface on [0, qmax]^2 (the symmetry-unique wedge is enough)."""
    g = np.linspace(0, qmax, 241)
    Q1, Q2 = np.meshgrid(g, g, indexing="ij")
    E = evaluate(coef, Q1.ravel(), Q2.ravel()).reshape(Q1.shape)
    E = np.where(Q2 <= Q1 + 1e-12, E, np.inf)                 # the symmetry-unique wedge 0 <= Q2 <= Q1
    k = np.unravel_index(int(np.argmin(E)), E.shape)
    q1, q2 = float(Q1[k]), float(Q2[k])
    kind = "origin" if q1 == 0 and q2 == 0 else ("axis" if min(q1, q2) < 1e-9 else ("diagonal" if abs(q1 - q2) < 1e-9 else "general"))
    return {"Q1": q1, "Q2": q2, "E_meV": float(E[k]), "where": kind, "on_border": bool(max(q1, q2) >= qmax - 1e-9)}


def plane_network(cfg: dict, pts: list, en: dict) -> dict | None:
    """Cross-run check: the plane's origin is the parent cell, and so is lambda = 0 of every path of the campaign, so
    their energies per formula unit must agree (same functional, cut-off, potentials, equivalent k-mesh) to
    policy.plane2.network_meV (default 1 meV, as the path network). Read-only on the campaign's energies.csv; None
    when the campaign has no finished path."""
    import csv
    from ..paths import from_config
    pp = cfg["policy"]["plane2"]
    root = from_config(cfg).repo_root / pp["collected"] / "energies.csv"
    if not root.exists():
        return None
    me = pp["stored"].rstrip("/").split("/")[-1]
    origin = next((p for p in pts if abs(p["Q"][list(p["Q"])[0]]) < 1e-12 and abs(p["Q"][list(p["Q"])[1]]) < 1e-12), None)
    if origin is None:
        return None
    e_own = float(origin["E0_eV"]) / en["per_fu"]
    others = []
    with open(root) as fh:
        for r in csv.DictReader(fh):
            if r["path"] == me or not r.get("lambda"):
                continue
            if abs(float(r["lambda"])) < 1e-12:
                e = float(r["E0_per_fu_eV"])
                others.append({"path": r["path"], "point": r["point"], "E_other_per_fu_eV": e,
                               "diff_meV": 1000 * (e_own - e)})
    if not others:
        return None
    return {"origin": origin["name"], "E_own_per_fu_eV": e_own, "others": others,
            "tol_meV": float(pp.get("network_meV", 1.0)), "root": str(root)}


def f5_plane2(state: dict) -> dict:
    cfg, grid, en = state["config"], state["grid"], state["energies"]
    pol = cfg["policy"]
    pts = sorted(en["points"], key=lambda p: p["id"])
    c1, c2 = grid["active"]
    q1 = np.array([p["Q"][c1] for p in pts])
    q2 = np.array([p["Q"][c2] for p in pts])
    dE = np.array([p["dE_meV"] for p in pts])
    w = np.array([p.get("multiplicity", 1) for p in pts], float)
    coef, fitv, rms, maxres = fit(q1, q2, dE, w)
    qmax = float(grid["q_max_A"])
    mn = minimum(coef, qmax)
    # the two symmetry lines on the computed points
    axis = sorted([(float(p["Q"][c1]), float(p["dE_meV"])) for p in pts if abs(p["Q"][c2]) < 1e-12])
    diag = sorted([(float(p["Q"][c1]), float(p["dE_meV"])) for p in pts if abs(p["Q"][c1] - p["Q"][c2]) < 1e-12])
    # full grid from the orbit representatives (symmetry images carry the same energy)
    step = float(grid["step_A"])
    full = {}
    for p in pts:
        a, b = [int(round(x / step)) for x in (p["Q"][c1], p["Q"][c2])]
        for s1, s2, sw in GROUP:
            x, y = (b, a) if sw else (a, b)
            full[(s1 * x, s2 * y)] = float(p["dE_meV"])
    levels = int(grid["levels"])
    idx = list(range(-(levels - 1), levels))
    surface = [[full.get((i, j)) for j in idx] for i in idx]       # rows Q1, cols Q2
    network = plane_network(cfg, pts, en)
    model = {"fitted": True, "kind": "plane2", "n_points": len(pts), "dropped_frames": dropped_frames(state), "irrep": grid["irrep"], "components": [c1, c2],
             "network": network,
             "coefficients": dict(zip(TERMS, [float(x) for x in coef])),
             "terms": "a(Q1^2+Q2^2) + b(Q1^4+Q2^4) + c Q1^2Q2^2 + d(Q1^6+Q2^6) + e(Q1^4Q2^2+Q1^2Q2^4), meV/f.u., Q in Å",
             "rms_meV": rms, "max_abs_res_meV": maxres, "residuals_meV": (dE - fitv).tolist(),
             "anisotropy_c_minus_2b": float(coef[2] - 2 * coef[1]),
             "minimum": mn, "axis_profile": axis, "diagonal_profile": diag,
             "E_axis_min_meV": min(e for _, e in axis), "E_diag_min_meV": min(e for _, e in diag) if diag else None,
             "q_max_A": qmax, "step_A": step, "levels": levels, "grid_index": idx, "surface_meV": surface,
             "n_full_points": sum(1 for row in surface for v in row if v is not None),
             "per_fu": en["per_fu"], "max_rms_meV": float(pol["fit"]["max_rms_meV"]),
             "max_abs_res_meV_allowed": float(pol["fit"]["max_abs_res_meV"])}
    return {"model": model, "last_node": "f5"}
