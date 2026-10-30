"""f5 Analyst, analysis kind "landau6d" (BiFeO3 stage B4): invariant polynomial in the six components fitted to
energies and gradients, the procedure of demo/bifeo3/grid6d/work/refit.py (final refit, 16 Oct 2026):

  E(q) = sum_a c_a I_a(q),   I_a = orbit sums of monomials under the 96 operations, even degrees 2..12
  least squares on [E; L dE/dq_k] for rows with E < E_window (meV/f.u.), unit weights, columns scaled by
  their largest |entry|; L = grad_weight (0.1 A).

The invariants are built here from IRIS's own 96 matrices (f1) with the same orbit-sum rule and ordering as
bfo6d/landau6d/inv.py, so the coefficient vector can be compared entry by entry with the stored one; their
number is checked against Molien's formula. Data: IRIS's own energies and gradients (f4, B3) for
main_V1 production frames with a converged energy (SCF-limited runs out, as load() in fit6d.py), refine_V1
and extra_V1; rows in collected-CSV order, so the published 20 % hold-out (seed 0) is the same split.
Also fitted as in refit.py: main + refine (blind on extra) and main + extra (blind on refine).
Derived: the nine stationary points on the symmetric lines (as work/analyze.py: Nelder-Mead along P, R or
P and R parallel to [111], [110], [001]) with their Hessian index, and 60 random BFGS starts (global minimum).
Added here (not in the script): 10-fold CV of the final scheme.
"""
from __future__ import annotations

from ._layout import dropped_frames

import itertools

import numpy as np

DIRS = {"[111]": np.ones(3) / np.sqrt(3), "[110]": np.array([1, 1, 0]) / np.sqrt(2), "[001]": np.array([0, 0, 1.0])}
STAT = [("R3c", "[111]", "PR"), ("Ima2", "[110]", "PR"), ("I4cm", "[001]", "PR"), ("R3m", "[111]", "P"),
        ("Amm2", "[110]", "P"), ("P4mm", "[001]", "P"), ("R-3c", "[111]", "R"), ("Imma", "[110]", "R"),
        ("I4/mcm", "[001]", "R")]


def invariants(mats: np.ndarray, maxdeg: int):
    perm = np.argmax(np.abs(mats), axis=2)
    sign = np.take_along_axis(mats, perm[:, :, None], axis=2)[:, :, 0].astype(int)
    out = []
    for deg in range(2, maxdeg + 1, 2):
        seen = set()
        for e in itertools.product(range(deg + 1), repeat=6):
            if sum(e) != deg or e in seen:
                continue
            poly = {}
            for g in range(len(mats)):
                new, s = [0] * 6, 1
                for i in range(6):
                    new[perm[g, i]] += e[i]
                    s *= int(sign[g, i]) ** e[i]
                poly[tuple(new)] = poly.get(tuple(new), 0) + s
            seen.update(poly)
            poly = {m: (1 if c > 0 else -1) for m, c in poly.items() if c != 0}
            if poly:
                out.append((deg, poly))
    return out


def molien(mats: np.ndarray, maxdeg: int) -> list[float]:
    """Number of independent invariants of each degree 0..maxdeg: (1/|G|) sum_g [t^d] 1/det(1 - t g)."""
    tot = np.zeros(maxdeg + 1)
    for G in mats:
        c = np.poly(G)                              # det(x - G) = sum_k c_k x^(6-k), so det(1 - t G) = sum_k c_k t^k
        inv = np.zeros(maxdeg + 1)
        inv[0] = 1.0 / c[0]
        for d in range(1, maxdeg + 1):
            inv[d] = -sum(c[k] * inv[d - k] for k in range(1, min(d, len(c) - 1) + 1)) / c[0]
        tot += inv
    return (tot / len(mats)).tolist()


