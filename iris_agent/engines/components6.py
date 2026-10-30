"""Six single-component vectors of a cubic-perovskite GM4- (+) R5- pair, from the stored ISODISTORT fields.

Used for BiFeO3 (Pm-3m -> R3c, GM4-(a,-a,-a) + R5-(a,-a,a), Bi at the origin). ISODISTORT gives each irrep
along the child direction only; the 6D grid needs every component separately:

  P_i  (i = x, y, z): the i-th Cartesian component of the GM4- field (T1u is a polar vector, so the
       x, y, z parts of every atom's displacement are the three components), rigid translation removed;
  R_i  : the part of the R5- field that is a rotation about x_i: O on bond axis a (a != i) moving along
       the third axis b (b != i, a).

Everything is re-derived, nothing assumed:
  - the components are a partition of the stored field (sum = field, exact);
  - closure: every one of the 48 cubic point operations about Bi (x {identity, odd parent translation}
    = 96 for the R point) maps the six component fields onto +- each other (signed permutation, derived
    by projection; any residual is reported);
  - the fields are folded onto a target cell (e.g. the 10-atom fcc(2a_c) cell of the 6D grid) by
    matching parent positions modulo that cell's lattice, and compared atom by atom with the grid's
    own basis vectors (composition, normalisation, signs).

Units: |component field| on a frame of n parent cells = A_p sqrt(n) (Methods; G1 mode_norms rule).
"""
from __future__ import annotations

import itertools

import numpy as np

AX = "xyz"


def parent_frame(iso, a_c: float):
    """Atoms of ISODISTORT's undistorted supercell in parent coordinates (cubic units) and the GM4- / R5-
    fields at the child amplitude in Cartesian Å (cubic frame). iso = engines.stored_isodistort object."""
    sub = iso.subgroup()
    M = np.array(sub["basis"], float)                  # rows: child lattice vectors in parent units
    o = np.array(sub["origin"], float)
    r0, fields, _ = iso.irrep_fields()
    p = r0.frac_coords @ M + o                          # parent fractional coordinates
    p = p - np.floor(p.min(axis=0))                     # any integer shift, positions only
    snap = np.round(2 * p) / 2                          # parent sites sit on the half-integer lattice
    dev = float(np.abs(p - snap).max())                 # (the stored origin and coordinates carry 5 decimals)
    if dev > 1e-3:
        raise ValueError(f"supercell atoms are {dev:.2e} off the parent sites: not the undistorted parent frame")
    spec = [str(x) for x in r0.species]
    u = {ir: d @ M * a_c for ir, d in fields.items()}   # Cartesian, cubic frame
    return snap, spec, u, dev


def sites(p, spec, tol=1e-4):
    """Parent sublattice of every atom: A (integer), B (half-integer), O bond axis (the integer coordinate)
    and the parent cell of its B neighbour (O at B - 1/2 e_axis)."""
    out = []
    for r, s in zip(p, spec):
        half = np.abs(r - np.round(r)) > 0.25
        if not half.any():
            out.append({"site": "A", "cell": np.round(r).astype(int), "axis": None})
        elif half.all():
            out.append({"site": "B", "cell": np.round(r - 0.5).astype(int), "axis": None})
        else:
            ints = np.where(~half)[0]
            if len(ints) != 1:
                raise ValueError(f"atom {s} at {r} is not on a cubic-perovskite site")
            a = int(ints[0])
            b = r.copy()
            b[a] += 0.5
            out.append({"site": "O", "cell": np.round(b - 0.5).astype(int), "axis": a})
    return out


def split(p, spec, uG, uR):
    """(6, N, 3): P_x, P_y, P_z, R_x, R_y, R_z component fields (GM4- translation removed per component)."""
    st = sites(p, spec)
    n = len(spec)
    C = np.zeros((6, n, 3))
    for i in range(3):
        C[i, :, i] = uG[:, i]
        C[i, :, i] -= C[i, :, i].mean()                 # rigid translation along x_i out
    for k, s in enumerate(st):
        if s["site"] != "O":
            if np.abs(uR[k]).max() > 1e-9:
                raise ValueError("R5- field moves a non-O atom: not a pure octahedral rotation")
            continue
        a = s["axis"]
        if abs(uR[k, a]) > 1e-9:
            raise ValueError("R5- field moves an O along its bond: not a pure octahedral rotation")
        for b in range(3):
            if b != a:
                i = 3 - a - b                            # rotation axis: the third one
                C[3 + i, k, b] = uR[k, b]
    return C, st


