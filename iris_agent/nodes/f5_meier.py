"""f5 Analyst, analysis kind "meier_QP" (policy.analysis: meier_QP): the hexagonal-manganite free energy
on the (K3, GM2-) plane at Phi = 0 (Meier et al. 2020 Eq. 12, uniform state, c' not determinable):

    E(Q, P) = a/2 Q^2 + b/4 Q^4 + c/6 Q^6 + a_P/2 P^2 - g Q^3 P + g'/2 Q^2 P^2

Runs the existing demo/staged_walkthrough/fit_landau_QP.py UNCHANGED, as a subprocess, on a run-dir layout
written inside IRIS_AGENT (test_runs/<thread>/f5_meier/): step4_energy_plane/{grid_spec.json,
grid_manifest.json} from the frames f2 built (ap_A = Q, translation-free A_p) and energies.csv from f4.
Fit window |Q| <= policy.fit.qmax, |P| <= policy.fit.pmax (A_p); energies per 30-atom cell.

Added here: k-fold cross-validation of the same model on the same fit set, and the coefficients converted
to Meier's convention (A_s = sqrt(n_cells) A_p).
"""
from __future__ import annotations

from ._layout import dropped_frames, r5_anchor_report

import csv
import json
import os
import subprocess
import sys

import numpy as np

from ..engines import legacy
from ..paths import from_config

NAMES = ["a", "b", "c", "a_P", "g", "g'"]
POWER = {"a": 2, "b": 4, "c": 6, "a_P": 2, "g": 4, "g'": 4}        # A_p -> A_s: coef / sqrt(n)^power


def design(Q, P):
    return np.c_[Q**2 / 2, Q**4 / 4, Q**6 / 6, P**2 / 2, -(Q**3) * P, Q**2 * P**2 / 2]


def fit_set(grid, energies, qmax, pmax, per_cell_unit=1.0):
    """The script's fit set: frames with energies, E relative to the frame nearest Q = P = 0, window."""
    mQ, mP = grid["active"]
    E = energies["eV_per_cell"]
    pts = [f for f in grid["frames"] if str(f["id"]) in E]
    o = min(pts, key=lambda f: f["Q"][mQ] ** 2 + f["Q"][mP] ** 2)
    Q = np.array([f["Q"][mQ] for f in pts])
    P = np.array([f["Q"][mP] for f in pts])
    Y = np.array([(E[str(f["id"])] - E[str(o["id"])]) * per_cell_unit for f in pts])
    w = (np.abs(Q) <= qmax + 1e-9) & (np.abs(P) <= pmax + 1e-9)
    return Q[w], P[w], Y[w], [f["id"] for f, k in zip(pts, w) if k]


def kfold_cv(Q, P, Y, k):
    X = design(Q, P)
    idx = np.arange(len(Y)) % k
    res = np.empty_like(Y)
    for f in range(k):
        tr, te = idx != f, idx == f
        c, *_ = np.linalg.lstsq(X[tr], Y[tr], rcond=None)
        res[te] = Y[te] - X[te] @ c
    return float(np.sqrt(np.mean(res**2)) * 1000), float(np.abs(res).max() * 1000)


def derived(co, qmax):
    """Q*, depth and the coupled minimum as fit_landau_QP.py computes them (2000-point Q scan, P* analytic)."""
    aa, bb, cc, aP, g, gp = (co[k] for k in NAMES)
    q = np.linspace(0.01, qmax, 2000)
    e_axis = aa / 2 * q**2 + bb / 4 * q**4 + cc / 6 * q**6
    Pst = g * q**3 / (aP + gp * q**2)
    e_c = e_axis + aP / 2 * Pst**2 - g * q**3 * Pst + gp / 2 * q**2 * Pst**2
    k = int(np.argmin(e_c))
    return float(q[np.argmin(e_axis)]), float(e_axis.min()), [float(q[k]), float(Pst[k]), float(e_c[k])]