class Basis:
    def __init__(self, mats, maxdeg):
        self.inv = invariants(mats, maxdeg)
        mons = sorted({m for _, p in self.inv for m in p})
        self.idx = {m: i for i, m in enumerate(mons)}
        self.E = np.array(mons)
        self.C = np.zeros((len(self.inv), len(mons)))
        for a, (_, p) in enumerate(self.inv):
            for m, c in p.items():
                self.C[a, self.idx[m]] = c

    def val(self, q):
        return np.prod(np.asarray(q)[:, None, :] ** self.E[None], axis=2) @ self.C.T

    def grad(self, q):
        q = np.asarray(q)
        out = np.zeros((len(q), 6, len(self.inv)))
        for k in range(6):
            Ek = self.E.copy()
            f = Ek[:, k].astype(float)
            Ek[:, k] = np.maximum(Ek[:, k] - 1, 0)
            out[:, k, :] = (np.prod(q[:, None, :] ** Ek[None], axis=2) * f[None]) @ self.C.T
        return out


def solve(B, q, E, G, ecut, L):
    m = E < ecut
    X, DG = B.val(q[m]), B.grad(q[m])
    A = np.vstack([X] + [L * DG[:, k, :] for k in range(6)])
    y = np.concatenate([E[m]] + [L * G[m, k] for k in range(6)])
    sc = np.abs(A).max(0)
    sc[sc == 0] = 1
    return np.linalg.lstsq(A / sc, y, rcond=None)[0] / sc, m


def errors(B, c, q, E, ecut):
    k = E < ecut
    d = B.val(q[k]) @ c - E[k]
    return {"n": int(k.sum()), "rms_meV": float(np.sqrt(np.mean(d ** 2))) if k.any() else None,
            "max_meV": float(np.abs(d).max()) if k.any() else None}


def stationary(B, c):
    from scipy.optimize import minimize
    f = lambda x: float((B.val(np.atleast_2d(x)) @ c)[0])
    g = lambda x: np.einsum("nki,i->nk", B.grad(np.atleast_2d(x)), c)[0]

    def H(x, h=1e-4):
        Hm = np.zeros((6, 6))
        for i in range(6):
            e = np.zeros(6)
            e[i] = h
            Hm[:, i] = (g(x + e) - g(x - e)) / (2 * h)
        return (Hm + Hm.T) / 2 / 1000
    out = {}
    for nm, dn, kind in STAT:
        n = DIRS[dn]
        if kind == "PR":
            o = minimize(lambda z: f(np.r_[z[0] * n, z[1] * n]), [0.5, 0.65], method="Nelder-Mead",
                         options=dict(xatol=1e-9, fatol=1e-10, maxiter=20000))
            p, r = o.x
        elif kind == "P":
            o = minimize(lambda z: f(np.r_[z[0] * n, 0 * n]), [0.6], method="Nelder-Mead",
                         options=dict(xatol=1e-9, fatol=1e-10, maxiter=20000))
            p, r = o.x[0], 0.0
        else:
            o = minimize(lambda z: f(np.r_[0 * n, z[0] * n]), [0.7], method="Nelder-Mead",
                         options=dict(xatol=1e-9, fatol=1e-10, maxiter=20000))
            p, r = 0.0, o.x[0]
        x = np.r_[p * n, r * n]
        ev = np.linalg.eigvalsh(H(x))
        out[nm] = {"E_meV": float(o.fun), "P_A": float(abs(p)), "R_A": float(abs(r)), "q": x.tolist(),
                   "index": int((ev < -1e-3 * np.abs(ev).max()).sum()), "hessian_eV_per_A2": ev.tolist(),
                   "grad_norm": float(np.linalg.norm(g(x)))}
    rng = np.random.default_rng(1)
    sols = []
    for _ in range(60):
        o = minimize(f, rng.normal(size=6) * np.r_[[0.35] * 3, [0.45] * 3], jac=g, method="BFGS", options=dict(gtol=1e-6))
        sols.append(round(float(o.fun), 1))
    vals, counts = np.unique(sols, return_counts=True)
    return out, {"n_starts": 60, "minima": {str(v): int(k) for v, k in zip(vals, counts)}, "lowest_meV": float(min(sols))}


