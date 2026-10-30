"""f2 Path planner, six-component grid (policy.components; BiFeO3 stage B2).

Plans the 6D campaign from IRIS's own vectors (f1: the GM4- / R5- single components folded onto the 10-atom
fcc(2a_c) cell, signs by the stated convention) and its own 96 operation matrices:

  main datasets (policy.grid.six.datasets): every node idx in Z^6 with |idx_P| <= r and |idx_R| <= r (two
  balls), q = idx * (dP, dP, dP, dR, dR, dR); orbits under the 96 operations (D5: canonical image = the
  lexicographically largest of the 96 images, orbit ids in ascending canonical order); the number of orbits is
  checked against Burnside's count; an orbit is kept when its shortest interatomic contact (periodic, on that
  dataset's cubic parameter) is >= the contact cut (contact distances are orbit invariants).
  refine planes (policy.grid.six.planes): P = i sP n, R = j sR n along a fixed direction n, same contact cut.
  controls: symmetry images of included orbits (policy.grid.six.controls: stored -> the stored set is read and
  verified; IRIS does not re-draw the random choice).
  extra points: adaptive (chosen from an RBF fit of earlier data), declared as stored frames and only checked
  (contact cut on IRIS's vectors).

Nothing is computed by DFT. The plan is compared with the stored campaign (manifests, orbits.npz and every
point_info.json, read from the packages in paths.grid_packages); G2 (G2_grid6 tests) decides.
Large arrays (855,625 nodes) go to test_runs/<thread>/f2_grid6/*.npz; the state keeps the frames and a summary.
"""
from __future__ import annotations

import hashlib
import itertools

import numpy as np

from ..engines.tarstore import open_store
from ..paths import from_config

NUM = {"Bi": 83, "Fe": 26, "O": 8}


def ball(r: int) -> np.ndarray:
    return np.array([v for v in itertools.product(range(-r, r + 1), repeat=3) if sum(x * x for x in v) <= r * r], int)


def nodes6(r: int) -> np.ndarray:
    P = ball(r)
    return np.concatenate([np.repeat(P, len(P), axis=0), np.tile(P, (len(P), 1))], axis=1)


def canonical(nodes: np.ndarray, mats: np.ndarray):
    """Lexicographically largest image of every node under the 96 matrices; (canon, orbit id, op index with
    node = mats[op] @ rep)."""
    r = int(np.abs(nodes).max())
    base = 2 * r + 1

    def key(X):
        k = np.zeros(len(X), np.int64)
        for j in range(6):
            k = k * base + (X[:, j] + r)
        return k
    best = np.full(len(nodes), -1, np.int64)
    for G in mats:
        best = np.maximum(best, key(nodes @ G.T))
    uniq, orbit = np.unique(best, return_inverse=True)
    own = key(nodes)
    rep_idx = np.full(len(uniq), -1)
    is_rep = own == best
    rep_idx[orbit[is_rep]] = np.where(is_rep)[0]
    reps = nodes[rep_idx]
    rep_of = reps[orbit]
    op = np.full(len(nodes), -1)
    for gi, G in enumerate(mats):
        m = np.where(op < 0)[0]
        if not len(m):
            break
        hit = np.all(rep_of[m] @ G.T == nodes[m], axis=1)
        op[m[hit]] = gi
    return reps, orbit, op


def burnside(nodes: np.ndarray, mats: np.ndarray) -> float:
    """(1/|G|) sum_g |Fix(g)| over the node set (independent orbit count)."""
    return float(sum(int(np.all(nodes @ G.T == nodes, axis=1).sum()) for G in mats) / len(mats))


class Cell:
    def __init__(self, comp_grid: dict, a_c: float):
        c = comp_grid["cell"]
        self.a_c = a_c
        self.lat = np.array(c["lattice_unit"], float) * a_c
        self.cart0 = np.array(c["frac_parent"], float) * a_c
        self.spec = list(c["species"])
        self.V = np.array(comp_grid["vectors_unit"], float)
        sh = np.array(list(itertools.product((-1, 0, 1), repeat=3)), float) @ self.lat
        self.shifts = sh

    def cart(self, q):
        return self.cart0 + np.tensordot(np.asarray(q, float), self.V, axes=1)

    def dmin_many(self, Q: np.ndarray, chunk=500) -> np.ndarray:
        out = np.empty(len(Q))
        n = len(self.spec)
        iu = np.triu_indices(n, 1)
        for s in range(0, len(Q), chunk):
            X = self.cart0[None] + np.einsum("bk,kna->bna", Q[s:s + chunk], self.V)          # (b, n, 3)
            d = X[:, :, None, None, :] - X[:, None, :, None, :] + self.shifts[None, None, None]   # (b,n,n,27,3)
            L = np.linalg.norm(d, axis=-1)
            same = L[:, np.arange(n), np.arange(n)]                                       # self images
            same[same < 1e-8] = np.inf
            pair = L[:, iu[0], iu[1]].min(axis=(1, 2))
            out[s:s + chunk] = np.minimum(pair, same.min(axis=(1, 2)))
        return out

    def sg(self, q, symprec=1e-3) -> int:
        import spglib
        frac = self.cart(q) @ np.linalg.inv(self.lat)
        return int(spglib.get_symmetry_dataset((self.lat, frac, [NUM[s] for s in self.spec]), symprec=symprec).number)