def point_ops():
    ops = []
    for perm in itertools.permutations(range(3)):
        for sg in itertools.product([1, -1], repeat=3):
            M = np.zeros((3, 3))
            for i, q in enumerate(perm):
                M[i, q] = sg[i]
            ops.append(M)
    return ops


def _index(p, spec, L_par, tol=1e-6):
    """position -> atom index, periodic in the supercell lattice L_par (rows, parent units)."""
    inv = np.linalg.inv(L_par)

    def find(r, s):
        for j, (q, t) in enumerate(zip(p, spec)):
            if t != s:
                continue
            d = (r - q) @ inv
            if np.allclose(d, np.round(d), atol=tol):
                return j
        raise ValueError("image not found")
    return find


def closure(p, spec, C, L_par):
    """For each of the 96 operations (48 point ops about the A site x {0, odd parent translation}) the 6x6
    matrix G with C'(g) = G C, by projection, and the largest residual. Returns (mats, max residual).
    L_par (rows, parent units) must be invariant under the cubic point operations (fcc or simple cubic)."""
    find = _index(p, spec, L_par)
    Cm = C.reshape(6, -1)
    nrm = (Cm * Cm).sum(1)
    mats, worst = [], 0.0
    for g in point_ops():
        for t in (np.zeros(3), np.array([1.0, 0.0, 0.0])):
            perm = [find(g @ r + t, s) for r, s in zip(p, spec)]
            G = np.zeros((6, 6))
            for k in range(6):
                v = np.zeros_like(C[k])
                for i, j in enumerate(perm):
                    v[j] = g @ C[k, i]
                c = Cm @ v.ravel() / nrm
                worst = max(worst, float(np.abs(v.ravel() - c @ Cm).max()))
                G[:, k] = c
            mats.append(G)
    return mats, worst


def is_signed_permutation(G, tol=1e-6):
    Gi = np.rint(G)
    return bool(np.allclose(G, Gi, atol=tol) and (np.abs(Gi).sum(0) == 1).all() and (np.abs(Gi).sum(1) == 1).all())


def fold(p, spec, C, target_frac_parent, target_spec, L_target):
    """Component fields on a target cell: target atom j takes the field of the supercell atom at the same
    parent position modulo the target lattice L_target (rows, parent units). The fields must be periodic
    in L_target (checked: every image gives the same vector). Returns (6, M, 3)."""
    inv = np.linalg.inv(L_target)
    out = np.zeros((6, len(target_spec), 3))
    for j, (r, s) in enumerate(zip(target_frac_parent, target_spec)):
        hits = [i for i, (q, t) in enumerate(zip(p, spec))
                if t == s and np.allclose((q - r) @ inv, np.round((q - r) @ inv), atol=1e-6)]
        if not hits:
            raise ValueError(f"target atom {s} at {r} has no image in the ISODISTORT supercell")
        v = C[:, hits, :]
        if np.abs(v - v[:, :1, :]).max() > 1e-8:
            raise ValueError("component fields are not periodic in the target lattice")
        out[:, j, :] = v[:, 0, :]
    return out


def compositions(C, st):
    """Per-component weights by sublattice (unit vector over the 5 atoms of one formula unit), and the
    norm of the field. P_i: A, B, O parallel (bond axis = i), O perpendicular; R_i: O moving."""
    out = {}
    for i in range(3):
        f = C[i, :, i]
        groups = {"A": [], "B": [], "O_par": [], "O_perp": []}
        for k, s in enumerate(st):
            key = s["site"] if s["site"] != "O" else ("O_par" if s["axis"] == i else "O_perp")
            groups[key].append(f[k])
        out[f"P_{AX[i]}"] = {g: (float(np.mean(v)), float(np.ptp(v)) if v else 0.0) for g, v in groups.items()}
    return out