def rows_for(state, use_stored_labels=False, parts=None):
    """Fit rows from f4 (IRIS labels and energies), in collected-CSV order per dataset. With
    use_stored_labels the CSV's own q / E columns are used instead (the published inputs)."""
    from pathlib import Path

    from ..engines.replay6 import GRAD_KEYS, Q_KEYS, read_collected, run_name
    from ..paths import from_config
    grid, en, cfg = state["grid"], state["energies"], state["config"]
    fit6 = cfg["policy"]["fit"]["six"]
    out = {}
    rows_csv = {}
    for part in (parts or fit6["parts"]):
        ds, roles = part["dataset"], set(part["roles"])
        rows_csv[ds] = read_collected(Path(from_config(cfg).repo("collected_dir")) / f"runs_{ds}.csv")
        order = {k: i for i, k in enumerate(rows_csv[ds])}
        sel = []
        for i, fr in enumerate(grid["frames"]):
            k = str(i)
            if fr["dataset"] != ds or fr["role"] not in roles or k not in en["meV_per_fu"] or k not in en["gradients_meV_per_A_fu"]:
                continue
            sel.append((order[run_name(fr)[1]], i))
        sel.sort()
        q, E, G, role = [], [], [], []
        for _, i in sel:
            fr = grid["frames"][i]
            if use_stored_labels:
                r = rows_csv[ds][run_name(fr)[1]]
                q.append([float(r[x]) for x in Q_KEYS]); E.append(float(r["E_meV_per_fu"]))
                G.append([float(r[x]) for x in GRAD_KEYS])
            else:
                q.append(fr["q_A"]); E.append(en["meV_per_fu"][str(i)]); G.append(en["gradients_meV_per_A_fu"][str(i)])
            role.append(fr["role"])
        out[part["name"]] = (np.array(q), np.array(E), np.array(G), np.array(role))
    return out


def fit_all(state, B, data):
    f6 = state["config"]["policy"]["fit"]["six"]
    ecut, L = float(f6["E_window_meV"]), float(f6["grad_weight_A"])
    M, R, X = data["main"], data["refine"], data["extra"]

    def cat(parts):
        return (np.vstack([p[0] for p in parts]), np.concatenate([p[1] for p in parts]), np.vstack([p[2] for p in parts]))
    res = {}
    cA, _ = solve(B, *cat([M, R]), ecut, L)
    res["main+refine: blind extra"] = errors(B, cA, X[0], X[1], ecut)
    for r in ("plane_check", "mep", "fill"):
        k = X[3] == r
        res[f"main+refine: blind extra {r}"] = errors(B, cA, X[0][k], X[1][k], ecut)
    cB, _ = solve(B, *cat([M, X]), ecut, L)
    res["main+extra: blind refine"] = errors(B, cB, R[0], R[1], ecut)
    Qa, Ea, Ga = cat([M, R, X])
    c1, m1 = solve(B, Qa, Ea, Ga, ecut, L)
    res["final: training"] = errors(B, c1, Qa[m1], Ea[m1], ecut)
    res["final: refine (train)"] = errors(B, c1, R[0], R[1], ecut)
    res["final: extra (train)"] = errors(B, c1, X[0], X[1], ecut)
    ho = f6.get("holdout") or {"fraction": 0.2, "seed": 0}
    te = np.random.default_rng(int(ho["seed"])).random(len(Qa)) < float(ho["fraction"])
    c2, _ = solve(B, Qa[~te], Ea[~te], Ga[~te], ecut, L)
    res["final scheme: hold-out"] = errors(B, c2, Qa[te], Ea[te], ecut)
    return c1, m1, (Qa, Ea, Ga), res