def axis_aP(grid, energies, tag_prefix, pmax, powers, nc):
    """a_P from the stored P-axis points (anchors tagged <tag_prefix>*, Q_K3 = 0): E(P) relative to the axis
    point at P = 0, fitted by sum_k c_k/k P^k (k in powers) with P in A_s = sqrt(n) A_p; a_P = c_2."""
    mQ, mP = grid["active"]
    E = energies["eV_per_cell"]
    pts = [f for f in grid["frames"] if f["tag"].startswith(tag_prefix) and str(f["id"]) in E]
    p0 = min(pts, key=lambda f: abs(f["Q"][mP]))
    Pa = np.array([f["Q"][mP] for f in pts]); Y = np.array([E[str(f["id"])] - E[str(p0["id"])] for f in pts])
    w = np.abs(Pa) <= pmax + 1e-9
    Ps = np.sqrt(nc) * Pa[w]
    A = np.vstack([Ps**k / k for k in powers]).T
    c, *_ = np.linalg.lstsq(A, Y[w], rcond=None)
    r = Y[w] - A @ c
    return float(c[0]), {"n": int(w.sum()), "powers": list(powers), "pmax_A": pmax, "coefficients_As": c.tolist(),
                         "rms_meV": float(np.sqrt(np.mean(r**2)) * 1000), "ids": [f["id"] for f, k in zip(pts, w) if k]}


def f5_meier_fixed_aP(state: dict) -> dict:
    """Variant used for ErMnO3 (compare_meier_final.md): a_P from the P axis (anchors), then the other five
    coefficients on the plane with a_P fixed. Computed in-node, in A_s per cell, following
    demo/ermno3/landau/fit_meier_fixed_aP.py (that script hardcodes a_P, so it cannot be run as is)."""
    cfg, grid, en, dec = state["config"], state["grid"], state["energies"], state["decomposition"]
    fit = cfg["policy"]["fit"]
    ax = fit["aP_axis"]
    mQ, mP = grid["active"]
    nc = float(dec["vectors"]["n_parent_primitive_cells"])
    S = np.sqrt(nc)
    aP, axinfo = axis_aP(grid, en, ax.get("tag_prefix", "anchor_pax"), float(ax["pmax"]), tuple(ax.get("powers", (2, 4, 6))), nc)
    E = en["eV_per_cell"]
    pts = [f for f in grid["frames"] if not f["tag"] and str(f["id"]) in E]
    o = min(pts, key=lambda f: f["Q"][mQ] ** 2 + f["Q"][mP] ** 2)
    Qa = np.array([f["Q"][mQ] for f in pts]); Pa = np.array([f["Q"][mP] for f in pts])
    Y = np.array([E[str(f["id"])] - E[str(o["id"])] for f in pts])
    w = (np.abs(Qa) <= float(fit["qmax"]) + 1e-9) & (np.abs(Pa) <= float(fit["pmax"]) + 1e-9)
    Q, Pp, Y = S * Qa[w], S * Pa[w], Y[w]
    X = design(Q, Pp)
    free = [i for i, k in enumerate(NAMES) if k != "a_P"]
    y = Y - aP * X[:, NAMES.index("a_P")]
    c, *_ = np.linalg.lstsq(X[:, free], y, rcond=None)
    co_s = dict(zip([NAMES[i] for i in free], map(float, c))); co_s["a_P"] = aP
    co_s = {k: co_s[k] for k in NAMES}
    r = y - X[:, free] @ c
    # cross-validation of the plane step with a_P fixed
    idx = np.arange(len(y)) % fit["cv_folds"]; cres = np.empty_like(y)
    for f in range(fit["cv_folds"]):
        tr, te = idx != f, idx == f
        cc, *_ = np.linalg.lstsq(X[tr][:, free], y[tr], rcond=None)
        cres[te] = y[te] - X[te][:, free] @ cc
    qs, dep, cp = derived(co_s, float(np.abs(Q).max()))
    dq = grid["sizing"]["dq"]; dqQ = dq[mQ] if isinstance(dq, dict) else dq
    model = {"fitted": True, "dropped_frames": dropped_frames(state), "kind": "meier_QP", "variant": "a_P fixed from the P axis",
             "script": "in-node (procedure of demo/ermno3/landau/fit_meier_fixed_aP.py; a_P from the P axis as compare_meier_final.md)",
             "modes": [mQ, mP], "per_fu": fit["per_fu"], "energy_unit": "per cell",
             "window": {"qmax_A": float(fit["qmax"]), "pmax_A": float(fit["pmax"])}, "n_fit": int(w.sum()),
             "n_fit_ids": [f["id"] for f, k in zip(pts, w) if k], "aP_axis": axinfo,
             "coefficients_As": co_s, "coefficients_Ap": {k: v * S ** POWER[k] for k, v in co_s.items()}, "n_cells": nc,
             "units": {"a": "eV Å⁻²", "b": "eV Å⁻⁴", "c": "eV Å⁻⁶", "a_P": "eV Å⁻²", "g": "eV Å⁻⁴", "g'": "eV Å⁻⁴"},
             "rms_meV": float(np.sqrt(np.mean(r**2)) * 1000), "max_abs_res_meV": float(np.abs(r).max() * 1000),
             "cv": {"folds": fit["cv_folds"], "rms_meV": float(np.sqrt(np.mean(cres**2)) * 1000), "max_abs_meV": float(np.abs(cres).max() * 1000)},
             "Q_star_A": qs / S, "depth_meV": dep * 1000, "coupled": {"Q_A": cp[0] / S, "P_A": cp[1] / S, "E_meV": cp[2] * 1000},
             "Q_star_As": qs, "coupled_As": [cp[0], cp[1]], "hat_meV_per_cell": -cp[2] * 1000, "grid_dq_A": dqQ}
    return {"model": model, "last_node": "f5"}


