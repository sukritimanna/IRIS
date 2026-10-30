"""f6 Skeptic: re-derive every number that goes into the report, by a route independent of the node
that produced it, and record value / re-derived value / tolerance / ok for each.

Independent routes:
  decomposition   ||field|| from the stored mode matrix vs the A_s ISODISTORT printed
  selection       select_modes re-run from the raw amplitudes
  frames          every frame rebuilt from r0 + sum Q e and its space group recounted (spglib)
  replay          every linked energy re-read from the CSV by stored id
  Landau fit      solved again by QR (not lstsq) on a fit set rebuilt from the frames
  ring            minimised again per angle with a bounded scalar optimiser (not the script's grid search)
  per f.u.        N atoms / atoms per formula unit from the system file
"""
from __future__ import annotations

import csv
import json

import numpy as np

from ..paths import from_config
from ..rules.select_modes import select_for
from ..engines.frames import frame_frac
from .f5_analyst import design, fit_set


def _row(name, value, rederived, tol, unit=""):
    ok = (value == rederived) if tol is None else (
        value is not None and rederived is not None and abs(float(value) - float(rederived)) <= tol)
    return {"name": name, "value": value, "rederived": rederived, "tol": tol, "unit": unit, "ok": bool(ok)}


def f6_skeptic(state: dict) -> dict:
    cfg, dec, sel, grid = state["config"], state["decomposition"], state["selection"], state["grid"]
    jobs, en, model = state["jobs"], state["energies"], state["model"]
    if grid.get("kind") == "six_component":               # BiFeO3 6D (nodes/f6_grid6)
        from .f6_grid6 import six_report
        return {"report": six_report(state), "last_node": "f6"}
    if grid.get("kind") == "plane2":                       # two-component plane (nodes/f6_plane2)
        from .f6_plane2 import plane2_report
        return {"report": plane2_report(state), "last_node": "f6"}
    if grid.get("kind") == "path":                         # straight-line path (nodes/f6_path)
        from .f6_path import path_report
        return {"report": path_report(state), "last_node": "f6"}
    P, pol = from_config(cfg), cfg["policy"]
    rows = []
    from pymatgen.core import Lattice, Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    # decomposition: amplitudes
    # n_cells re-derived: spglib primitive of the undistorted frame r0 (f1 used the parent CIF)
    r0s0 = Structure(Lattice(dec["vectors"]["r0"]["lattice"]), dec["vectors"]["r0"]["species"], dec["vectors"]["r0"]["frac"])
    n_cells = len(r0s0) / len(SpacegroupAnalyzer(r0s0, symprec=1e-3).find_primitive())
    rows.append(_row("parent primitive cells in the frame", dec["vectors"]["n_parent_primitive_cells"], n_cells, 1e-9))
    for ir, v in dec["irreps"].items():
        ap = dec["vectors"]["norm_A"][ir] / np.sqrt(n_cells)
        rows.append(_row(f"A_p {ir}", abs(v["Ap"]), ap, 2e-4, "Å"))
        rows.append(_row(f"A_s {ir}", abs(v["As"]), ap * np.sqrt(dec["isodistort"]["s"]), 3e-4, "Å"))

    # selection
    again = select_for(dec, pol, state.get("overrides", {}).get("f2", {}).get("r5_decision"))
    rows.append(_row("active set", sel["active"], again["active"], None))
    rows.append(_row("primaries", sel["primaries"], again["primaries"], None))
    rows.append(_row("held at zero", sel["held_at_zero"], again["held_at_zero"], None))
    rows.append(_row("c1 intersection SG", sel["c1_intersection_sg"], again["c1_intersection_sg"], None))

    # frames: rebuild and recount
    r0 = dec["vectors"]["r0"]
    lat, sp, f0 = Lattice(r0["lattice"]), r0["species"], np.array(r0["frac"])
    vec = {ir: np.array(v) for ir, v in grid["vectors"].items()}
    count, pcount, f2_pcount = {}, {}, {}
    pol = grid.get("polar")
    if pol:
        # second component re-derived by another route: e2 = (T e1 - T^2 e1) / sqrt 3 (T = the 120 deg translation)
        L_ = np.array(r0["lattice"]); t = np.array(pol["translation"]); e1 = vec[pol["irrep"]]

        def shift(e, tt):
            out = np.zeros_like(e)
            for j in range(len(f0)):
                d = f0 - (f0[j] + tt); d -= np.round(d)
                out[int(np.argmin(np.linalg.norm(d @ L_, axis=1)))] = e[j]
            return out
        e2_alt = (shift(e1, t) - shift(e1, 2 * t)) / np.sqrt(3)
        rows.append(_row(f"second {pol['irrep']} component: max |e2 - (T e1 - T² e1)/√3|", 0.0,
                         float(np.abs(e2_alt - vec[f"{pol['irrep']}@c2"]).max()), 1e-9))
    for fr in grid["frames"]:
        if fr["tag"] and not fr.get("polar"):
            continue
        s = Structure(lat, sp, frame_frac(fr, f0, vec, grid["active"]))
        g = SpacegroupAnalyzer(s, symprec=1e-2).get_space_group_number()
        if fr.get("polar"):
            pcount[g] = pcount.get(g, 0) + 1
            f2_pcount[fr["sg"]] = f2_pcount.get(fr["sg"], 0) + 1
            continue
        count[g] = count.get(g, 0) + 1
    for g in sorted(set(pcount) | set(f2_pcount)):
        rows.append(_row(f"polar frames in SG {g}", f2_pcount.get(g, 0), pcount.get(g, 0), None))
    f2_count = {}
    for fr in grid["frames"]:
        if not fr["tag"]:
            f2_count[fr["sg"]] = f2_count.get(fr["sg"], 0) + 1
    for g in sorted(set(count) | set(f2_count)):
        rows.append(_row(f"grid frames in SG {g}", f2_count.get(g, 0), count.get(g, 0), None))
    rows.append(_row("grid frames (m^n)", grid["n_grid"], sum(count.values()), None))

    # replay: energies re-read from the CSV by stored id
    with open(P.repo("energies_csv")) as fh:
        csv_e = {int(r["id"]): float(r["energy_eV"]) for r in csv.DictReader(fh)}
    for tag, x in (jobs.get("extra_references") or {}).items():
        with open(P.repo_root / x["energies"]) as fh:
            csv_e.update({f"{tag}:{int(r['id'])}": float(r["energy_eV"]) for r in csv.DictReader(fh)})
    bad = [k for k, v in jobs["matched"].items() if csv_e.get(v["stored_id"]) != en["eV_per_cell"].get(k)]
    rows.append(_row("frames matched to stored structures", jobs["n_matched"], len(grid["frames"]), None))
    rows.append(_row("linked energies equal to the CSV", 0, len(bad), None))

    # per f.u.
    sysj = json.loads(P.repo("system_json").read_text())
    apfu = sum(sysj["composition"].values())
    rows.append(_row("formula units per cell", model["per_fu"], len(sp) // apfu, None))

    if model.get("kind") == "surface":
        return {"report": _surface_report(rows, state, csv_e, count), "last_node": "f6"}
    if model.get("kind") == "meier_QP":
        return {"report": _meier_report(rows, state, csv_e, count), "last_node": "f6"}
    if model.get("kind") == "meier_joint":
        return {"report": _joint_report(rows, state, csv_e, count), "last_node": "f6"}

    # Landau fit by QR on an independently rebuilt fit set
    A, B, y, ids = fit_set(grid, en, model["rmax_A"], len(sp) // apfu)
    X = design(A, B)
    Qm, Rm = np.linalg.qr(X)
    coef = np.linalg.solve(Rm, Qm.T @ y)
    resid = y - X @ coef
    rows.append(_row("nodes in fit (r ≤ rmax)", model["n_fit"], len(y), None))
    for n_, c in zip(["a1", "b1", "c1", "a2", "b2", "c2", "λ", "μ"], coef):
        rows.append(_row(f"Landau {n_}", model["coefficients"][n_], float(c), 1e-6 + 1e-6 * abs(c)))
    rows.append(_row("RMS residual", model["rms_meV"], float(np.sqrt(np.mean(resid**2)) * 1000), 1e-6, "meV/f.u."))

    # ring of minima by a different minimiser
    from scipy.optimize import minimize_scalar
    a1, b1, c1, a2, b2, c2, lam, mu = coef

    def F(r, t):
        Aa, Bb = r * np.cos(t), r * np.sin(t)
        return (a1 / 2 * Aa**2 + b1 / 4 * Aa**4 + c1 / 6 * Aa**6 + a2 / 2 * Bb**2 + b2 / 4 * Bb**4
                + c2 / 6 * Bb**6 + lam / 2 * Aa**2 * Bb**2 + mu / 6 * (Aa**4 * Bb**2 + Aa**2 * Bb**4))
    th = np.radians(np.arange(0, 360, 1.0))
    rr, ee = [], []
    for t in th:
        o = minimize_scalar(lambda r: F(r, t), bounds=(0.02, model["rmax_A"] * 1.05), method="bounded",
                            options={"xatol": 1e-7})
        rr.append(o.x)
        ee.append(o.fun)
    rr, ee = np.array(rr), np.array(ee)
    ring = model["ring"]
    rows.append(_row("ring radius min", ring["radius_min_A"], round(float(rr.min()), 2), 0.011, "Å"))
    rows.append(_row("ring radius max", ring["radius_max_A"], round(float(rr.max()), 2), 0.011, "Å"))
    rows.append(_row("ring depth below parent", ring["depth_meV"], float(-ee.min() * 1000), 0.05, "meV/f.u."))
    rows.append(_row("ring corrugation", ring["corrugation_meV"], float((ee.max() - ee.min()) * 1000), 0.05, "meV/f.u."))

    # DFT-grid ring (ring_profile.py) re-derived with scipy.interpolate.interpn on the f4 energies
    rg = model.get("ring_dft_grid", {})
    if rg.get("ok"):
        from scipy.interpolate import interpn
        E = en["eV_per_cell"]
        modes = grid["active"]
        pts = [f for f in grid["frames"] if str(f["id"]) in E and not f["tag"]]
        xs = sorted({round(f["Q"][modes[0]], 10) for f in pts})
        ys = sorted({round(f["Q"][modes[1]], 10) for f in pts})
        Z = np.full((len(xs), len(ys)), np.nan)
        for f in pts:
            Z[xs.index(round(f["Q"][modes[0]], 10)), ys.index(round(f["Q"][modes[1]], 10))] = E[str(f["id"])]
        Z = (Z - E[en["origin_id"]]) * 1000 / model["per_fu"]
        gm = min(pts, key=lambda f: E[str(f["id"])])
        r_ring = float(np.hypot(gm["Q"][modes[0]], gm["Q"][modes[1]]))
        thd = np.radians(np.linspace(0, 360, 361))
        rr2 = np.linspace(0.3, min(max(xs), max(ys)) * 0.98, 120)
        ev = lambda xy: interpn((xs, ys), Z, xy, bounds_error=False, fill_value=np.nan)
        ering = ev(np.c_[r_ring * np.cos(thd), r_ring * np.sin(thd)])
        rmin, emin = [], []
        for t in thd:
            er = ev(np.c_[rr2 * np.cos(t), rr2 * np.sin(t)])
            k = int(np.nanargmin(er))
            rmin.append(rr2[k])
            emin.append(er[k])
        rows.append(_row("DFT-grid ring radius (grid minimum)", rg["ring_radius_A"], round(r_ring, 2), 0.006, "Å"))
        rows.append(_row("DFT-grid ring corrugation", rg["corrugation_meV"], round(float(np.nanmax(ering) - np.nanmin(ering)), 1), 0.051, "meV/f.u."))
        rows.append(_row("DFT-grid radial-minimum radius min", rg["radial_min_radius_A"][0], round(float(min(rmin)), 2), 0.006, "Å"))
        rows.append(_row("DFT-grid radial-minimum radius max", rg["radial_min_radius_A"][1], round(float(max(rmin)), 2), 0.006, "Å"))
        rows.append(_row("DFT-grid valley floor min", rg["valley_floor_meV"][0], round(float(np.nanmin(emin)), 1), 0.051, "meV/f.u."))
        rows.append(_row("DFT-grid valley floor max", rg["valley_floor_meV"][1], round(float(np.nanmax(emin)), 1), 0.051, "meV/f.u."))

    # D4 scans re-derived: energies re-read from the stored scan CSVs by stored id, quartic by QR, the minimum
    # from the roots of dE/da (f5: polyfit and a dense scan)
    d4 = model.get("d4")
    if d4:
        for sc in d4["scans"]:
            tag = f"d4_{sc['name']}"
            fr = [f for f in grid["frames"] if f["tag"] == tag]
            a = np.array([f["Q"][sc["irrep"]] for f in fr])
            e = np.array([csv_e[jobs["matched"][str(f["id"])]["stored_id"]] for f in fr])
            o = np.argsort(a); a, e = a[o], e[o]
            y = (e - e[int(np.argmin(np.abs(a)))]) * 1000 / model["per_fu"]
            V = np.vstack([a ** k for k in range(5)]).T
            Qd, Rd = np.linalg.qr(V)
            c = np.linalg.solve(Rd, Qd.T @ y)                      # c0 + c1 a + ... + c4 a^4
            dpoly = np.array([4 * c[4], 3 * c[3], 2 * c[2], c[1]])
            cand = [r.real for r in np.roots(dpoly) if abs(r.imag) < 1e-9 and a.min() <= r.real <= a.max()] + [a.min(), a.max()]
            Ev = lambda x: c[0] + c[1] * x + c[2] * x**2 + c[3] * x**3 + c[4] * x**4
            xs_ = min(cand, key=Ev)
            rows.append(_row(f"D4 {sc['name']}: curvature (meV/Å²/f.u.)", sc["deg4"]["curvature_meV_per_A2"], float(2 * c[2]), 1e-6, "meV/Å²"))
            rows.append(_row(f"D4 {sc['name']}: relaxed {sc['irrep']} (Å)", round(sc["deg4"]["a_star_A"], 4), round(float(xs_), 4), 2e-4, "Å"))
            rows.append(_row(f"D4 {sc['name']}: energy released (meV/f.u.)", sc["deg4"]["gain_meV"], float(Ev(xs_) - c[0]), 1e-4, "meV/f.u."))
        rows.append(_row("D4 reference (ring corrugation of the fit, meV/f.u.)", d4["reference_meV"], model["ring"]["corrugation_meV"], 1e-9, "meV/f.u."))

    report = {"rows": rows, "n_numbers": len(rows), "n_ok": sum(r["ok"] for r in rows),
              "summary": {
                  "decomposition_Ap": {ir: v["Ap"] for ir, v in dec["irreps"].items()},
                  "active": sel["active"], "held_at_zero": sel["held_at_zero"],
                  "grid": {"m": grid["sizing"]["m"], "n": grid["sizing"]["n"], "N": grid["n_grid"],
                           "anchors": grid["n_anchors"], "sg_count_grid": {str(k): v for k, v in sorted(count.items())}},
                  "replay": {"matched": jobs["n_matched"], "of": jobs["n_frames"], "max_dev_frac": jobs["max_dev_frac"]},
                  "landau": {**{k: model["coefficients"][k] for k in ("a1", "a2", "λ")},
                             "rms_meV": model["rms_meV"], "cv_rms_meV": model["cv"]["rms_meV"], "n_fit": model["n_fit"]},
                  "ring": ring, "ring_dft_grid": rg}}
    return {"report": report, "last_node": "f6"}


def _surface_report(rows, state, csv_e, count):
    """Surface numbers re-derived from the CSV energies (by stored id) with a dict of nodes keyed by
    the integer grid index, scipy interpn for the off-node child point, and A_s from A_p via the
    ISODISTORT supercell size s re-read from the stored subgroup (not from f5)."""
    from scipy.interpolate import interpn
    cfg, dec, grid, jobs, model = state["config"], state["decomposition"], state["grid"], state["jobs"], state["model"]
    m0, m1 = grid["active"]
    dq = grid["sizing"]["dq"]
    k = 1000.0 / model["per_fu"]
    node, anchor = {}, {}
    for fr in grid["frames"]:
        rec = jobs["matched"].get(str(fr["id"]))
        e = csv_e.get(rec["stored_id"]) if rec else None
        if fr["tag"]:
            anchor[fr["tag"][len("anchor_"):]] = e
        elif e is not None:
            node[(int(round(fr["Q"][m0] / dq)), int(round(fr["Q"][m1] / dq)))] = e
    e_min = min(list(node.values()) + [v for v in anchor.values() if v is not None])
    rel = {ij: (e - e_min) * k for ij, e in node.items()}
    rows.append(_row("surface nodes with energy", model["n_nodes"], len(rel), None))
    rows.append(_row("E_min (eV/cell)", model["E_min_eV_per_cell"], e_min, 1e-9, "eV"))
    rows.append(_row("E range above E_min", model["range_meV"], max(rel.values()), 1e-6, "meV/f.u."))
    lo = min(rel.values())
    mins = sorted([ij for ij, v in rel.items() if abs(v - lo) < 1e-9])
    rows.append(_row("grid minima (A_p, Å)", sorted([[round(x, 6) for x in mn["Ap"]] for mn in model["minima"]]),
                     sorted([[round(i * dq, 6), round(j * dq, 6)] for i, j in mins]), None))
    from ..engines.stored_isodistort import load
    from ..paths import from_config
    s_iso = float(load(str(from_config(cfg).repo("isodistort_stored"))).subgroup()["s"])
    rows.append(_row("supercell size s (A_s = A_p √s)", model["s"], s_iso, 0))
    rows.append(_row("grid minima (A_s, Å)", sorted([mn["As"] for mn in model["minima"]]),
                     sorted([[round(i * dq * np.sqrt(s_iso), 6), round(j * dq * np.sqrt(s_iso), 6)] for i, j in mins]), None))
    mx = max(abs(v - rel[(-i, j)]) for (i, j), v in rel.items() if (-i, j) in rel)
    my = max(abs(v - rel[(i, -j)]) for (i, j), v in rel.items() if (i, -j) in rel)
    rows.append(_row("mirror max|E(x,y)-E(-x,y)|", model["mirror_meV"]["x"], mx, 1e-6, "meV/f.u."))
    rows.append(_row("mirror max|E(x,y)-E(x,-y)|", model["mirror_meV"]["y"], my, 1e-6, "meV/f.u."))
    ph = model["phases"]
    rows.append(_row("E parent (Q = 0)", ph["parent"]["E_meV"], rel[(0, 0)], 1e-6, "meV/f.u."))
    for n, e in anchor.items():
        rows.append(_row(f"E {n} (DFT anchor)", ph[n]["E_meV"], None if e is None else (e - e_min) * k, 1e-6, "meV/f.u."))
    ks = sorted({i for i, _ in rel})
    xs = np.array(ks) * dq
    Z = np.array([[rel.get((i, j), np.nan) for j in ks] for i in ks])
    cx, cy = abs(dec["irreps"][m0]["Ap"]), abs(dec["irreps"][m1]["Ap"])
    rows.append(_row("E child at its A_p (bilinear)", ph["child"]["E_meV"],
                     float(interpn((xs, xs), Z, [[cx, cy]], method="linear")[0]), 1e-6, "meV/f.u."))
    sc = model.get("script", {})
    if sc.get("ok"):
        rows.append(_row("script: mirror x (printed to 3 dp)", sc["mirror_x_meV"], round(mx, 3), 6e-4, "meV/f.u."))
        for n in ("cmcm", "cmce", "a21am"):
            if n in anchor and anchor[n] is not None:
                rows.append(_row(f"script: E {n} (printed to 2 dp)", sc[f"{n}_meV"], round((anchor[n] - e_min) * k, 2), 6e-3, "meV/f.u."))
    return {"rows": rows, "n_numbers": len(rows), "n_ok": sum(r["ok"] for r in rows),
            "summary": {"decomposition_Ap": {ir: v["Ap"] for ir, v in dec["irreps"].items()},
                        "active": state["selection"]["active"], "held_at_zero": state["selection"]["held_at_zero"],
                        "policy_overrides": state["selection"].get("policy_overrides", []),
                        "grid": {"m": grid["sizing"]["m"], "n": grid["sizing"]["n"], "N": grid["n_grid"],
                                 "anchors": grid["n_anchors"], "sg_count_grid": {str(k_): v for k_, v in sorted(count.items())}},
                        "replay": {"matched": jobs["n_matched"], "of": jobs["n_frames"], "max_dev_frac": jobs["max_dev_frac"]},
                        "surface": {"range_meV": model["range_meV"], "minima": model["minima"], "phases": ph,
                                    "mirror_meV": model["mirror_meV"]}}}


def _meier_report(rows, state, csv_e, count):
    """(Q, P) fit re-derived: fit set rebuilt from the frames with energies re-read from the CSV by stored id,
    solved by QR (the script uses lstsq); A_s conversion with n_cells from spglib on r0; Q*, depth and the
    coupled minimum by scipy optimisers (the script scans a 2000-point Q grid)."""
    from scipy.optimize import minimize, minimize_scalar
    from pymatgen.core import Lattice, Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    from .f5_meier import NAMES, POWER, design
    dec, grid, jobs, model, sel = state["decomposition"], state["grid"], state["jobs"], state["model"], state["selection"]
    mQ, mP = grid["active"]
    E = {}
    for fr in grid["frames"]:
        rec = jobs["matched"].get(str(fr["id"]))
        if rec and rec["stored_id"] in csv_e:
            E[fr["id"]] = csv_e[rec["stored_id"]]
    fixed = bool(model.get("aP_axis"))
    fr = [f for f in grid["frames"] if f["id"] in E and not (fixed and f["tag"])]   # fixed-a_P variant: plane = non-anchor frames
    o = min(fr, key=lambda f: f["Q"][mQ] ** 2 + f["Q"][mP] ** 2)
    win = model["window"]
    keep = [f for f in fr if abs(f["Q"][mQ]) <= win["qmax_A"] + 1e-9 and abs(f["Q"][mP]) <= win["pmax_A"] + 1e-9]
    Q = np.array([f["Q"][mQ] for f in keep]); P = np.array([f["Q"][mP] for f in keep])
    Y = np.array([E[f["id"]] - E[o["id"]] for f in keep])
    r0 = dec["vectors"]["r0"]
    r0s = Structure(Lattice(r0["lattice"]), r0["species"], r0["frac"])
    nc = len(r0s) / len(SpacegroupAnalyzer(r0s, symprec=1e-3).find_primitive())
    rows.append(_row("nodes in fit window", model["n_fit"], len(Y), None))
    if fixed:
        ax = model["aP_axis"]
        pa = [f for f in grid["frames"] if f["id"] in ax["ids"]]
        p0 = min(pa, key=lambda f: abs(f["Q"][mP]))
        Ps = np.sqrt(nc) * np.array([f["Q"][mP] for f in pa]); Ya = np.array([E[f["id"]] - E[p0["id"]] for f in pa])
        A = np.vstack([Ps**k / k for k in ax["powers"]]).T
        Qa, Ra = np.linalg.qr(A); ca = np.linalg.solve(Ra, Qa.T @ Ya)
        rows.append(_row("P-axis points used for a_P", ax["n"], len(pa), None))
        aP_s = float(ca[0])
        X = design(np.sqrt(nc) * Q, np.sqrt(nc) * P)
        free = [i for i, k in enumerate(NAMES) if k != "a_P"]
        y = Y - aP_s * X[:, NAMES.index("a_P")]
        Qm, Rm = np.linalg.qr(X[:, free]); cf = np.linalg.solve(Rm, Qm.T @ y)
        r = y - X[:, free] @ cf
        co_s = dict(zip([NAMES[i] for i in free], cf)); co_s["a_P"] = aP_s
        co = np.array([co_s[k] * np.sqrt(nc) ** POWER[k] for k in NAMES])          # back to A_p
    else:
        X = design(Q, P)
        Qm, Rm = np.linalg.qr(X)
        co = np.linalg.solve(Rm, Qm.T @ Y)
        r = Y - X @ co
    for nm, c in zip(NAMES, co):
        rows.append(_row(f"{nm} (A_p, eV/cell)", model["coefficients_Ap"][nm], float(c), 1e-6 + 1e-6 * abs(c)))
        cs = float(c) / np.sqrt(nc) ** POWER[nm]
        rows.append(_row(f"{nm} (A_s, eV/cell)", model["coefficients_As"][nm], cs, 1e-6 + 1e-6 * abs(cs)))
    rows.append(_row("RMS residual", model["rms_meV"], float(np.sqrt(np.mean(r**2)) * 1000), 1e-6, "meV/cell"))
    a, b, c, aP, g, gp = co
    Fq = lambda q: a / 2 * q**2 + b / 4 * q**4 + c / 6 * q**6
    qmax_scan = float(np.abs([f["Q"][mQ] for f in fr]).max())
    o1 = minimize_scalar(Fq, bounds=(0.01, qmax_scan), method="bounded", options={"xatol": 1e-9})
    rows.append(_row("K3 well Q* (A_p)", model["Q_star_A"], float(o1.x), 1e-3, "Å"))
    rows.append(_row("well depth", model["depth_meV"], float(o1.fun * 1000), 0.05, "meV/cell"))
    Fqp = lambda v: Fq(v[0]) + aP / 2 * v[1] ** 2 - g * v[0] ** 3 * v[1] + gp / 2 * v[0] ** 2 * v[1] ** 2
    o2 = minimize(Fqp, x0=[model["coupled"]["Q_A"] * 1.05, 0.0], method="Nelder-Mead", options={"xatol": 1e-9, "fatol": 1e-12})
    cp = model["coupled"]
    rows.append(_row("coupled minimum Q (A_p)", cp["Q_A"], float(o2.x[0]), 1e-3, "Å"))
    rows.append(_row("coupled minimum P (A_p)", cp["P_A"], float(o2.x[1]), 1e-3, "Å"))
    rows.append(_row("hat height (parent - coupled min)", model["hat_meV_per_cell"], float(-o2.fun * 1000), 0.05, "meV/cell"))
    return {"rows": rows, "n_numbers": len(rows), "n_ok": sum(x["ok"] for x in rows),
            "summary": {"decomposition_Ap": {ir: v["Ap"] for ir, v in dec["irreps"].items()},
                        "active": sel["active"], "held_at_zero": sel["held_at_zero"],
                        "grid": {"m": grid["sizing"]["m"], "n": grid["sizing"]["n"], "N": grid["n_grid"],
                                 "anchors": grid["n_anchors"], "sg_count_grid": {str(k): v for k, v in sorted(count.items())}},
                        "replay": {"matched": jobs["n_matched"], "of": jobs["n_frames"], "max_dev_frac": jobs["max_dev_frac"],
                                   "max_rigid_shift_A": jobs.get("max_rigid_shift_A")},
                        "meier_QP": {"coefficients_As": model["coefficients_As"], "rms_meV": model["rms_meV"],
                                     "cv_rms_meV": model["cv"]["rms_meV"], "n_fit": model["n_fit"],
                                     "Q_star_As": model["Q_star_As"], "coupled_As": model["coupled_As"],
                                     "hat_meV_per_cell": model["hat_meV_per_cell"]}}}


def _joint_report(rows, state, csv_e, count):
    """Joint plane + hat fit re-derived: rows rebuilt from the frames with energies re-read from the CSVs by
    stored id, a_P (if fixed) from the P axis by QR, the fit by QR; hat and brim by a bounded scalar minimiser
    per direction (the node scans a Q grid); n_cells from spglib on r0."""
    from scipy.optimize import minimize_scalar
    from pymatgen.core import Lattice, Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    dec, grid, jobs, model, sel, cfg = (state[k] for k in ("decomposition", "grid", "jobs", "model", "selection", "config"))
    fit, joint = cfg["policy"]["fit"], cfg["policy"]["fit"]["joint"]
    mQ, mP = grid["active"]
    r0 = dec["vectors"]["r0"]
    r0s = Structure(Lattice(r0["lattice"]), r0["species"], r0["frac"])
    nc = len(r0s) / len(SpacegroupAnalyzer(r0s, symprec=1e-3).find_primitive())
    S = np.sqrt(nc)
    E = {}
    for fr in grid["frames"]:
        rec = jobs["matched"].get(str(fr["id"]))
        if rec is not None and rec["stored_id"] in csv_e:
            E[fr["id"]] = csv_e[rec["stored_id"]]
    tag = (grid.get("polar") or {}).get("tag", "hat")
    plane = [f for f in grid["frames"] if not f["tag"] and f["id"] in E]
    E0 = E[min(plane, key=lambda f: abs(f["Q"][mQ]) + abs(f["Q"][mP]))["id"]]
    Q, T, P, Y, src = [], [], [], [], []
    for f in plane + [f for f in grid["frames"] if f["tag"] == tag and f["id"] in E]:
        polar = f["tag"] == tag
        q, p = f["Q"][mQ], f["Q"][mP]
        if not polar and q < 0:
            q, t = -q, np.pi / 3
        else:
            t = np.radians(f.get("phi_deg", 0.0)) if polar else 0.0
        pm = joint["pmax_hat"] if polar else joint["pmax_plane"]
        if q <= joint["qmax"] + 1e-9 and abs(p) <= pm + 1e-9:
            Q.append(S * q); T.append(t); P.append(S * p); Y.append(E[f["id"]] - E0); src.append(int(polar))
    Q, T, P, Y, src = map(np.array, (Q, T, P, Y, src))
    rows.append(_row("joint fit nodes (plane)", model["n_fit_plane"], int((src == 0).sum()), None))
    rows.append(_row("joint fit nodes (hat)", model["n_fit_hat"], int((src == 1).sum()), None))
    cols = {"a": Q**2 / 2, "b": Q**4 / 4, "c": Q**6 / 6, "a_P": P**2 / 2, "g": -(Q**3) * P * np.cos(3 * T),
            "g'": Q**2 * P**2 / 2, "c'": Q**6 / 6 * np.cos(6 * T)}
    if model.get("aP_axis"):
        ax = model["aP_axis"]
        pa = [f for f in grid["frames"] if f["id"] in ax["ids"]]
        p0 = min(pa, key=lambda f: abs(f["Q"][mP]))
        Pa = S * np.array([f["Q"][mP] for f in pa]); Ya = np.array([E[f["id"]] - E[p0["id"]] for f in pa])
        A = np.vstack([Pa**k / k for k in ax["powers"]]).T
        Qa, Ra = np.linalg.qr(A); aP = float(np.linalg.solve(Ra, Qa.T @ Ya)[0])
        rows.append(_row("a_P from the P axis (A_s, eV/cell)", model["coefficients_As"]["a_P"], aP, 1e-9))
        names = [k for k in cols if k != "a_P"]; y = Y - aP * cols["a_P"]
    else:
        names, y, aP = list(cols), Y, None
    X = np.vstack([cols[k] for k in names]).T
    Qm, Rm = np.linalg.qr(X); c = np.linalg.solve(Rm, Qm.T @ y); r = y - X @ c
    co = dict(zip(names, map(float, c)))
    if aP is not None:
        co["a_P"] = aP
    for k in ["a", "b", "c", "c'", "a_P", "g", "g'"]:
        rows.append(_row(f"{k} (A_s, eV/cell)", model["coefficients_As"][k], co[k], 1e-6 + 1e-6 * abs(co[k])))
    rows.append(_row("joint RMS residual", model["rms_meV"], float(np.sqrt(np.mean(r**2)) * 1000), 1e-6, "meV/cell"))
    from .f5_joint import model_F
    lo, hi, _n = model["brim_q_scan_As"]
    m0 = minimize_scalar(lambda q: model_F(co, q, 0.0), bounds=(lo, hi), method="bounded", options={"xatol": 1e-9})
    m30 = minimize_scalar(lambda q: model_F(co, q, np.pi / 6), bounds=(lo, hi), method="bounded", options={"xatol": 1e-9})
    pf = model["per_fu"]
    rows.append(_row("hat height (meV/f.u.)", model["hat_meV_per_fu"], float(-m0.fun * 1000 / pf), 0.05, "meV/f.u."))
    rows.append(_row("brim barrier, Q and P relaxed (meV/f.u.)", model["brim_meV_per_fu"], float((m30.fun - m0.fun) * 1000 / pf), 0.05, "meV/f.u."))
    rows.append(_row("coupled minimum Q at Phi = 0 (A_s)", model["coupled_As"][0], float(m0.x), 2e-3, "Å"))
    return {"rows": rows, "n_numbers": len(rows), "n_ok": sum(x["ok"] for x in rows),
            "summary": {"active": sel["active"], "polar_grid": model.get("polar_grid"),
                        "grid": {"m": grid["sizing"]["m"], "n": grid["sizing"]["n"], "N": grid["n_grid"],
                                 "anchors": grid["n_anchors"], "sg_count_grid": {str(k_): v for k_, v in sorted(count.items())}},
                        "replay": {"matched": jobs["n_matched"], "of": jobs["n_frames"], "max_dev_frac": jobs["max_dev_frac"]},
                        "meier_joint": {"coefficients_As": model["coefficients_As"], "rms_meV": model["rms_meV"],
                                        "n_fit": model["n_fit"], "hat_meV_per_fu": model["hat_meV_per_fu"],
                                        "brim_meV_per_fu": model["brim_meV_per_fu"]}}}
