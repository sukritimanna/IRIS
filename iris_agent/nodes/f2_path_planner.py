"""f2 Path Planner (Methods 4.2): select modes (R1-R5, c1) -> certify vectors (c2) -> size the grid
(D1-D5, c3) -> build r(Q) = r0 + sum_i Q_i e_i on the fixed parent lattice -> audit every frame.

Vectors come from f1 (the stored ISODISTORT mode matrix at the child amplitude). The movie vectors
the 12 Sep grid was built from (<reference_grid>/01_eigenvectors/df_*.npy, the ISODISTORT movie peak
frame) are used only for the calibration check s_i = A_child / A_movie (c2 check 3).
Q_i is in Å of A_p on calibrated, translation-free vectors (Q_i = A_p,child reproduces the child).
"""
from __future__ import annotations

import itertools
import json

import numpy as np

from ..engines.frames import frame_frac, polar_expected_sg, second_component
from ..engines.stored_isodistort import match_atoms
from ..paths import from_config
from ..rules.select_modes import intersection, parse_tree, select_for

SYMPREC = 1e-2                  # strict symmetry tolerance for c2 check 4 and the frame audit
LADDER = (1e-4, 1e-3, 1e-2, 1e-1)


def _structure(r0: dict, frac):
    from pymatgen.core import Lattice, Structure
    return Structure(Lattice(r0["lattice"]), r0["species"], frac, coords_are_cartesian=False)


def _sg(s, symprec=SYMPREC):
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    try:
        return SpacegroupAnalyzer(s, symprec=symprec).get_space_group_number()
    except Exception:
        return None


def _dmin(s) -> float:
    d = s.distance_matrix
    return float(d[np.triu_indices(len(s), 1)].min())


def child_in_parent_frame(r0s, child_cif):
    """c2 check 1 + the child displacement for calibration: map the child onto the parent supercell
    (StructureMatcher), then species-constrained Hungarian assignment. Returns (dfrac, max_disp_A)."""
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.core import Structure
    C = Structure.from_file(child_cif)
    M = StructureMatcher(primitive_cell=False, attempt_supercell=True, scale=True,
                         ltol=0.3, stol=0.5, angle_tol=15).get_s2_like_s1(r0s, C)
    if M is None:
        return None, None
    perm = match_atoms(r0s, M)
    d = M.frac_coords[perm] - r0s.frac_coords
    d -= np.round(d)
    d -= d.mean(axis=0)                                         # centre of mass fixed
    return d, float(np.linalg.norm(d @ r0s.lattice.matrix, axis=1).max())


def align_domain(r0s, d, target):
    """The matcher returns one of the symmetry-equivalent child domains. Apply every operation of the
    parent supercell to the child displacement field and keep the image with the largest overlap with
    `target` (sum of the calibrated vectors at the child amplitudes), as step4_generate_nd.py does."""
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    L, f = r0s.lattice.matrix, r0s.frac_coords
    best, best_s = d, float(((d @ L) * (target @ L)).sum())
    for op in SpacegroupAnalyzer(r0s, symprec=1e-3).get_symmetry_operations():
        R, t = op.rotation_matrix, op.translation_vector
        fm = (f @ R.T + t) % 1.0
        new = np.zeros_like(d)
        for i in range(len(f)):
            dd = f - fm[i]
            dd -= np.round(dd)
            new[int(np.argmin(np.linalg.norm(dd @ L, axis=1)))] = d[i] @ R.T
        s = float(((new @ L) * (target @ L)).sum())
        if s > best_s:
            best, best_s = new, s
    return best


