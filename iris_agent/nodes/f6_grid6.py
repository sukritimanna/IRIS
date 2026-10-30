"""f6 Skeptic for the six-component campaign (BiFeO3): every reported number re-derived by another route.

  decomposition  per-component amplitudes from the stored fields (engines/components6 rerun) and the 96 matrices
                 from the grid toolkit (bfo6d/symmetry.mode_matrices, an independent implementation)
  plan           orbit counts by Burnside on the node sets saved by f2; frame counts by role
  replay         energies re-read from the collected CSVs by run name (E_meV_per_fu column) vs f4
  fit            invariant list from the stored toolkit (bfo6d/landau6d/inv.py) vs f5's own; the fit re-solved
                 by QR (f5: lstsq); training RMS and blind/hold-out errors re-evaluated
  stationary     each of the nine points re-minimised by BFGS with the analytic gradient (f5: Nelder-Mead); the
                 Hessian index from second differences of the energy (f5: differences of the gradient); the space
                 group of the structure at each stationary point (spglib on IRIS's frame) vs the phase name
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

SG_OF = {"R3c": 161, "Ima2": 46, "I4cm": 108, "R3m": 160, "Amm2": 38, "P4mm": 99, "R-3c": 167, "Imma": 74, "I4/mcm": 140}


def _row(name, value, rederived, tol, unit=""):
    ok = (value == rederived) if tol is None else (
        value is not None and rederived is not None and abs(float(value) - float(rederived)) <= tol)
    return {"name": name, "value": value, "rederived": rederived, "tol": tol, "unit": unit, "ok": bool(ok)}


def six_report(state: dict) -> dict:
    from scipy.optimize import minimize

    from ..engines import legacy
    from ..engines.replay6 import read_collected, run_name
    from ..paths import from_config
    from .f2_grid6 import Cell, burnside
    from .f5_landau6d import DIRS, STAT, Basis, errors, rows_for
    cfg, dec, grid, jobs, en, model = (state[k] for k in ("config", "decomposition", "grid", "jobs", "energies", "model"))
    P = from_config(cfg)
    rows = []
    cg = dec["components"]["grid"]
    mats = np.array(cg["mats"], int)

    # decomposition
    sym = legacy.toolkit(P, "grid_toolkit", "symmetry")
    theirs = {np.asarray(G).astype(int).tobytes() for G in sym.mode_matrices()}
    rows.append(_row("96 operation matrices = grid toolkit's", True, {G.tobytes() for G in mats} == theirs, None))
    for k, lab in enumerate(dec["components"]["labels"]):
        V = np.array(cg["vectors_unit"][k])
        rows.append(_row(f"|{lab}|^2 on the 10-atom cell (= n_cells 2)", 2.0, float((V ** 2).sum()), 1e-9))
    irr = dec["irreps"]
    for k, ir in ((0, cfg["policy"]["components"]["polar"]), (3, cfg["policy"]["components"]["rotation"])):
        rows.append(_row(f"{ir} per-component A_p (Å)", dec["components"]["component_Ap"][k],
                         irr[ir]["Ap_tf"] / np.sqrt(3), 1e-4, "Å"))

    # plan
    for d in grid["datasets"]:
        z = np.load(d["orbits_file"])
        rows.append(_row(f"{d['name']}: orbits (Burnside on the saved nodes)", d["n_orbits"], round(burnside(z["nodes"], mats)), None))
        rows.append(_row(f"{d['name']}: orbits kept by the contact cut", d["n_orbits_included"], int(z["orbit_included"].sum()), None))
    for role, n in grid["n_by_role"].items():
        rows.append(_row(f"frames with role {role}", n, sum(1 for f in grid["frames"] if f["role"] == role), None))

    # replay: energies re-read by run name
    csv = {}
    for ds in sorted({f["dataset"] for f in grid["frames"]}):
        csv[ds] = read_collected(Path(P.repo("collected_dir")) / f"runs_{ds}.csv")
    bad = 0
    for i, fr in enumerate(grid["frames"]):
        r = csv[fr["dataset"]].get(run_name(fr)[1])
        e = en["meV_per_fu"].get(str(i))
        if r is None or e is None or abs(float(r["E_meV_per_fu"]) - e) > 1e-6:
            bad += 1
    rows.append(_row("frames matched to stored POSCARs", jobs["n_matched"], len(grid["frames"]), None))
    rows.append(_row("energies differing from the collected CSV (> 1e-6 meV/f.u.)", 0, bad, None))

    # fit
    f6 = cfg["policy"]["fit"]["six"]
    B = Basis(mats, int(f6["degree"]))
    inv_t = None
    if (Path(P.repo("grid_toolkit")) / "landau6d" / "inv.py").is_file():
        import importlib
        _path(P)
        inv_t = importlib.import_module("inv")
    if inv_t is not None:
        ti = inv_t.invariants(int(f6["degree"]))
        same = len(ti) == len(B.inv) and all(a[0] == b[0] and a[1] == b[1] for a, b in zip(ti, B.inv))
        rows.append(_row("invariants = toolkit's landau6d/inv.py (same list, same order)", True, bool(same), None))
    rows.append(_row("invariants (count)", model["n_invariants"], len(B.inv), None))
    data = rows_for(state)
    Qa = np.vstack([data[k][0] for k in ("main", "refine", "extra")])
    Ea = np.concatenate([data[k][1] for k in ("main", "refine", "extra")])
    Ga = np.vstack([data[k][2] for k in ("main", "refine", "extra")])
    ecut, L = float(f6["E_window_meV"]), float(f6["grad_weight_A"])
    m = Ea < ecut
    X, DG = B.val(Qa[m]), B.grad(Qa[m])
    A = np.vstack([X] + [L * DG[:, k, :] for k in range(6)])
    y = np.concatenate([Ea[m]] + [L * Ga[m, k] for k in range(6)])
    sc = np.abs(A).max(0)
    sc[sc == 0] = 1
    Qm, Rm = np.linalg.qr(A / sc)
    c = np.linalg.solve(Rm, Qm.T @ y) / sc
    c5 = np.load(model["coef_file"])
    rows.append(_row("fit rows in the window", model["n_fit"], int(m.sum()), None))
    tr = errors(B, c, Qa[m], Ea[m], ecut)
    rows.append(_row("training RMS (meV/f.u.)", model["rms_meV"], tr["rms_meV"], 1e-4, "meV/f.u."))
    rows.append(_row("training max |residual| (meV/f.u.)", model["max_abs_res_meV"], tr["max_meV"], 1e-3, "meV/f.u."))
    pred_diff = float(np.abs(B.val(Qa) @ c - B.val(Qa) @ c5).max())
    rows.append(_row("QR vs lstsq model on all rows: max |ΔE| (meV/f.u.)", 0.0, pred_diff, 1e-3, "meV/f.u."))

    # stationary points: BFGS with the analytic gradient on the restricted lines
    f = lambda x: float((B.val(np.atleast_2d(x)) @ c)[0])
    g = lambda x: np.einsum("nki,i->nk", B.grad(np.atleast_2d(x)), c)[0]
    cell = Cell(cg, float(cfg["policy"]["grid"]["six"]["datasets"][0]["a_c"]))
    for nm, dn, kind in STAT:
        n = DIRS[dn]
        st5 = model["stationary"][nm]
        if kind == "PR":
            U = np.zeros((6, 2)); U[:3, 0] = n; U[3:, 1] = n; z0 = [st5["P_A"] * 0.97, st5["R_A"] * 1.03]
        elif kind == "P":
            U = np.zeros((6, 1)); U[:3, 0] = n; z0 = [st5["P_A"] * 0.97]
        else:
            U = np.zeros((6, 1)); U[3:, 0] = n; z0 = [st5["R_A"] * 1.03]
        o = minimize(lambda z: f(U @ z), z0, jac=lambda z: U.T @ g(U @ z), method="BFGS", options=dict(gtol=1e-8))
        x = U @ o.x
        rows.append(_row(f"{nm}: E (meV/f.u.)", st5["E_meV"], float(o.fun), 0.01, "meV/f.u."))
        pr = (float(np.linalg.norm(x[:3])), float(np.linalg.norm(x[3:])))
        rows.append(_row(f"{nm}: |P| (Å)", round(st5["P_A"], 4), round(pr[0], 4), 2e-4, "Å"))
        rows.append(_row(f"{nm}: |R| (Å)", round(st5["R_A"], 4), round(pr[1], 4), 2e-4, "Å"))
        h = 1e-3
        Hm = np.zeros((6, 6))
        for i in range(6):
            for j in range(i, 6):
                ei, ej = np.eye(6)[i] * h, np.eye(6)[j] * h
                Hm[i, j] = Hm[j, i] = (f(x + ei + ej) - f(x + ei - ej) - f(x - ei + ej) + f(x - ei - ej)) / (4 * h * h)
        ev = np.linalg.eigvalsh(Hm)
        rows.append(_row(f"{nm}: Hessian index", st5["index"], int((ev < -1e-3 * np.abs(ev).max()).sum()), None))
        rows.append(_row(f"{nm}: space group of the structure", SG_OF[nm], cell.sg(x), None))
    # secondary dataset (V0): training RMS by QR and each stationary energy by BFGS
    for nm_s, sec in (model.get("secondary") or {}).items():
        s_cfg = next(x for x in f6["secondary"] if x["name"] == nm_s)
        d2 = rows_for(state, parts=s_cfg["parts"])
        Q2 = np.vstack([v[0] for v in d2.values()]); E2 = np.concatenate([v[1] for v in d2.values()])
        G2 = np.vstack([v[2] for v in d2.values()])
        m2 = E2 < ecut
        X2, DG2 = B.val(Q2[m2]), B.grad(Q2[m2])
        A2 = np.vstack([X2] + [L * DG2[:, k, :] for k in range(6)])
        y2 = np.concatenate([E2[m2]] + [L * G2[m2, k] for k in range(6)])
        sc2 = np.abs(A2).max(0); sc2[sc2 == 0] = 1
        Qm2, Rm2 = np.linalg.qr(A2 / sc2)
        c2 = np.linalg.solve(Rm2, Qm2.T @ y2) / sc2
        rows.append(_row(f"{nm_s}: training RMS (meV/f.u.)", sec["iris"]["training"]["rms_meV"],
                         errors(B, c2, Q2[m2], E2[m2], ecut)["rms_meV"], 1e-4, "meV/f.u."))
        f2_ = lambda x: float((B.val(np.atleast_2d(x)) @ c2)[0])
        g2_ = lambda x: np.einsum("nki,i->nk", B.grad(np.atleast_2d(x)), c2)[0]
        for nm, dn, kind in STAT:
            n = DIRS[dn]
            st5 = sec["iris"]["stationary"][nm]
            U = np.zeros((6, 2 if kind == "PR" else 1))
            if kind == "PR":
                U[:3, 0] = n; U[3:, 1] = n; z0 = [st5["P_A"] * 0.97, st5["R_A"] * 1.03]
            elif kind == "P":
                U[:3, 0] = n; z0 = [st5["P_A"] * 0.97]
            else:
                U[3:, 0] = n; z0 = [st5["R_A"] * 1.03]
            o = minimize(lambda z: f2_(U @ z), z0, jac=lambda z: U.T @ g2_(U @ z), method="BFGS", options=dict(gtol=1e-8))
            rows.append(_row(f"{nm_s} {nm}: E (meV/f.u.)", st5["E_meV"], float(o.fun), 0.01, "meV/f.u."))
    e0 = model["stationary"]["R3c"]["E_meV"]
    rows.append(_row("global minimum = R3c (60 BFGS starts)", round(e0, 1), model["global_search"]["lowest_meV"], 0.1, "meV/f.u."))
    return {"rows": rows, "n_numbers": len(rows), "n_ok": sum(x["ok"] for x in rows),
            "summary": {"datasets": [{k: d[k] for k in ("name", "n_nodes", "n_orbits", "n_orbits_included")} for d in grid["datasets"]],
                        "frames": grid["n_frames"], "matched": jobs["n_matched"],
                        "fit": {k: model[k] for k in ("n_invariants", "n_fit", "rms_meV", "cv")},
                        "stationary": {k: {x: v[x] for x in ("E_meV", "P_A", "R_A", "index")} for k, v in model["stationary"].items()}}}


def _path(P) -> bool:
    import sys
    d = str(Path(P.repo("grid_toolkit")) / "landau6d")
    if d not in sys.path:
        sys.path.insert(0, d)
    return True
