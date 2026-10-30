"""f5 Analyst, analysis kind "meier_joint": Meier Eq. 12 with the six-fold term, fitted jointly on the
(K3, GM2-) plane at Phi = 0 and the polar (Q, Phi, P) hat wedge (stage 2 of the manganite replays):

    F = a/2 Q^2 + b/4 Q^4 + (c + c' cos 6Phi)/6 Q^6 + a_P/2 P^2 - g Q^3 P cos 3Phi + g'/2 Q^2 P^2

Q, P in A_s = sqrt(n_cells) A_p; energies per cell relative to the plane's Q = P = 0 frame. Plane frames
with Q_K3 < 0 enter with Phi = 60 deg (cos 3Phi = -1, cos 6Phi = 1). a_P is fitted, or fixed from the
P axis (policy.fit.joint.aP = axis, ErMnO3). Window per part: |Q| <= qmax, |P| <= pmax_plane / pmax_hat.
Reproduces demo/inmno3/landau/joint_hat_fit.py and demo/ermno3/landau/joint_hat_fit.py (both read the
stored manifests from fixed relative paths, so they cannot be run on IRIS's frames; computed in-node).

Derived (as those scripts): hat = -min_Q F(Q, 0) and brim = min_Q F(Q, 30 deg) - min_Q F(Q, 0), with P
relaxed analytically (P* = g Q^3 cos 3Phi / (a_P + g' Q^2)), in meV per formula unit.
"""
from __future__ import annotations

from ._layout import dropped_frames

import numpy as np

from .f5_meier import axis_aP

NAMES_FREE = ["a", "b", "c", "a_P", "g", "g'", "c'"]


def rows(grid, energies, polar_tag):
    mQ, mP = grid["active"]
    E = energies["eV_per_cell"]
    plane = [f for f in grid["frames"] if not f["tag"] and str(f["id"]) in E]
    o = min(plane, key=lambda f: f["Q"][mQ] ** 2 + f["Q"][mP] ** 2)
    E0 = E[str(o["id"])]
    out = []
    for f in plane:
        q = f["Q"][mQ]
        out.append((abs(q), 0.0 if q >= 0 else np.pi / 3, f["Q"][mP], E[str(f["id"])] - E0, 0, f["id"]))
    for f in grid["frames"]:
        if f["tag"] == polar_tag and str(f["id"]) in E:
            out.append((f["Q"][mQ], np.radians(f["phi_deg"]), f["Q"][mP], E[str(f["id"])] - E0, 1, f["id"]))
    return out


def design(Qs, T, Ps, with_aP=True):
    cols = [Qs**2 / 2, Qs**4 / 4, Qs**6 / 6]
    if with_aP:
        cols.append(Ps**2 / 2)
    cols += [-(Qs**3) * Ps * np.cos(3 * T), Qs**2 * Ps**2 / 2, Qs**6 / 6 * np.cos(6 * T)]
    return np.vstack(cols).T


def model_F(co, q, phi):
    k = co["g"] * q**3 * np.cos(3 * phi)
    return co["a"] / 2 * q**2 + co["b"] / 4 * q**4 + (co["c"] + co["c'"] * np.cos(6 * phi)) / 6 * q**6 \
        - k**2 / (2 * (co["a_P"] + co["g'"] * q**2))


def solve(R, nc, joint, aP_fixed=None, solver="lstsq"):
    Q, T, P, E, src, ids = (np.array(x) for x in zip(*R))
    w = (Q <= joint["qmax"] + 1e-9) & (np.abs(P) <= np.where(src == 1, joint["pmax_hat"], joint["pmax_plane"]) + 1e-9)
    S = np.sqrt(nc)
    Qs, Ps = S * Q[w], S * P[w]
    X = design(Qs, T[w], Ps, with_aP=aP_fixed is None)
    y = E[w] - (aP_fixed / 2 * Ps**2 if aP_fixed is not None else 0.0)
    if solver == "qr":
        Qm, Rm = np.linalg.qr(X)
        c = np.linalg.solve(Rm, Qm.T @ y)
    else:
        c, *_ = np.linalg.lstsq(X, y, rcond=None)
    names = [n for n in NAMES_FREE if not (aP_fixed is not None and n == "a_P")]
    co = dict(zip(names, map(float, c)))
    if aP_fixed is not None:
        co["a_P"] = float(aP_fixed)
    r = y - X @ c
    return {k: co[k] for k in NAMES_FREE}, r, w, src[w], X, y, ids[w]