def analyse(iso, a_c: float, polar: str, rotation: str, grid=None) -> dict:
    """Everything f1 records for the six components. grid = (basis module, symmetry module) of the stored 6D
    grid toolkit (bfo6d), or None. The closure is evaluated on the folded cell (its lattice is invariant under
    the cubic operations; ISODISTORT's 30-atom hexagonal cell is not, so images there are ambiguous)."""
    p, spec, u, dev = parent_frame(iso, a_c)
    C, st = split(p, spec, u[polar], u[rotation])
    n = len(spec) / 5
    uG = u[polar] - u[polar].mean(0)
    out = {"irreps": [polar, rotation], "a_c_A": a_c, "n_parent_cells_supercell": n,
           "site_snap_A_parent_units": dev,
           "partition_residual_A": float(max(np.abs(C[:3].sum(0) - uG).max(), np.abs(C[3:].sum(0) - u[rotation]).max())),
           "component_Ap": [float(np.linalg.norm(C[k]) / np.sqrt(n)) for k in range(6)],
           "irrep_Ap_tf": {polar: float(np.linalg.norm(uG) / np.sqrt(n)), rotation: float(np.linalg.norm(u[rotation]) / np.sqrt(n))},
           "labels": ["P1", "P2", "P3", "R1", "R2", "R3"]}
    comp = {}
    for i in range(3):
        a = float(np.linalg.norm(C[i]) / np.sqrt(n))
        sgn = float(np.sign(C[i][[k for k, s in enumerate(st) if s["site"] == "A"], i].mean()))
        w = {}
        for key in ("A", "B", "O_par", "O_perp"):
            ks = [k for k, s in enumerate(st) if (s["site"] if s["site"] != "O" else ("O_par" if s["axis"] == i else "O_perp")) == key]
            w[key] = float(sgn * C[i][ks, i].mean() / a)
        comp[f"P{i + 1}"] = w
    out["composition_unit_fu"] = comp
    if grid is None:
        return out
    bb, sym = grid
    lat, cart, spc, meta = bb.build_cell(bb.A_C)
    L10 = np.array(bb.LATTICE_UNIT, float)
    t = cart / bb.A_C
    F = fold(p, spec, C, t, spc, L10)
    B = np.asarray(bb.basis_vectors(bb.A_C))
    n10 = len(spc) / 5
    q, res = [], []
    for k in range(6):
        s = float((F[k] * B[k]).sum() / (B[k] ** 2).sum())
        q.append(s)
        res.append(float(np.abs(F[k] - s * B[k]).max()))
    mats, worst = closure(t, spc, F, L10)
    # unit vectors on the target cell (|V|^2 = n_cells, A_p convention) with the sign convention of the grid,
    # derived from the geometry: P_i > 0 moves the A site (Bi) along +x_i; R_i > 0 rotates the octahedron
    # around the B site (Fe) of the even-parity cell right-handed about +x_i (u_O = w x r, w along +x_i)
    st10 = sites(t, spc)
    V = np.zeros_like(F)
    signs = []
    for k in range(6):
        v = F[k] * np.sqrt(n10) / np.linalg.norm(F[k])
        if k < 3:
            s_ = np.sign(sum(v[j, k] for j, s in enumerate(st10) if s["site"] == "A"))
        else:
            e = np.eye(3)[k - 3]
            fe = [j for j, s in enumerate(st10) if s["site"] == "B" and not (s["cell"] % 2).any() and s["cell"].sum() % 2 == 0][0]
            acc = 0.0
            for j, s in enumerate(st10):
                if s["site"] == "O" and np.array_equal(s["cell"], st10[fe]["cell"]):
                    acc += np.cross(e, (t[j] - t[fe]) * bb.A_C) @ v[j]
            s_ = np.sign(acc)
        signs.append(int(s_))
        V[k] = s_ * v
    mine = {np.rint(G).astype(int).tobytes() for G in mats}
    theirs = {np.asarray(G).astype(int).tobytes() for G in sym.mode_matrices()}
    # the stored grid's child node: the operation taking ISODISTORT's domain onto all-positive components
    qv = np.array(q)
    best = max((np.rint(G) @ qv for G in mats), key=lambda v: (np.sign(v) > 0).sum())
    pstep, rstep = (x / 2 for x in bb.child_amplitudes())
    out["grid"] = {"cell_atoms": len(spc), "n_parent_cells": n10,
                   "basis_norm_sq": [float((B[k] ** 2).sum()) for k in range(6)],
                   "child_q_isodistort_domain": q, "child_q_positive_domain": best.tolist(),
                   "child_node": [float(best[k] / (pstep if k < 3 else rstep)) for k in range(6)],
                   "grid_steps_A": [float(pstep), float(rstep)],
                   "fold_residual_A": res,
                   "closure_residual": worst, "closure_n_ops": len(mats),
                   "closure_signed_permutations": all(is_signed_permutation(G, 1e-4) for G in mats),
                   "closure_distinct": len(mine), "matrices_equal_grid_toolkit": mine == theirs,
                   "grid_child_Ap": [float(x) for x in bb.child_amplitudes()],
                   "grid_composition": {k: float(v) for k, v in bb.composition_from_isodistort()[0].items()},
                   "cell": {"lattice_unit": L10.tolist(), "frac_parent": t.tolist(), "species": list(spc),
                            "a_c_A": float(bb.A_C)},
                   "vectors_unit": V.tolist(), "sign_from_convention": signs,
                   "vectors_vs_grid_max_A": float(np.abs(V - B).max()),
                   "mats": [np.rint(G).astype(int).tolist() for G in mats]}
    return out