def _steps(six: dict):
    dP, dR = float(six["steps_A"][0]), float(six["steps_A"][1])
    return np.r_[[dP] * 3, [dR] * 3]


def plan_main(ds: dict, mats: np.ndarray, comp_grid: dict, six: dict, store, out_dir) -> dict:
    sc = _steps(six)
    nodes = nodes6(int(ds["radius"]))
    reps, orbit, op = canonical(nodes, mats)
    mult = np.bincount(orbit, minlength=len(reps))
    cell = Cell(comp_grid, float(ds["a_c"]))
    dmin = cell.dmin_many(reps * sc)
    cut = float(ds["dmin_cut"])
    inc = dmin >= cut
    res = {"name": ds["name"], "radius": int(ds["radius"]), "a_c": float(ds["a_c"]), "dmin_cut": cut,
           "n_nodes": int(len(nodes)), "n_orbits": int(len(reps)), "burnside": burnside(nodes, mats),
           "mult_divides_96": bool(np.all(96 % mult == 0)), "sum_mult": int(mult.sum()),
           "n_orbits_included": int(inc.sum()), "n_nodes_included": int(mult[inc].sum()),
           "closest_to_cut_A": float(np.abs(dmin - cut).min()),
           "unfold_ok": bool(np.all(np.einsum("nij,nj->ni", mats[op], reps[orbit]) == nodes))}
    f = out_dir / f"orbits_{ds['name']}.npz"
    np.savez_compressed(f, nodes=nodes, reps=reps, mult=mult, node_orbit=orbit, node_op=op, orbit_dmin=dmin,
                        orbit_included=inc)
    res["orbits_file"] = str(f)
    res["orbits_sha256"] = hashlib.sha256(f.read_bytes()).hexdigest()
    # comparison with the stored dataset
    pre = ds["stored"]
    st = {}
    if store is not None and f"{pre}/orbits.npz" in store.data:
        z = store.npz(f"{pre}/orbits.npz")
        man = store.json(f"{pre}/manifest.json")
        st = {"manifest": {k: man.get(k) for k in ("n_nodes", "n_orbits", "n_orbits_included", "n_nodes_included",
                                                   "n_controls", "radius", "a_c", "dmin_cut", "dP", "dR")},
              "nodes_equal": bool(z["nodes"].shape == nodes.shape and np.array_equal(np.sort(_keys(z["nodes"])), np.sort(_keys(nodes)))),
              "reps_equal": bool(np.array_equal(z["reps"], reps)),
              "mult_equal": bool(np.array_equal(z["mult"], mult)),
              "included_equal": bool(np.array_equal(z["orbit_included"], inc)),
              "dmin_max_diff_A": float(np.abs(z["orbit_dmin"] - dmin).max()),
              "mats_equal": {np.asarray(G).astype(int).tobytes() for G in z["mats"]} == {G.astype(int).tobytes() for G in mats},
              "steps_equal": bool(abs(float(z["dP"]) - sc[0]) < 1e-12 and abs(float(z["dR"]) - sc[3]) < 1e-12)}
        if st["nodes_equal"] and np.array_equal(z["nodes"], nodes):
            st["node_orbit_equal"] = bool(np.array_equal(z["node_orbit"], orbit))
        else:                                       # same node set in another order: compare the partition
            m = {k: i for i, k in enumerate(_keys(nodes))}
            idx = np.array([m[k] for k in _keys(z["nodes"])])
            st["node_orbit_equal"] = bool(np.array_equal(z["node_orbit"], orbit[idx]))
    res["stored"] = st
    frames = []
    for k in np.where(inc)[0]:
        frames.append({"id": f"{ds['name']}:o{k:05d}", "dataset": ds["name"], "role": "production",
                       "index": reps[k].tolist(), "q_A": (reps[k] * sc).tolist(), "orbit": int(k),
                       "mult": int(mult[k]), "dmin_A": float(dmin[k]), "a_c": float(ds["a_c"])})
    return res, frames, (nodes, orbit, reps, inc, mult)