def f5_joint(state: dict) -> dict:
    cfg, grid, en, dec = state["config"], state["grid"], state["energies"], state["decomposition"]
    fit = cfg["policy"]["fit"]
    joint = fit["joint"]
    pol = grid.get("polar") or {}
    nc = float(dec["vectors"]["n_parent_primitive_cells"])
    S = np.sqrt(nc)
    aP_fixed, axinfo = None, None
    if joint.get("aP") == "axis":
        ax = fit["aP_axis"]
        aP_fixed, axinfo = axis_aP(grid, en, ax.get("tag_prefix", "anchor_pax"), float(ax["pmax"]),
                                   tuple(ax.get("powers", (2, 4, 6))), nc)
    R = rows(grid, en, pol.get("tag", "hat"))
    co, r, w, srcw, X, y, idsw = solve(R, nc, joint, aP_fixed)
    k = fit["cv_folds"]
    idx = np.arange(len(y)) % k
    cres = np.empty_like(y)
    for f in range(k):
        tr, te = idx != f, idx == f
        cc, *_ = np.linalg.lstsq(X[tr], y[tr], rcond=None)
        cres[te] = y[te] - X[te] @ cc
    lo, hi = joint.get("brim_q_As", [0.3, 1.4])
    qq = np.linspace(lo, hi, int(joint.get("brim_n", 2000)))
    F0, F30 = model_F(co, qq, 0.0), model_F(co, qq, np.pi / 6)
    i0 = int(np.argmin(F0))
    per_fu = fit["per_fu"]
    q0 = float(qq[i0])
    p0 = float(co["g"] * q0**3 / (co["a_P"] + co["g'"] * q0**2))
    co0 = {**co, "c'": 0.0}
    brim_c0 = float((model_F(co0, qq, np.pi / 6).min() - model_F(co0, qq, 0.0).min()) * 1000 / per_fu)
    dq = grid["sizing"]["dq"]
    dqQ = dq[grid["active"][0]] if isinstance(dq, dict) else dq
    model = {"fitted": True, "dropped_frames": dropped_frames(state), "kind": "meier_joint",
             "script": "in-node (procedure of demo/<system>/landau/joint_hat_fit.py)",
             "modes": grid["active"], "per_fu": per_fu, "energy_unit": "per cell", "n_cells": nc,
             "window": {"qmax_A": joint["qmax"], "pmax_plane_A": joint["pmax_plane"], "pmax_hat_A": joint["pmax_hat"]},
             "n_fit": int(w.sum()), "n_fit_plane": int((srcw == 0).sum()), "n_fit_hat": int((srcw == 1).sum()),
             "n_fit_ids": [int(i) for i in idsw], "aP": "fixed from the P axis" if aP_fixed is not None else "fitted",
             "aP_axis": axinfo, "coefficients_As": co,
             "rms_meV": float(np.sqrt(np.mean(r**2)) * 1000), "max_abs_res_meV": float(np.abs(r).max() * 1000),
             "rms_plane_meV": float(np.sqrt(np.mean(r[srcw == 0] ** 2)) * 1000),
             "rms_hat_meV": float(np.sqrt(np.mean(r[srcw == 1] ** 2)) * 1000) if (srcw == 1).any() else None,
             "cv": {"folds": k, "rms_meV": float(np.sqrt(np.mean(cres**2)) * 1000), "max_abs_meV": float(np.abs(cres).max() * 1000)},
             "hat_meV_per_fu": float(-F0.min() * 1000 / per_fu),
             "brim_meV_per_fu": float((F30.min() - F0.min()) * 1000 / per_fu), "brim_cprime0_meV_per_fu": brim_c0,
             "brim_q_scan_As": [lo, hi, len(qq)],
             "Q_star_A": q0 / S, "coupled": {"Q_A": q0 / S, "P_A": p0 / S, "E_meV": float(F0.min() * 1000)},
             "coupled_As": [q0, p0], "grid_dq_A": dqQ,
             "polar_grid": {k_: pol.get(k_) for k_ in ("wedge_deg", "reduction", "n")}}
    if aP_fixed is not None and fit["aP_axis"].get("sensitivity"):
        from .f5_meier import SENS_KEYS_JOINT, aP_sensitivity
        model["aP_sensitivity"] = aP_sensitivity(state, f5_joint, SENS_KEYS_JOINT)
    return {"model": model, "last_node": "f5"}
