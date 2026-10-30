"""f1 Crystallographer: standardize -> subgroup -> basis -> decomposition (stored ISODISTORT responses; in run.mode
live the same responses are fetched during the run by engines/live_iso.py and read from the run folder).

Wraps existing code (read-only):
  demo/staged_walkthrough/step1_standardize.py   tolerance_ladder (pymatgen/spglib)
  demo/staged_walkthrough/step2_subgroup.py      group_index, is_true_subgroup
  demo/staged_walkthrough/step3_isodistort.py    parse_modes_details, parse_tree
  iris/lib/basis_search.py                       find_basis (independent atom-matching basis search)
  <reference_run>/step1_standardize/step1_result.json   stored FINDSYM response (cross-check only)
  <reference_run>/step3_isodistort/04_raw_isodistort/*  stored ISODISTORT responses (no web calls)
"""
from __future__ import annotations

import contextlib
import io
import json

import numpy as np

from ..engines import legacy
from ..engines.stored_isodistort import direction_of, free_components, irrep_of, load
from ..paths import from_config


_BASIS_CACHE: dict = {}


def _find_basis(P, parent, child, cell_tol):
    """iris/lib/basis_search.find_basis, cached per process (it takes ~25 s; retries reuse it)."""
    key = (parent, child, cell_tol)
    if key not in _BASIS_CACHE:
        bs = legacy.iris_lib(P, "basis_search")
        with contextlib.redirect_stdout(io.StringIO()):
            _BASIS_CACHE[key] = [(np.asarray(b).tolist(), list(o), float(d))
                                 for b, o, d in bs.find_basis(parent, child, cell_tol=cell_tol)]
    return _BASIS_CACHE[key]


def _spglib_sg(structure, symprec=1e-2) -> int:
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    return SpacegroupAnalyzer(structure, symprec=symprec).get_space_group_number()


Z_LATTICE = {"P": 1, "A": 2, "B": 2, "C": 2, "I": 2, "F": 4}


def _centering(psg: int, sub: dict, child_lattice) -> dict:
    """Lattice points per conventional cell of parent and child (R: 3 on hexagonal axes, 1 on rhombohedral):
    ISODISTORT's basis is conventional child in conventional parent units, so det(basis) = s z_child / z_parent."""
    from pymatgen.symmetry.groups import SpaceGroup
    lp = SpaceGroup.from_int_number(psg).symbol[0]
    lc = sub["symbol"][0]
    hexax = abs(child_lattice_gamma(child_lattice) - 120.0) < 0.5

    def z(letter, hexax):
        return (3 if hexax else 1) if letter == "R" else Z_LATTICE[letter]
    return {"parent": lp, "child": lc, "child_hexagonal_axes": hexax, "z_parent": z(lp, False), "z_child": z(lc, hexax)}


def child_lattice_gamma(L) -> float:
    a, b = np.asarray(L[0], float), np.asarray(L[1], float)
    return float(np.degrees(np.arccos(a @ b / np.linalg.norm(a) / np.linalg.norm(b))))