def f5_meier(state: dict) -> dict:
    if state["config"]["policy"]["fit"].get("aP_axis"):
        out = f5_meier_fixed_aP(state)
        s = aP_sensitivity(state, f5_meier_fixed_aP, SENS_KEYS_PLANE)
        if s:
            out["model"]["aP_sensitivity"] = s
        return out
    cfg, grid, en, dec = state["config"], state["grid"], state["energies"], state["decomposition"]
    P, fit = from_config(cfg), cfg["policy"]["fit"]
    modes = grid["active"]
    if len(modes) != 2:
        # e.g. after an R5 exclude / anchor_only decision removed the polar axis: the (Q, P) model cannot be fitted;
        # G5 fails with NO_FIT and the decision's measured consequence (anchor energies) is reported with it
        return {"model": {"fitted": False, "kind": "meier_QP", "reason": f"(Q, P) fit needs 2 active modes, got {modes}",
                          "r5_decision": (grid.get("r5") or {}).get("decision") or state.get("overrides", {}).get("f2", {}).get("r5_decision"),
                          "r5_anchors": r5_anchor_report(state), "dropped_frames": dropped_frames(state)},
                "last_node": "f5"}
    mQ, mP = modes
    qmax, pmax = float(fit["qmax"]), float(fit["pmax"])
    wd = P.out(P.run_dir(cfg["thread_id"]), "f5_meier")
    step = P.out(wd, "step4_energy_plane")
    step.mkdir(parents=True, exist_ok=True)
    P.out(step, "grid_spec.json").write_text(json.dumps(
        {"modes": modes, "units": "Ap_A (translation-free)", "child_Ap": {m: grid["certify"]["calibration"][m]["Ap_child"] for m in modes}}))
    P.out(step, "grid_manifest.json").write_text(json.dumps(
        [{"id": f["id"], "ap_A": f["Q"], "tag": f["tag"]} for f in grid["frames"]]))
    ecsv = P.out(wd, "energies.csv")
    with open(ecsv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "energy_eV"])
        for i, e in en["eV_per_cell"].items():
            w.writerow([i, f"{e:.8f}"])
    jout = P.out(wd, "landau_QP.json")
    cmd = [sys.executable, "-I", str(legacy.script(P, "fit_landau_QP.py")), str(wd), "--tag", "plane",
           "--energies", str(ecsv), "--per-fu", str(fit["per_fu"]), "--per-cell", "--qmax", str(qmax),
           "--pmax", str(pmax), "--as-units", "--label", cfg["thread_id"], "--json-out", str(jout)]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "MPLBACKEND": "Agg"}
    pr = subprocess.run(cmd, capture_output=True, text=True, cwd=str(wd), env=env, timeout=600)
    P.out(wd, "fit_landau_QP.stdout.txt").write_text(pr.stdout + pr.stderr)
    if pr.returncode != 0 or not jout.is_file():
        return {"model": {"fitted": False, "kind": "meier_QP", "reason": "fit_landau_QP.py failed",
                          "stderr": pr.stderr[-2000:]}, "last_node": "f5"}
    res = json.loads(jout.read_text())
    nc = float(dec["vectors"]["n_parent_primitive_cells"])
    coef_p = res["coefficients"]
    coef_s = {k: v / np.sqrt(nc) ** POWER[k] for k, v in coef_p.items()}
    Q, Pp, Y, ids = fit_set(grid, en, qmax, pmax)
    X = design(Q, Pp)
    resid = Y - X @ np.array([coef_p[k] for k in NAMES])
    cv_rms, cv_max = kfold_cv(Q, Pp, Y, fit["cv_folds"])
    dq = grid["sizing"]["dq"]
    dqQ = dq[mQ] if isinstance(dq, dict) else dq
    qc, pc, ec = res["coupled"]
    model = {"fitted": True, "dropped_frames": dropped_frames(state), "kind": "meier_QP", "script": "demo/staged_walkthrough/fit_landau_QP.py (unchanged)", "r5_anchors": r5_anchor_report(state),
             "command": " ".join(cmd[2:]), "modes": modes, "per_fu": fit["per_fu"], "energy_unit": "per cell",
             "window": {"qmax_A": qmax, "pmax_A": pmax}, "n_fit": len(Y), "n_fit_ids": ids,
             "coefficients_Ap": coef_p, "coefficients_As": coef_s, "n_cells": nc,
             "units": {"a": "eV Å⁻²", "b": "eV Å⁻⁴", "c": "eV Å⁻⁶", "a_P": "eV Å⁻²", "g": "eV Å⁻⁴", "g'": "eV Å⁻⁴"},
             "rms_meV": res["rms_meV"], "max_abs_res_meV": float(np.abs(resid).max() * 1000),
             "cv": {"folds": fit["cv_folds"], "rms_meV": cv_rms, "max_abs_meV": cv_max},
             "Q_star_A": res["Q_star"], "depth_meV": res["depth"] * 1000,
             "coupled": {"Q_A": qc, "P_A": pc, "E_meV": ec * 1000},
             "Q_star_As": res["Q_star"] * np.sqrt(nc), "coupled_As": [qc * np.sqrt(nc), pc * np.sqrt(nc)],
             "hat_meV_per_cell": -ec * 1000, "grid_dq_A": dqQ,
             "files": {"json": str(jout), "stdout": str(P.out(wd, "fit_landau_QP.stdout.txt"))}}
    return {"model": model, "last_node": "f5"}