def f5_landau6d(state: dict) -> dict:
    cfg = state["config"]
    fit = cfg["policy"]["fit"]
    f6 = fit["six"]
    mats = np.array(state["decomposition"]["components"]["grid"]["mats"], int)
    deg = int(f6["degree"])
    B = Basis(mats, deg)
    mol = molien(mats, deg)
    data = rows_for(state)
    c1, m1, (Qa, Ea, Ga), res = fit_all(state, B, data)
    ecut, L = float(f6["E_window_meV"]), float(f6["grad_weight_A"])
    # 10-fold CV of the final scheme (rows in order, fold = row index mod k)
    k = int(fit["cv_folds"])
    idx = np.arange(len(Qa)) % k
    cres = []
    for f in range(k):
        cc, _ = solve(B, Qa[idx != f], Ea[idx != f], Ga[idx != f], ecut, L)
        t = (idx == f) & (Ea < ecut)
        cres.append(B.val(Qa[t]) @ cc - Ea[t])
    cres = np.concatenate(cres)
    r1 = B.val(Qa[m1]) @ c1 - Ea[m1]
    gres = np.einsum("nki,i->nk", B.grad(Qa[m1]), c1) - Ga[m1]
    st, glob = stationary(B, c1)
    e0 = st["R3c"]["E_meV"]
    # the published inputs: the same procedure on the CSV's own labels and energies
    c_st, _, _, res_st = fit_all(state, B, rows_for(state, use_stored_labels=True))
    st_st, _ = stationary(B, c_st)
    from ..paths import from_config
    out_dir = from_config(cfg).out(from_config(cfg).run_dir(state["thread_id"]), "f5_landau6d")
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "coef_iris.npy", c1)
    np.save(out_dir / "coef_iris_stored_labels.npy", c_st)
    model = {"fitted": True, "dropped_frames": dropped_frames(state), "kind": "landau6d", "script": "in-node (procedure of demo/bifeo3/grid6d/work/refit.py)",
             "degree": deg, "n_invariants": len(B.inv), "n_monomials": int(len(B.E)),
             "molien_per_degree": mol, "molien_total_2_to_deg": float(sum(mol[1:])),
             "per_fu": fit["per_fu"], "energy_unit": "meV per f.u.", "E_window_meV": ecut, "grad_weight_A": L,
             "n_rows": {nm: int(len(v[1])) for nm, v in data.items()}, "n_fit": int(m1.sum()),
             "points_per_coef": float(m1.sum() / len(B.inv)),
             "rms_meV": float(np.sqrt(np.mean(r1 ** 2))), "max_abs_res_meV": float(np.abs(r1).max()),
             "grad_rms_meV_per_A": float(np.sqrt(np.mean(gres ** 2))),
             "cv": {"folds": k, "rms_meV": float(np.sqrt(np.mean(cres ** 2))), "max_abs_meV": float(np.abs(cres).max())},
             "tests": res, "tests_stored_labels": res_st,
             "stationary": st, "stationary_stored_labels": {k_: {x: v[x] for x in ("E_meV", "P_A", "R_A", "index")}
                                                            for k_, v in st_st.items()},
             "relative_meV": {k_: v["E_meV"] - e0 for k_, v in st.items()}, "global_search": glob,
             "coef_file": str(out_dir / "coef_iris.npy"), "coef_file_stored_labels": str(out_dir / "coef_iris_stored_labels.npy")}
    ref = cfg["paths"].get("reference_fit")
    if ref:
        cref = np.load(from_config(cfg).repo("reference_fit"))
        model["vs_stored_coef"] = {"max_abs_diff": float(np.abs(c1 - cref).max()),
                                   "max_rel_diff": float(np.abs(c1 - cref).max() / np.abs(cref).max()),
                                   "stored_labels_max_rel_diff": float(np.abs(c_st - cref).max() / np.abs(cref).max())}
    sec = {}
    for s in f6.get("secondary") or []:
        sec[s["name"]] = secondary_fit(state, B, s)
    if sec:
        model["secondary"] = sec
    rbf = f6.get("rbf")
    if rbf:
        model["rbf"] = rbf_check(state, rbf, data, st)
    return {"model": model, "last_node": "f5"}