def f1_crystallographer(state: dict) -> dict:
    cfg = state["config"]
    P = from_config(cfg)
    over = state.get("overrides", {}).get("f1", {})
    parent, child = state["inputs"]["parent_cif"], state["inputs"]["child_cif"]
    live_info = None
    if cfg["run"]["mode"] == "live":                 # the decomposition is computed now (engines/live_iso), not stored
        from ..engines.live_iso import ensure_live_decomposition, live_paths
        live_info = ensure_live_decomposition(P, cfg, parent, child, refresh=bool(over.get("refresh_isodistort")))
        P = live_paths(P, cfg, live_info)
    step1 = legacy.walkthrough(P, "step1_standardize")
    step2 = legacy.walkthrough(P, "step2_subgroup")
    step3 = legacy.walkthrough(P, "step3_isodistort")

    # 1. standardize: spglib tolerance ladder (+ stored FINDSYM response as cross-check)
    ladders = {"parent": step1.tolerance_ladder(parent), "child": step1.tolerance_ladder(child)}
    findsym = {}
    f = P.repo("reference_run") / "step1_standardize" / "step1_result.json"
    if f.is_file():
        r = json.loads(f.read_text())
        findsym = {k: r.get(k, {}).get("findsym", {}).get("sg_number") for k in ("parent", "child")}

    # 2. subgroup relation (pymatgen ITA tables)
    psg, csg = cfg["expected"]["parent_sg"], cfg["expected"]["child_sg"]
    t_index = step2.group_index(psg, csg)
    is_sub = step2.is_true_subgroup(psg, csg)

    # 3. basis: stored ISODISTORT subgroup + independent atom-matching search
    iso = load(str(P.repo("isodistort_stored")))
    sub = iso.subgroup()
    B = np.array(sub["basis"], dtype=float)
    basis_search = {"skipped": True}
    if not over.get("skip_basis_search"):
        # dmax: largest per-atom displacement the atom matching accepts (recovery ladder widens it)
        dmax = float(over.get("basis_dmax_A", cfg["policy"].get("basis_dmax_A", 2.0)))
        found = _find_basis(P, parent, child, over.get("basis_cell_tol", 0.18))
        cands = [c for c in found if c[2] <= dmax]
        if cands:
            b0, origin0, dmax0 = cands[0]
            basis_search = {"skipped": False, "n_candidates": len(cands), "basis": b0, "origin": origin0,
                            "det": round(float(np.linalg.det(np.array(b0)))), "max_disp_A": dmax0,
                            "dmax_A": dmax}
        else:
            basis_search = {"skipped": False, "n_candidates": 0, "dmax_A": dmax,
                            "smallest_max_disp_A": min((c[2] for c in found), default=None)}

    # 4. decomposition from the stored modes-details response (existing parser)
    md = step3.parse_modes_details(iso.modes_details)
    tree = {"parent": psg, "child": csg, "chain": step3.parse_tree(iso.tree_text)}
    isotropy = iso.isotropy_by_irrep()
    labels = {irrep_of(l): direction_of(l) for l in iso.mode_labels.values()}
    irreps = {ir: {"As": v["As"], "Ap": v["Ap"], "direction": labels.get(ir),
                   "free_components": free_components(labels[ir]) if ir in labels else None,
                   "isotropy_sg": isotropy.get(ir, {}).get("sg")}
              for ir, v in md["displacive_totals"].items()}
    strain = {s["irrep"]: s["amplitude"] for s in md["strain_amplitudes"]}       # last component per irrep (legacy)
    strain_components = {}                                                         # every component, ISODISTORT order
    for s in md["strain_amplitudes"]:
        strain_components.setdefault(s["irrep"], []).append({"label": s["label"], "amplitude": s["amplitude"]})

    # 5. space group of the decomposition rebuilt from the stored mode matrix (displacive part,
    #    parent lattice) vs the ISODISTORT subgroup vs spglib on the child CIF
    comp = iso.component_amplitudes()
    full = iso.structure({k: comp[l[l.index("["):]] for k, l in iso.mode_labels.items()})
    from pymatgen.core import Structure
    child_sg = _spglib_sg(Structure.from_file(child), 1e-3)
    rebuilt_sg = _spglib_sg(full, 1e-2)

    # vectors at the child amplitude (consumed by f2)
    r0, fields, groups = iso.irrep_fields()
    L = r0.lattice.matrix
    norms = {ir: float(np.linalg.norm(d @ L)) for ir, d in fields.items()}
    # cell counting: the frame holds n_cells parent PRIMITIVE cells, so |field| = A_p sqrt(n_cells)
    # (CsSnI3 20/5 = 4: |field| = 2 A_p = A_s; Ca3Ti2O7 48/12 = 4: |field| = 2 A_p = sqrt2 A_s, as ISODISTORT's
    # supercell there is the 24-atom A-centred primitive child cell, s = 2)
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    n_prim = len(SpacegroupAnalyzer(Structure.from_file(parent), symprec=1e-3).find_primitive())
    n_cells = len(r0) / n_prim
    dtot = sum(fields.values())
    max_disp_tf = float(np.linalg.norm((dtot - dtot.mean(axis=0)) @ L, axis=1).max())   # rigid shift removed
    # rigid-translation fraction of each irrep's field, f_T = N |mean u|^2 / ||u||^2 (Cartesian), and the
    # amplitude left once the translation is removed (the primary walk can run on these: Methods 4.2)
    for ir, d in fields.items():
        if ir in irreps:
            u = d @ L
            fT = float(len(u) * np.sum(u.mean(axis=0) ** 2) / np.sum(u ** 2)) if np.sum(u ** 2) > 0 else 0.0
            keep = np.sqrt(max(0.0, 1.0 - fT))
            irreps[ir].update({"f_T": fT, "As_tf": abs(irreps[ir]["As"]) * keep, "Ap_tf": abs(irreps[ir]["Ap"]) * keep})

    # independent route for a polar child (G1): child mapped onto r0 by StructureMatcher + assignment, centre of mass fixed
    if basis_search.get("n_candidates"):
        from .f2_path_planner import child_in_parent_frame
        try:
            basis_search["com_fixed_max_disp_A"] = child_in_parent_frame(r0, child)[1]
        except Exception as exc:
            basis_search["com_fixed_error"] = f"{type(exc).__name__}: {exc}"

    decomposition = {
        "standardize": {"ladders": {k: {str(t): sg for t, sg in v.items()} for k, v in ladders.items()},
                        "findsym_stored": findsym},
        "subgroup": {"parent_sg": psg, "child_sg": csg, "t_index": t_index, "is_true_subgroup": is_sub},
        "isodistort": {**sub, "det_basis": round(float(np.linalg.det(B))), "centering": _centering(psg, sub, L),
                       "max_displacement_A": iso.max_displacement(),
                       "max_displacement_translation_free_A": max_disp_tf,
                       "child_superstructure_abc": iso.child_superstructure_abc()},
        "basis_search": basis_search,
        "irreps": irreps, "strain": strain, "strain_components": strain_components, "overall": md["overall"], "tree": tree,
        "spacegroups": {"isodistort_subgroup": sub["sg"], "spglib_child_cif": child_sg,
                        "spglib_rebuilt_decomposition": rebuilt_sg},
        "vectors": {"r0": {"lattice": L.tolist(), "species": [str(x) for x in r0.species],
                           "frac": r0.frac_coords.tolist()},
                    "child_fields_frac": {ir: d.tolist() for ir, d in fields.items()},
                    "norm_A": norms,
                    "n_parent_primitive_cells": n_cells, "parent_primitive_atoms": n_prim,
                    "mode_ids": groups},
        "source": str(P.repo("isodistort_stored")),
        "live_isodistort": live_info,
    }

    # 6. single components of a cubic-perovskite GM4- + R5- pair (BiFeO3 6D grid): split, closure under the 96
    #    Pm-3m operations, fold onto the stored grid's 10-atom cell and compare with its basis (engines/components6)
    comp_pol = cfg["policy"].get("components")
    if comp_pol:
        from ..engines import components6
        grid = None
        if comp_pol.get("grid_toolkit", True) and P.has("grid_toolkit"):
            grid = (legacy.toolkit(P, "grid_toolkit", "basis"), legacy.toolkit(P, "grid_toolkit", "symmetry"))
        a_c = float(Structure.from_file(parent).lattice.a)
        decomposition["components"] = components6.analyse(iso, a_c, comp_pol["polar"], comp_pol["rotation"], grid)
    return {"decomposition": decomposition, "last_node": "f1"}
