"""f4 Reviewer, six-component grid (BiFeO3 stage B3): energies, gradients and QC from the collected CSVs.

Source: paths.collected_dir/runs_<dataset>.csv (bfo6d/collect.py on Perlmutter: OUTCAR energy, gradients
dE/dq = -F.B projected on the six basis vectors, SCF and magnetic QC). OUTCARs are not available locally, so
IRIS re-derives what it can from the rows and checks the rest by symmetry:
  - E_meV_per_fu = 1000 (E0_cell / n_fu - E0_origin / n_fu) against each dataset's own q = 0 run;
  - the CSV labels q and the space group equal the frame IRIS planned;
  - controls: E(image) = E(representative), dE/dq(image) = G dE/dq(rep) with image = G rep (G one of the 96);
  - refine points on a main-grid node: E = E of that node's orbit (main_V1);
  - gradient sign and units: along grid lines of main_V1 (every node via the orbit map),
    E(c) - E(a) = h/3 (g_a + 4 g_b + g_c) + O(h^5) on three consecutive nodes (Simpson; tested: slope = 1);
    the two-node trapezoid (O(h^3)) is reported only: at these steps its h^3 bias is ~3 %;
  - magnetism: G-AFM kept (m_Fe1 = -m_Fe2, total moment ~ 0).
SCF-limited runs (policy.qc.scf_limited: keep_energy_drop_gradients) keep the energy and lose the gradients;
they are flagged and accepted. Frames without a converged energy are flagged, never recomputed.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..engines.replay6 import GRAD_KEYS, Q_KEYS, fnum, read_collected, run_name, truthy
from ..paths import from_config


def _canon(idx, mats):
    return max(tuple(int(x) for x in G @ np.asarray(idx)) for G in mats)


def canon_many(X: np.ndarray, mats: np.ndarray):
    """Canonical image (lexicographic max of the 96 images) of every row and the op H with canon = H x."""
    imgs = np.einsum("gij,nj->gni", mats, X)                       # (96, n, 6)
    key = np.zeros(imgs.shape[:2], np.int64)
    for j in range(6):
        key = key * 101 + (imgs[:, :, j] + 50)
    g = key.argmax(axis=0)
    return imgs[g, np.arange(len(X))], g


def _sg_numbers() -> dict:
    import spglib
    out = {}
    for h in range(1, 531):
        t = spglib.get_spacegroup_type(h)
        out.setdefault(t.international_short, t.number)
        out.setdefault(t.international, t.number)
    return out


def f4_grid6(state: dict) -> dict:
    cfg, grid, jobs = state["config"], state["grid"], state["jobs"]
    P = from_config(cfg)
    qc = cfg["policy"].get("qc") or {}
    n_fu = int(cfg["policy"]["fit"]["per_fu"])
    cdir = P.repo("collected_dir")
    mats = np.array(state["decomposition"]["components"]["grid"]["mats"], int)
    sg_of = {}
    rows = {}
    for ds in sorted({f["dataset"] for f in grid["frames"]}):
        rows[ds] = read_collected(Path(cdir) / f"runs_{ds}.csv")
    E, G, flagged, recs = {}, {}, [], {}
    accept_failed = bool(state.get("overrides", {}).get("f4", {}).get("flag_unconverged"))
    label_dev, sg_bad, missing_rows = 0.0, [], []
    for i, fr in enumerate(grid["frames"]):
        m = jobs["matched"].get(str(i))
        st = (m or {}).get("status", "")
        if st.startswith("failed:"):
            # a failed job: G4 fails with its code unless the frames are accepted as flagged (recovery option
            # flag_and_continue, as in f4_reviewer / f4_path)
            flagged.append({"id": fr["id"], "code": st.split(":", 1)[1], "part": m.get("part"),
                            "reason": f"job part {m.get('part')} {st}", "accepted": accept_failed})
            continue
        if not m or st != "finished":
            flagged.append({"id": fr["id"], "reason": "unmatched or not finished"})
            continue
        r = rows[fr["dataset"]].get(run_name(fr)[1])
        if r is None:
            missing_rows.append(fr["id"])
            flagged.append({"id": fr["id"], "reason": "no row in the collected CSV"})
            continue
        q = np.array([float(r[k]) for k in Q_KEYS])
        label_dev = max(label_dev, float(np.abs(q - np.array(fr["q_A"])).max()))
        sg_of[fr["id"]] = r["spacegroup"]
        e0 = fnum(r["E0_cell_eV"])
        if not truthy(r["done"]) or e0 is None:
            flagged.append({"id": fr["id"], "reason": "no energy"})
            continue
        scf_lim = truthy(r["scf_limited"])
        if not truthy(r["converged"]) and not scf_lim:
            flagged.append({"id": fr["id"], "reason": "not converged"})
            continue
        E[str(i)] = e0
        g = [fnum(r[k]) for k in GRAD_KEYS]
        if scf_lim:
            ok = qc.get("scf_limited") == "keep_energy_drop_gradients"
            flagged.append({"id": fr["id"], "code": "SCF_LIMITED", "accepted": ok, "energy_kept": ok,
                            "reason": f"SCF-limited ({r['nscf']} steps): energy kept, gradients dropped"})
            if not ok:
                E.pop(str(i))
                continue
        elif None not in g:
            G[str(i)] = g
        recs[str(i)] = {"E_csv_meV": fnum(r["E_meV_per_fu"]), "M_tot": fnum(r["M_tot"]),
                        "m_Fe": (fnum(r["m_Fe1"]), fnum(r["m_Fe2"])), "nscf": int(float(r["nscf"])),
                        "F_out_max": fnum(r["F_out_max"])}

    # energies per dataset relative to its own origin (q = 0) run
    origin, E_meV, e_dev = {}, {}, 0.0
    for i, fr in enumerate(grid["frames"]):
        if str(i) in E and np.allclose(fr["q_A"], 0) and fr["dataset"] not in origin:
            origin[fr["dataset"]] = str(i)
    for i, fr in enumerate(grid["frames"]):
        k = str(i)
        if k in E and fr["dataset"] in origin:
            E_meV[k] = 1000 * (E[k] - E[origin[fr["dataset"]]]) / n_fu
            if recs.get(k, {}).get("E_csv_meV") is not None:
                e_dev = max(e_dev, abs(E_meV[k] - recs[k]["E_csv_meV"]))
    origin_copies = {}
    for i, fr in enumerate(grid["frames"]):
        if str(i) in E and np.allclose(fr["q_A"], 0):
            o = origin.get(fr["dataset"])
            origin_copies.setdefault(fr["dataset"], []).append(1000 * abs(E[str(i)] - E[o]) / n_fu)

    # controls and refine-on-node checks (symmetry)
    pos = {fr["id"]: str(i) for i, fr in enumerate(grid["frames"])}
    rep_frame = {(fr["dataset"], tuple(fr["index"])): str(i) for i, fr in enumerate(grid["frames"])
                 if fr["role"] == "production"}
    ctl = {"n": 0, "n_compared_grad": 0, "max_dE_meV": 0.0, "max_dgrad": 0.0, "worst": None, "scf_limited": {}}
    scf_ids = {f["id"] for f in flagged if f.get("code") == "SCF_LIMITED"}
    for i, fr in enumerate(grid["frames"]):
        if fr["role"] != "control_img" or str(i) not in E_meV:
            continue
        idx = np.array(fr["index"])
        rep = _canon(idx, mats)
        j = rep_frame.get((fr["dataset"], rep))
        if j is None or j not in E_meV:
            continue
        ops = [G for G in mats if tuple(G @ np.array(rep)) == tuple(idx)]
        dE = abs(E_meV[str(i)] - E_meV[j])
        if fr["id"] in scf_ids or grid["frames"][int(j)]["id"] in scf_ids:      # energy uncertain (+- 15 meV/f.u.)
            ctl["scf_limited"][fr["id"]] = dE
            continue
        ctl["n"] += 1
        if dE > ctl["max_dE_meV"]:
            ctl["max_dE_meV"], ctl["worst"] = dE, fr["id"]
        if str(i) in G and j in G:
            ctl["n_compared_grad"] += 1
            gi, gr = np.array(G[str(i)]), np.array(G[j])
            ctl["max_dgrad"] = max(ctl["max_dgrad"], min(float(np.abs(gi - Gm @ gr).max()) for Gm in ops))
    ref = {"n": 0, "max_dE_meV": 0.0}
    six = cfg["policy"]["grid"]["six"]
    sc = np.r_[[six["steps_A"][0]] * 3, [six["steps_A"][1]] * 3]
    main_ds = six["datasets"][0]["name"]
    for i, fr in enumerate(grid["frames"]):
        if fr["role"] != "refine" or str(i) not in E_meV:
            continue
        idx = np.array(fr["q_A"]) / sc
        if not np.allclose(idx, np.round(idx), atol=1e-9):
            continue
        j = rep_frame.get((main_ds, _canon(np.round(idx).astype(int), mats)))
        if j is not None and j in E_meV:
            ref["n"] += 1
            ref["max_dE_meV"] = max(ref["max_dE_meV"], abs(E_meV[str(i)] - E_meV[j]))

    # gradient sign / units along grid lines of main_V1 (all nodes via the orbit map): trapezoid (reported) and Simpson (tested)
    node_E, node_g = {}, {}
    for (ds, rep), j in rep_frame.items():
        if ds == main_ds and j in E_meV:
            node_E[rep] = E_meV[j]
            if j in G:
                node_g[rep] = np.array(G[j])
    reps = np.array(list(node_g), int)
    lhs, rhs, emax = [], [], []
    for k in range(6):
        B = reps.copy()
        B[:, k] += 1
        cb, h = canon_many(B, mats)
        for a, b, c, H in zip(reps, B, cb, h):
            c = tuple(int(x) for x in c)
            if c not in node_g:
                continue
            gb = mats[H].T @ node_g[c]                        # b = H^T c, so g(b) = H^T g(c)
            ga = node_g[tuple(int(x) for x in a)]
            lhs.append(node_E[c] - node_E[tuple(int(x) for x in a)])
            rhs.append(0.5 * (ga[k] + gb[k]) * sc[k])
            emax.append(max(node_E[c], node_E[tuple(int(x) for x in a)]))
    lhs, rhs, emax = np.array(lhs), np.array(rhs), np.array(emax)

    def _stats(m):
        if not m.any():
            return {"n_pairs": 0, "slope": None}
        a_, b_ = lhs[m], rhs[m]
        return {"n_pairs": int(m.sum()), "slope": float(a_ @ b_ / (b_ @ b_)),
                "rms_meV": float(np.sqrt(np.mean((a_ - b_) ** 2))), "median_abs_meV": float(np.median(np.abs(a_ - b_)))}
    # Simpson on three consecutive nodes a, b, c: E(c) - E(a) = h/3 (g_a + 4 g_b + g_c) + O(h^5)
    sl, sr, se = [], [], []
    for k in range(6):
        Bm, Bp = reps.copy(), reps.copy()
        Bm[:, k] -= 1
        Bp[:, k] += 1
        cm, hm = canon_many(Bm, mats)
        cp, hp = canon_many(Bp, mats)
        for a, m_, p_, Hm, Hp in zip(reps, cm, cp, hm, hp):
            m_, p_ = tuple(int(x) for x in m_), tuple(int(x) for x in p_)
            if m_ not in node_g or p_ not in node_g:
                continue
            ta = tuple(int(x) for x in a)
            gm, gp = mats[Hm].T @ node_g[m_], mats[Hp].T @ node_g[p_]
            sl.append(node_E[p_] - node_E[m_])
            sr.append(sc[k] / 3 * (gm[k] + 4 * node_g[ta][k] + gp[k]))
            se.append(max(node_E[p_], node_E[m_], node_E[ta]))
    sl, sr, se = np.array(sl), np.array(sr), np.array(se)
    ew = float(qc.get("line_E_max_meV", 1000.0))
    trap = {"trapezoid": _stats(emax <= ew), "E_max_meV": ew, "trapezoid_all": _stats(np.ones(len(lhs), bool)),
            "step_A": [float(sc[0]), float(sc[3])]}
    lhs, rhs = sl, sr
    trap["simpson"] = _stats(se <= ew)
    trap["simpson_all"] = _stats(np.ones(len(sl), bool))
    trap.update({k: trap["simpson"][k] for k in ("n_pairs", "slope", "rms_meV", "median_abs_meV") if k in trap["simpson"]})

    # magnetism, SCF
    mags = [v["m_Fe"] for v in recs.values() if None not in v["m_Fe"]]
    mag = {"min_abs_mFe": float(min(min(abs(a), abs(b)) for a, b in mags)) if mags else None,
           "max_abs_mFe": float(max(max(abs(a), abs(b)) for a, b in mags)) if mags else None,
           "max_afm_imbalance": float(max(abs(a + b) for a, b in mags)) if mags else None,
           "n_same_sign": int(sum(1 for a, b in mags if a * b >= 0)),
           "max_abs_Mtot": float(max(abs(v["M_tot"]) for v in recs.values() if v["M_tot"] is not None))}
    vals = list(E_meV.values())
    energies = {"eV_per_cell": E, "meV_per_fu": E_meV, "gradients_meV_per_A_fu": G, "flagged": flagged,
                "n": len(E), "n_gradients": len(G), "origin_id": origin.get(main_ds), "origins": origin,
                "origin_copies_spread_meV": {k: max(v) for k, v in origin_copies.items()},
                "E0_eV": E.get(origin.get(main_ds)), "range_meV_per_fu": (max(vals) - min(vals)) if vals else None,
                "per_fu": n_fu, "sanity": {"min_range_meV": 1.0, "max_range_meV": 10000.0},
                "E_csv_max_dev_meV": e_dev, "label_max_dev_A": label_dev, "missing_rows": missing_rows[:10],
                "n_missing_rows": len(missing_rows), "controls": ctl, "refine_on_main": ref, "line_integral": trap,
                "magnetism": mag, "n_scf_limited": sum(1 for f in flagged if f.get("code") == "SCF_LIMITED"),
                "stored_input_sets": jobs.get("stored_input_sets", {}),
                "convergence_source": "collected CSVs (bfo6d/collect.py on Perlmutter); OUTCAR/OSZICAR not available locally",
                "sg_csv": None}
    # space-group symbols in the CSV vs IRIS's numbers (f2)
    sym = _sg_numbers()
    for fr in grid["frames"]:
        s = sg_of.get(fr["id"])
        if s is None:
            continue
        if sym.get(s) != fr.get("sg"):
            sg_bad.append((fr["id"], s, fr.get("sg")))
    energies["n_sg_mismatch"] = len(sg_bad)
    energies["sg_mismatch"] = sg_bad[:10]
    return {"energies": energies, "last_node": "f4"}