def f2_path_planner(state: dict) -> dict:
    cfg, dec = state["config"], state["decomposition"]
    P, pol = from_config(cfg), cfg["policy"]
    over = state.get("overrides", {}).get("f2", {})
    irreps = dec["irreps"]

    # ---- select modes (R1-R5, c1) ------------------------------------------------------------
    sel = select_for(dec, pol, over.get("r5_decision"))          # the R5 answer is applied inside the rules
    out = {"selection": sel, "last_node": "f2"}
    if sel["code"] != "OK":
        out["grid"] = {"built": False, "reason": sel["code"]}
        return out
    active = sel["active"]
    if pol.get("path"):                                    # straight-line irrep path (HfO2 T1-T5)
        from .f2_path import f2_path
        return {**f2_path(state), "selection": sel}
    if pol.get("plane2"):                                  # two-component plane of one irrep (live BaTiO3 GM4-)
        from .f2_plane2 import f2_plane2
        return {**f2_plane2(state), "selection": sel}
    if pol.get("components") and (pol.get("grid") or {}).get("six"):        # six single components (BiFeO3)
        from .f2_grid6 import f2_grid6
        return {**f2_grid6(state), "selection": sel}

    # ---- certify vectors (c2) ----------------------------------------------------------------
    r0 = dec["vectors"]["r0"]
    r0s = _structure(r0, r0["frac"])
    L = np.array(r0["lattice"])
    N = len(r0["species"])
    cert = {}
    child_d, child_dmax = child_in_parent_frame(r0s, state["inputs"]["child_cif"])
    cert["atom_matching"] = {"max_disp_A": child_dmax, "limit_A": 2.0,
                             "isodistort_max_disp_A": dec["isodistort"]["max_displacement_A"]}
    vec, trans, calib, single, ap_used = {}, {}, {}, {}, {}
    # the movie vectors are stored in the movie's atom order = the stored Q=0 frame's order
    # (paths.movie_grid / paths.movie_vectors when the replayed grid was not built from them, e.g. Ca3Ti2O7)
    movie_perm = None
    mgrid = P.repo("movie_grid") if P.has("movie_grid") else (P.repo("reference_grid") if P.has("reference_grid") else None)
    mvdir = P.repo("movie_vectors") if P.has("movie_vectors") else (mgrid / "01_eigenvectors" if mgrid else None)
    if mgrid and (mgrid / "grid_manifest.json").is_file():
        from ..engines.replay import ReferenceGrid, reference_grid
        ref = reference_grid(P, cfg, with_energies=False) if not P.has("movie_grid") else ReferenceGrid(mgrid)
        movie_perm = match_atoms(r0s, ref.structure(ref.origin_id()))
    fault_t = (cfg.get("faults") or {}).get("inject_translation") if cfg["run"]["mode"] == "replay" else None
    remove_t = bool(over.get("subtract_mean_displacement", pol.get("remove_translation", True)))
    check_on = over.get("single_mode_check_on", pol.get("single_mode_check_on", "fixed_parent_lattice"))
    for ir in active:
        d = np.array(dec["vectors"]["child_fields_frac"][ir])
        if fault_t and fault_t.get("irrep") == ir:            # fault injection: a rigid shift of every atom
            u = np.ones(3) / np.sqrt(3) * float(fault_t["A_per_atom"])
            d = d + np.linalg.solve(L.T, u)
        # check 2: rigid translation f_T = N |e_mean|^2 / ||e||^2, removed from every vector
        ebar = d.mean(axis=0)
        fT = float(N * np.sum((ebar @ L) ** 2) / np.sum((d @ L) ** 2))
        if remove_t:
            d = d - ebar
        trans[ir] = {"f_T": fT, "removed": remove_t}
        # calibrate to the translation-free amplitude A_p^tf = A_p sqrt(1 - f_T) (f1), so |e| = sqrt(n_cells) Å
        # per Å and Q is in Å of translation-free A_p (Methods 4.2 c2 check 3); = A_p when f_T = 0
        Ap = abs(irreps[ir].get("Ap_tf", irreps[ir]["Ap"])) if remove_t else abs(irreps[ir]["Ap"])
        ap_used[ir] = Ap
        e = d / Ap                                               # per Å of A_p
        vec[ir] = e
        # check 3: calibration. movie vector (12 Sep grid) and the child itself, both projected on e
        rec = {"Ap_child": Ap, "Ap_isodistort": abs(irreps[ir]["Ap"])}
        mv = mvdir / f"df_{ir}.npy" if mvdir else None
        if mv is not None and mv.is_file() and movie_perm is not None:
            df = np.load(mv)[movie_perm]          # movie atom order -> r0 atom order
            ec, mc = (d @ L).ravel(), (df @ L).ravel()
            rec["s_matrix_over_movie"] = float(ec @ mc / (mc @ mc))
            rec["A_movie_A"] = float(np.linalg.norm(mc))
            rec["A_child_A"] = float(np.linalg.norm(ec))
        calib[ir] = rec
        # check 4: single-mode frame built as the grid builds it (fixed parent lattice), strict at 1e-2.
        # check_on = movie_frame reproduces the 12 Sep No. 55 error: the frame on the child's cell.
        if check_on == "movie_frame":
            from pymatgen.core import Lattice, Structure
            s1 = Structure(Lattice.orthorhombic(*dec["isodistort"]["child_superstructure_abc"]), r0["species"],
                           np.array(r0["frac"]) + Ap * e)
        else:
            s1 = _structure(r0, np.array(r0["frac"]) + Ap * e)
        ladder = {str(t): _sg(s1, t) for t in LADDER}
        single[ir] = {"expected": irreps[ir]["isotropy_sg"], "sg_1e-2": ladder[str(SYMPREC)],
                      "ladder": ladder, "built_on": check_on}
    if child_d is not None:
        child_d = align_domain(r0s, child_d, sum(ap_used[ir] * vec[ir] for ir in active))
        for ir in active:
            ev = (vec[ir] @ L).ravel()
            calib[ir]["child_projection_Ap"] = float((child_d @ L).ravel() @ ev / (ev @ ev))   # = Ap_child
        cert["overall_child_disp_A"] = float(np.linalg.norm(child_d @ L))
    cert.update({"translation": trans, "calibration": calib, "single_mode": single})

    # ---- size the grid (D1-D5, c3) -----------------------------------------------------------
    # one (q_max, dq) for every axis, or per irrep under policy.grid.axes (InMnO3: K3 and GM2- differ)
    g = dict(pol["grid"])
    per = {ir: dict((g.get("axes") or {}).get(ir) or {"q_max": g["q_max"], "dq": g["dq"]}) for ir in active}
    if over.get("densify"):                                                      # G5 THIN_GRID -> f2
        for a in per.values():
            a["dq"] = a["dq"] / float(over["densify"])
    n = sum(irreps[i]["free_components"] or 1 for i in active)                   # D1
    axes = {}
    for ir, a in per.items():
        k = int(round(a["q_max"] / a["dq"]))
        axes[ir] = (np.arange(-k, k + 1) * a["dq"]).round(10)
    ms = {ir: len(ax) for ir, ax in axes.items()}                                # D2
    N_grid = int(np.prod(list(ms.values())))
    uniform = len(set(ms.values())) == 1 and len(per) and all(per[i] == next(iter(per.values())) for i in per)
    m = next(iter(ms.values())) if len(set(ms.values())) == 1 else ms
    budget = cfg["run"]["budget_runs"]
    anchors = pol.get("anchors", []) or []
    psg, csg, nodes = parse_tree(dec["tree"], set(dec["strain"]) - set(irreps))   # pure-strain irreps only
    descent = {}
    for r in range(len(active) + 1):
        for sub in itertools.combinations(active, r):
            node = intersection(set(sub), nodes, psg)
            descent["+".join(sub) or "0"] = node.sg if node else None
    sizing = {"n": n, "m": m, "N": N_grid, "budget": budget,
              "q_max": per[active[0]]["q_max"] if uniform else {i: a["q_max"] for i, a in per.items()},
              "dq": per[active[0]]["dq"] if uniform else {i: a["dq"] for i, a in per.items()},
              "full_grid": N_grid + len(anchors) <= budget, "descent_tree": descent,
              "rule": "D2 full grid" if N_grid + len(anchors) <= budget else "D3 needed"}
    if not sizing["full_grid"]:
        out["grid"] = {"built": False, "reason": "OVER_BUDGET", "sizing": sizing, "certify": cert}
        return out

    # ---- build and audit ----------------------------------------------------------------------
    f0 = np.array(r0["frac"])
    points = [(dict(zip(active, qs)), "", None) for qs in itertools.product(*[axes[ir] for ir in active])]
    points += [({ir: float(a["Q"].get(ir, 0.0)) for ir in active}, f"anchor_{a['name']}", None) for a in anchors]
    # polar part (policy.grid.polar): a two-component irrep sampled in (Q, phi) on a declared wedge, the
    # secondary on its own axis; the second component comes from a parent-lattice translation (120 deg)
    pol_g = g.get("polar")
    polar_info = None
    if pol_g:
        pir, sec = pol_g["irrep"], pol_g["secondary"]
        e2, polar_info = second_component(vec[pir], np.array(r0["frac"]), L, r0["species"], pol_g["translation"])
        vec[f"{pir}@c2"] = e2
        polar_info.update({"irrep": pir, "secondary": sec, "tag": pol_g.get("tag", "hat"),
                           "wedge_deg": [min(pol_g["phi_deg"]), max(pol_g["phi_deg"])],
                           "reduction": pol_g.get("reduction", ""), "n": len(pol_g["Q"]) * len(pol_g["phi_deg"]) * len(pol_g["P"])})
        for q in pol_g["Q"]:
            for ph in pol_g["phi_deg"]:
                for pp in pol_g["P"]:
                    points.append(({pir: float(q), sec: float(pp)}, polar_info["tag"], float(ph)))
        sizing["polar"] = polar_info
        if len(points) > budget:
            out["grid"] = {"built": False, "reason": "OVER_BUDGET", "sizing": {**sizing, "full_grid": False}, "certify": cert}
            return out
    # D4 (policy.d4): hard-secondary scans. Each secondary held at zero is scanned along its own vector at
    # declared base points of the primaries (cubic origin, ring, child); f5 fits each scan and G5 compares the
    # energy the secondary would release with the smallest energy difference the run interprets.
    d4 = pol.get("d4")
    d4_info = None
    if d4:
        d4_info = {"scans": [], "vectors": {}}
        held = set(sel.get("held_at_zero") or [])
        for sec in sorted({s_["irrep"] for s_ in d4["scans"]}):
            if sec not in held:
                raise ValueError(f"D4 scan of {sec}: not a secondary held at zero (held: {sorted(held)})")
            d = np.array(dec["vectors"]["child_fields_frac"][sec])
            ebar = d.mean(axis=0)
            fT = float(N * np.sum((ebar @ L) ** 2) / np.sum((d @ L) ** 2))
            d = d - ebar
            Ap_s = abs(irreps[sec].get("Ap_tf", irreps[sec]["Ap"]))
            vec[sec] = d / Ap_s
            ev = (vec[sec] @ L).ravel()
            d4_info["vectors"][sec] = {"Ap_child": Ap_s, "f_T": fT,
                                       "child_projection_Ap": float((child_d @ L).ravel() @ ev / (ev @ ev)) if child_d is not None else None}
        for s_ in d4["scans"]:
            base = {ir: float(s_["base"].get(ir, 0.0)) for ir in active}
            ratio = {ir: (base[ir] / ap_used[ir]) for ir in active}
            amps = [round(float(a), 10) for a in s_["amplitudes"]]
            tag = f"d4_{s_['name']}"
            d4_info["scans"].append({"name": s_["name"], "tag": tag, "irrep": s_["irrep"], "base": base,
                                     "base_over_child": ratio, "amplitudes": amps})
            for a in amps:
                points.append(({**base, s_["irrep"]: a}, tag, None))
        sizing["d4"] = {"frames": sum(len(x["amplitudes"]) for x in d4_info["scans"])}
        if len(points) > budget:
            out["grid"] = {"built": False, "reason": "OVER_BUDGET", "sizing": {**sizing, "full_grid": False}, "certify": cert}
            return out
    # R5 anchor_only: one frame per removed borderline irrep at the child amplitudes of the axes plus its own child
    # amplitude, so that f5 reports the energy the irrep releases at the child against the nearest grid point
    r5_info = None
    if sel.get("r5_anchors"):
        r5_info = {"decision": sel["r5_decision"], "anchors": []}
        for ir in sel["r5_anchors"]:
            d = np.array(dec["vectors"]["child_fields_frac"][ir])
            d = d - d.mean(axis=0)
            Ap_r = abs(irreps[ir].get("Ap_tf", irreps[ir]["Ap"]))
            vec[ir] = d / Ap_r
            base = {a: float(ap_used[a]) for a in active}
            tag = f"r5_anchor_{ir}"
            points.append(({**base, ir: float(Ap_r)}, tag, None))
            r5_info["anchors"].append({"irrep": ir, "tag": tag, "base": base, "amplitude": float(Ap_r)})
        sizing["r5_anchors"] = len(r5_info["anchors"])
        if len(points) > budget:
            out["grid"] = {"built": False, "reason": "OVER_BUDGET", "sizing": {**sizing, "full_grid": False}, "certify": cert}
            return out
    frames, sg_count = [], {}
    for idx, (Q, tag, phi) in enumerate(points):
        keys = active + [k for k in Q if k not in active]
        fr = {"id": idx, "Q": {ir: round(float(Q.get(ir, 0.0)), 10) for ir in keys}, "tag": tag}
        if phi is not None:
            fr.update({"polar": polar_info["irrep"], "phi_deg": phi})
        s = _structure(r0, frame_frac(fr, f0, vec, keys))
        if tag.startswith("d4_"):
            nz = {ir for ir in keys if abs(fr["Q"][ir]) > 1e-12}
            node = intersection(nz, nodes, psg)
            exp_sg = node.sg if node else None
        elif phi is not None:
            exp_sg = polar_expected_sg(phi, fr["Q"][polar_info["secondary"]], *pol_g["expected_sg"])
        else:
            nz = "+".join(ir for ir in active if abs(fr["Q"][ir]) > 1e-12) or "0"
            exp_sg = descent[nz]
        sg = _sg(s)
        fr.update({"expected_sg": exp_sg, "sg": sg, "d_min": round(_dmin(s), 4)})
        frames.append(fr)
        sg_count[str(sg)] = sg_count.get(str(sg), 0) + 1
    rd = P.run_dir(cfg["thread_id"])
    gdir = P.out(rd, "f2_grid")
    gdir.mkdir(exist_ok=True)
    np.savez(P.out(gdir, "vectors.npz"), r0_frac=f0, lattice=L, **{f"e_{ir}": v for ir, v in vec.items()})
    P.out(gdir, "grid_manifest.json").write_text(json.dumps(frames, indent=0))
    out["grid"] = {
        "built": True, "active": active, "units": "Q in Å of A_p (calibrated, translation-free)",
        "lattice": "fixed parent supercell (strain policy %s)" % pol["strain_policy"],
        "certify": cert, "sizing": sizing, "n_frames": len(frames),
        "n_grid": N_grid, "n_anchors": len(anchors), "sg_count": sg_count,
        "frames": frames, "vectors": {ir: np.asarray(v).tolist() for ir, v in vec.items()}, "polar": polar_info, "d4": d4_info, "r5": r5_info,
        "files": {"manifest": str(P.out(gdir, "grid_manifest.json")), "vectors": str(P.out(gdir, "vectors.npz"))},
    }
    return out