SENS_KEYS_PLANE = ("rms_meV", "hat_meV_per_cell", "depth_meV", "Q_star_A")
SENS_KEYS_JOINT = ("rms_meV", "hat_meV_per_fu", "brim_meV_per_fu", "brim_cprime0_meV_per_fu")


def aP_sensitivity(state: dict, fit_fn, keys) -> list[dict]:
    """policy.fit.aP_axis.sensitivity = {pmax: [...], powers: [[2, 4], [2, 4, 6], ...]}: the same two-step fit
    (a_P from the P axis, then the plane or the joint fit with a_P fixed) for every window x powers choice.
    Reported only; the run's model uses the configured choice."""
    import copy
    ax = state["config"]["policy"]["fit"]["aP_axis"]
    sens = ax.get("sensitivity")
    if not sens:
        return []
    out = []
    for pm in sens["pmax"]:
        for pw in sens["powers"]:
            st = copy.deepcopy(state)
            a2 = st["config"]["policy"]["fit"]["aP_axis"]
            a2.pop("sensitivity", None)
            a2["pmax"], a2["powers"] = float(pm), list(pw)
            try:
                m = fit_fn(st)["model"]
            except Exception as exc:          # e.g. too few axis points for the powers
                out.append({"pmax_A": pm, "powers": list(pw), "error": f"{type(exc).__name__}: {exc}"})
                continue
            ai = m["aP_axis"]
            row = {"pmax_A": float(pm), "powers": list(pw), "n_axis": ai["n"], "a_P_As": m["coefficients_As"]["a_P"],
                   "axis_rms_meV": ai["rms_meV"],
                   "published": float(pm) == float(ax["pmax"]) and list(pw) == list(ax.get("powers", [2, 4, 6]))}
            row.update({k: m.get(k) for k in keys})
            out.append(row)
    return out