def _keys(X):
    X = np.asarray(X, np.int64) + 50
    k = np.zeros(len(X), np.int64)
    for j in range(6):
        k = k * 101 + X[:, j]
    return k


def plan_planes(pl: dict, comp_grid: dict, six: dict, a_c: float, cut: float):
    sc = _steps(six)
    cell = Cell(comp_grid, a_c)
    frames, skipped = [], 0
    for name, p in pl.items():
        n = np.asarray(p["direction"], float)
        n = n / np.linalg.norm(n)
        sP, sR = float(p["step_P_A"]), float(p["step_R_A"])
        mP, mR = int(p["reach_steps"] * sc[0] / sP + 1e-9), int(p["reach_steps"] * sc[3] / sR + 1e-9)
        Q = np.array([np.r_[i * sP * n, j * sR * n] for i in range(mP + 1) for j in range(mR + 1)])
        ij = [(i, j) for i in range(mP + 1) for j in range(mR + 1)]
        d = cell.dmin_many(Q)
        for (i, j), q, dd in zip(ij, Q, d):
            if dd < cut:
                skipped += 1
                continue
            frames.append({"id": f"{p['dataset']}:{name}/i{i:02d}_j{j:02d}", "dataset": p["dataset"], "role": "refine",
                           "plane": name, "i": i, "j": j, "q_A": q.tolist(), "dmin_A": float(dd), "a_c": a_c})
    return frames, skipped