def secondary_fit(state, B, s: dict) -> dict:
    """A second dataset fitted on its own with the same model (BiFeO3 V0 at the cubic-anchor volume, the procedure
    of landau6d/v0.py): the final scheme on all its rows, a 20 % hold-out (seed 0) on its rows, the nine stationary
    points; and the same fit on the CSV's own labels, compared with the stored coefficient file."""
    from ..paths import from_config
    f6 = state["config"]["policy"]["fit"]["six"]
    ecut, L = float(f6["E_window_meV"]), float(f6["grad_weight_A"])
    out = {"parts": s["parts"]}
    for lab, stored in (("iris", False), ("stored_labels", True)):
        d = rows_for(state, use_stored_labels=stored, parts=s["parts"])
        Q = np.vstack([v[0] for v in d.values()]); E = np.concatenate([v[1] for v in d.values()])
        G = np.vstack([v[2] for v in d.values()])
        c, m = solve(B, Q, E, G, ecut, L)
        ho = s.get("holdout") or {"fraction": 0.2, "seed": 0}
        te = np.random.default_rng(int(ho["seed"])).random(len(Q)) < float(ho["fraction"])
        c2, _ = solve(B, Q[~te], E[~te], G[~te], ecut, L)
        st, glob = stationary(B, c)
        out[lab] = {"n_rows": int(len(Q)), "training": errors(B, c, Q[m], E[m], ecut),
                    "hold-out": errors(B, c2, Q[te], E[te], ecut), "stationary": st, "global_search": glob, "coef": c}
    P = from_config(state["config"])
    if s.get("reference_fit"):
        cref = np.load(P.repo_root / s["reference_fit"])
        out["vs_stored_coef"] = {"max_rel_diff": float(np.abs(out["iris"]["coef"] - cref).max() / np.abs(cref).max()),
                                 "stored_labels_max_rel_diff": float(np.abs(out["stored_labels"]["coef"] - cref).max() / np.abs(cref).max())}
    d_ = P.out(P.run_dir(state["thread_id"]), "f5_landau6d")
    d_.mkdir(parents=True, exist_ok=True)
    np.save(d_ / f"coef_iris_{s['name']}.npy", out["iris"]["coef"])
    out["coef_file"] = str(d_ / f"coef_iris_{s['name']}.npy")
    for lab in ("iris", "stored_labels"):
        out[lab].pop("coef")
    return out


def rbf_check(state, rbf: dict, data: dict, st: dict) -> dict:
    """Cross-check (reported only): the stored RBF model (work/fit_rbf6d.py: invariant trend + RBF of the residual
    on the 96-fold unfolded data, all main + refine + extra points) at the stationary points of the polynomial."""
    from ..engines import legacy
    from ..paths import from_config
    P = from_config(state["config"])
    mod = legacy.toolkit(P, "rbf_toolkit", "fit_rbf6d")
    Q = np.vstack([data[k][0] for k in ("main", "refine", "extra")])
    E = np.concatenate([data[k][1] for k in ("main", "refine", "extra")])
    m = mod.RBF6D(Q, E, trend=int(rbf.get("trend", 8)), kernel=rbf.get("kernel", "thin_plate_spline"),
                  neighbors=int(rbf.get("neighbors", 100)))
    out = {"settings": m.info, "n_unfolded": int(m.n_unfolded), "max_err_at_data_meV": float(np.abs(m(Q) - E).max()),
           "at_stationary": {}}
    for nm, v in st.items():
        e = float(m(np.array(v["q"]))[0])
        out["at_stationary"][nm] = {"rbf_meV": e, "poly_meV": v["E_meV"], "diff_meV": e - v["E_meV"]}
    return out