def f2_grid6(state: dict) -> dict:
    cfg, dec = state["config"], state["decomposition"]
    P = from_config(cfg)
    six = cfg["policy"]["grid"]["six"]
    cg = dec["components"]["grid"]
    mats = np.array(cg["mats"], int)
    pk = cfg["paths"].get("grid_packages") or []
    store = open_store([str(P.repo_root / p) for p in pk]) if pk else None
    out_dir = P.out(P.run_dir(state["thread_id"]), "f2_grid6")
    out_dir.mkdir(parents=True, exist_ok=True)
    sc = _steps(six)

    datasets, frames, sets = [], [], {}
    for ds in six["datasets"]:
        res, fr, arrs = plan_main(ds, mats, cg, six, store, out_dir)
        datasets.append(res)
        frames += fr
        sets[ds["name"]] = arrs

    # stored point folders vs plan (names, index, orbit, multiplicity, space group)
    audit = {}
    if store is not None:
        for ds, res in zip(six["datasets"], datasets):
            pre = ds["stored"]
            names = {f.rsplit("/", 1)[-1] for f in store.folders(f"{pre}/points")}
            mine = [f for f in frames if f["dataset"] == ds["name"]]
            want = {f["id"].split(":")[1] for f in mine}
            bad = []
            for f in mine:
                key = f"{pre}/points/{f['id'].split(':')[1]}/point_info.json"
                if key not in store.data:
                    continue
                pi = store.json(key)
                if pi["index"] != f["index"] or pi["orbit"] != f["orbit"] or pi["multiplicity"] != f["mult"] \
                        or abs(pi["min_dist"] - f["dmin_A"]) > 1e-3:
                    bad.append(f["id"])
                f["sg_stored"] = int(pi["spacegroup"])
            audit[ds["name"]] = {"stored_folders": len(names), "planned": len(want), "missing_in_store": sorted(want - names)[:10],
                                 "n_missing_in_store": len(want - names), "n_unplanned_in_store": len(names - want),
                                 "unplanned_in_store": sorted(names - want)[:10], "n_field_mismatch": len(bad), "field_mismatch": bad[:10]}

    # controls
    ctl = six.get("controls", {})
    controls = []
    if ctl.get("source") == "stored" and store is not None:
        for ds, res in zip(six["datasets"], datasets):
            nodes, orbit, reps, inc, mult = sets[ds["name"]]
            m = {k: i for i, k in enumerate(_keys(nodes))}
            fs = store.folders(f"{ds['stored']}/controls")
            bad = []
            for f in fs:
                pi = store.json(f + "/point_info.json")
                idx = np.array(pi["index"])
                i = m.get(int(_keys(idx[None])[0]))
                k = None if i is None else int(orbit[i])
                ok = k is not None and k == pi["orbit"] and bool(inc[k]) and not np.array_equal(idx, reps[k])
                if not ok:
                    bad.append(f.rsplit("/", 1)[-1])
                controls.append({"id": f"{ds['name']}:{f.rsplit('/', 1)[-1]}", "dataset": ds["name"], "role": "control_img",
                                 "index": idx.tolist(), "q_A": (idx * sc).tolist(), "orbit": k,
                                 "mult": int(mult[k]) if k is not None else None, "a_c": float(ds["a_c"]),
                                 "sg_stored": int(pi["spacegroup"])})
            want = int(round(float(ctl.get("fraction", 0.01)) * res["n_orbits_included"]))
            audit[ds["name"]]["controls"] = {"n": len(fs), "expected": want, "n_invalid": len(bad), "invalid": bad[:10]}

    # refine planes
    planes, pl_audit = [], {}
    if six.get("planes"):
        pdef = six["planes"]
        a_c, cut = float(pdef["a_c"]), float(pdef["dmin_cut"])
        planes, skipped = plan_planes(pdef["sets"], cg, six, a_c, cut)
        pl_audit = {"n": len(planes), "skipped": skipped}
        if store is not None and pdef.get("stored"):
            man = store.json(f"{pdef['stored']}/manifest.json")
            stored = {f[len(pdef["stored"]) + 1:] for f in store.folders(pdef["stored"])}
            mine = {f["id"].split(":", 1)[1] for f in planes}
            mism = 0
            for f in planes:
                key = f"{pdef['stored']}/{f['id'].split(':', 1)[1]}/point_info.json"
                if key in store.data:
                    pi = store.json(key)
                    if np.abs(np.array(pi["q_A"]) - np.array(f["q_A"])).max() > 1e-6:
                        mism += 1
                    f["sg_stored"] = int(pi["spacegroup"])
            pl_audit.update({"stored_n_points": man.get("n_points"), "stored_n_skipped": man.get("n_skipped"),
                             "n_missing_in_store": len(mine - stored), "n_unplanned_in_store": len(stored - mine),
                             "n_q_mismatch": mism})

    # extra (adaptive, declared): contact cut on IRIS's vectors
    extra, ex_audit = [], {}
    ex = six.get("extra")
    if ex and store is not None:
        fs = store.folders(ex["stored"])
        Q = np.array([store.json(f + "/point_info.json")["q_A"] for f in fs])
        roles = [store.json(f + "/point_info.json")["role"] for f in fs]
        d = Cell(cg, float(ex["a_c"])).dmin_many(Q) if len(Q) else np.array([])
        for f, q, r, dd in zip(fs, Q, roles, d):
            extra.append({"id": f"{ex['name']}:{f[len(ex['stored']) + 1:]}", "dataset": ex["name"], "role": r,
                          "q_A": q.tolist(), "dmin_A": float(dd), "a_c": float(ex["a_c"]),
                          "sg_stored": int(store.json(f + "/point_info.json")["spacegroup"])})
        man = store.json(f"{ex['stored']}/manifest.json")
        ex_audit = {"n": len(extra), "stored_n_runs": man.get("n_runs"), "roles": {r: roles.count(r) for r in sorted(set(roles))},
                    "below_cut": int((d < float(ex["dmin_cut"])).sum()), "min_dmin_A": float(d.min()) if len(d) else None}

    # space groups on IRIS's frames (spglib 1e-3) vs the stored point_info
    allf = frames + controls + planes + extra
    sg_mis, sg_counts = [], {}
    for f in allf:
        cell = Cell(cg, f["a_c"])
        f["sg"] = cell.sg(f["q_A"])
        sg_counts[f["sg"]] = sg_counts.get(f["sg"], 0) + 1
        if "sg_stored" in f and f["sg_stored"] != f["sg"]:
            sg_mis.append((f["id"], f["sg"], f["sg_stored"]))
    special = {}
    for name, idx in (six.get("special_nodes") or {}).items():
        special[name] = {"index": idx["index"], "sg": Cell(cg, float(six["datasets"][0]["a_c"])).sg(np.asarray(idx["index"]) * sc),
                         "expected": idx["sg"]}

    grid = {"built": True, "kind": "six_component", "steps_A": sc[[0, 3]].tolist(),
            "datasets": datasets, "audit": audit, "planes": pl_audit, "extra": ex_audit,
            "sg_counts": {str(k): v for k, v in sorted(sg_counts.items())}, "sg_mismatch": sg_mis[:20],
            "n_sg_mismatch": len(sg_mis), "special_nodes": special,
            "frames": allf, "n_frames": len(allf),
            "n_by_role": {r: sum(f["role"] == r for f in allf) for r in sorted({f["role"] for f in allf})},
            "budget": cfg["run"]["budget_runs"]}
    return {"grid": grid, "last_node": "f2"}
