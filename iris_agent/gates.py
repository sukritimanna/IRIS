"""Gates G0-G6: plain Python, no LLM. Each gate runs named tests on the node's output and returns
{"ok", "code", "detail", "tests"}. The first failing test sets the code.

A test returns None (pass), a (code, detail) tuple (fail), or SKIP (not implemented yet).
SKIP only counts as a pass in run.mode == "skeleton"; in any other mode it fails with
NOT_IMPLEMENTED, so an unimplemented test can never pass silently.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

SKIP = "SKIP"

# ---- G0: config valid ----------------------------------------------------------------------


def _intake():
    import sys
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from intake import build
    return build


def g0_intake_in_scope(s):          # build step 6: the f0 language-model intake (intake/build.py)
    return _intake().g0_in_scope(s.get("config") or {}) if (s.get("config") or {}).get("intake") else None


def g0_intake_decidable(s):
    return _intake().g0_decidable(s.get("config") or {}) if (s.get("config") or {}).get("intake") else None


def g0_intake_stored_data(s):
    return _intake().g0_stored_data(s.get("config") or {}) if (s.get("config") or {}).get("intake") else None


def g0_intake_consistent(s):
    return _intake().g0_consistent(s.get("config") or {}) if (s.get("config") or {}).get("intake") else None


def g0_matches_schema(s):
    errs = s.get("inputs", {}).get("schema_errors", [])
    return ("SCHEMA", "; ".join(errs)) if errs else None


def g0_cif_files_exist(s):
    inp = s.get("inputs", {})
    for role in ("parent", "child"):
        p = inp.get(f"{role}_cif")
        if not p or not Path(p).is_file():
            return ("CIF_MISSING", f"{role} CIF not found: {p}")
    return None


def g0_cif_space_groups(s):
    inp, exp = s.get("inputs", {}), s.get("config", {}).get("expected", {})
    for role in ("parent", "child"):
        if inp.get(f"{role}_read_error"):
            return ("CIF_UNREADABLE", f"{role}: {inp[f'{role}_read_error']}")
        got, want = inp.get(f"{role}_sg"), exp.get(f"{role}_sg")
        if got != want:
            return ("CIF_SG", f"{role} space group {got} (spglib, symprec 1e-3), expected {want}")
    return None


def g0_cif_checksums(s):
    """Replay integrity: when the config pins sha256 digests, the CIFs must be those exact files."""
    inp, exp = s.get("inputs", {}), s.get("config", {}).get("expected", {})
    for role in ("parent", "child"):
        want = exp.get(f"{role}_sha256")
        if want and inp.get(f"{role}_sha256") != want:
            return ("CIF_CHANGED", f"{role} CIF sha256 {inp.get(f'{role}_sha256')} != pinned {want}")
    return None


def g0_faults_only_in_replay(s):
    cfg = s.get("config", {})
    if cfg.get("faults") and cfg.get("run", {}).get("mode") != "replay":
        return ("FAULTS", "fault injection is allowed only in replay mode")
    return None


def g0_budget_within_limits(s):
    b = s.get("config", {}).get("run", {}).get("budget_runs")
    from .config import MAX_BUDGET
    if not isinstance(b, int) or not 0 < b <= MAX_BUDGET:
        return ("BUDGET", f"budget_runs={b} outside 1..{MAX_BUDGET}")
    return None


def g0_writes_inside_agent_root(s):
    p = s.get("config", {}).get("paths", {})
    agent, repo = Path(p.get("agent_root", "")).resolve(), Path(p.get("repo_root", "")).resolve()
    if agent == repo or not str(agent):
        return ("PATHS", "agent_root must be a separate sub-folder of repo_root")
    return None


# ---- G1: decomposition valid ----------------------------------------------------------------
def _dec(s):
    return s.get("decomposition") or {}


def g1_H_subgroup_of_G(s):
    d, exp = _dec(s), s["config"]["expected"]
    sub, iso = d.get("subgroup", {}), d.get("isodistort", {})
    if not sub.get("is_true_subgroup"):
        return ("NOT_SUBGROUP", f"#{exp['child_sg']} is not a subgroup of #{exp['parent_sg']} (pymatgen ITA)")
    if sub.get("t_index") is None or sub["t_index"] * iso.get("s", 0) != iso.get("i"):
        return ("NOT_SUBGROUP", f"index mismatch: t={sub.get('t_index')} x k={iso.get('s')} != i={iso.get('i')}")
    for role in ("parent", "child"):
        lad = d["standardize"]["ladders"][role]
        want = exp[f"{role}_sg"]
        if lad.get("0.001") != want or lad.get("0.01") != want:
            return ("SG_LADDER", f"{role}: spglib ladder {lad} not stable at {want} for symprec 1e-3..1e-2")
        fs = d["standardize"]["findsym_stored"].get(role)
        if fs is not None and fs != want:
            return ("SG_DISAGREE", f"{role}: stored FINDSYM #{fs} != expected #{want}")
    return None


def g1_basis_det_equals_k(s):
    d = _dec(s)
    iso, bs = d.get("isodistort", {}), d.get("basis_search", {})
    # ISODISTORT's basis: conventional child cell in conventional parent units, det = s z_child / z_parent
    # (z = lattice points per conventional cell; BiFeO3 R3c on hexagonal axes: 2 x 3 / 1 = 6)
    cen = iso.get("centering") or {"z_parent": 1, "z_child": 1}
    want = iso.get("s", 0) * cen["z_child"] / cen["z_parent"]
    if iso.get("det_basis") != want or iso.get("det_basis", 0) <= 0:
        return ("BASIS_DET", f"det(basis) = {iso.get('det_basis')} != s z_child/z_parent = {iso.get('s')} x "
                             f"{cen['z_child']}/{cen['z_parent']} (or left-handed)")
    if not bs.get("skipped"):
        if not bs.get("n_candidates"):
            return ("NO_BASIS", f"atom-matching basis search found no candidate within dmax {bs.get('dmax_A')} Å "
                                f"(smallest max displacement {bs.get('smallest_max_disp_A')} Å)")
        # the basis search works on the child CIF as given: a conventional centred cell (Amm2 A-centred, R3m hexagonal)
        # has det = k z_child/z_parent in parent units, a primitive cell det = k
        if bs["det"] not in (iso["s"], want):
            return ("BASIS_DET", f"basis search det {bs['det']} != k = {iso['s']} (or k z_child/z_parent = {want:g} for a centred child cell)")
        # the atom matching fixes the origin, so it finds the displacement without a rigid shift; ISODISTORT's
        # printed 'displ' keeps the shift of a polar irrep (Ca3Ti2O7 GM5-: 0.548 printed, 0.411 shift-free)
        refs = [iso["max_displacement_A"]] + ([iso["max_displacement_translation_free_A"]]
                                              if "max_displacement_translation_free_A" in iso else [])
        # for a POLAR child the origin along the polar axis is free and the basis search fixes it its own way
        # (InMnO3 0.282, ErMnO3 0.316 vs ISODISTORT shift-free 0.313, 0.299): compare instead the
        # centre-of-mass-fixed child mapping (StructureMatcher + assignment, f1) with ISODISTORT shift-free
        from .rules.select_modes import sg_is_polar
        polar_child = sg_is_polar(int(s["config"]["expected"]["child_sg"]))
        if polar_child and bs.get("com_fixed_max_disp_A") is not None and "max_displacement_translation_free_A" in iso:
            ok = abs(bs["com_fixed_max_disp_A"] - iso["max_displacement_translation_free_A"]) <= 0.01
            if not ok:
                return ("BASIS_DISAGREE", f"centre-of-mass-fixed child mapping max displacement {bs['com_fixed_max_disp_A']:.4f} Å "
                                          f"vs ISODISTORT shift-free {iso['max_displacement_translation_free_A']:.4f} Å")
        else:
            ok = min(abs(bs["max_disp_A"] - r) for r in refs) <= 0.01
        if not ok or bs["max_disp_A"] >= 2.0:
            return ("BASIS_DISAGREE", f"basis search max displacement {bs['max_disp_A']:.4f} Å vs "
                                      f"ISODISTORT {' / '.join(f'{r:.4f}' for r in refs)} Å (printed / shift-free)")
    return None


def g1_isodistort_sg_equals_spglib(s):
    sg = _dec(s).get("spacegroups", {})
    want = s["config"]["expected"]["child_sg"]
    vals = {k: sg.get(k) for k in ("isodistort_subgroup", "spglib_child_cif", "spglib_rebuilt_decomposition")}
    if set(vals.values()) != {want}:
        return ("SG_DISAGREE", f"child space groups disagree: {vals} (expected #{want})")
    return None


def g1_mode_norms_equal_As(s):
    d = _dec(s)
    """|field| of each irrep in the frame = A_p sqrt(n_cells), n_cells = parent primitive cells in the frame
    (= A_s only when n_cells = s, as for CsSnI3)."""
    nc = d.get("vectors", {}).get("n_parent_primitive_cells")
    if not nc:
        return ("DECOMP_NORM", "number of parent primitive cells in the frame not recorded")
    r = float(nc) ** 0.5
    for ir, v in d.get("irreps", {}).items():
        nrm = d["vectors"]["norm_A"].get(ir)
        if nrm is None or abs(nrm - abs(v["Ap"]) * r) > 2e-4 * r:
            return ("DECOMP_NORM", f"{ir}: |field| {nrm} Å != A_p {v['Ap']} x sqrt({nc:g}) "
                                   "(stored mode matrix vs amplitudes)")
    return None


def g1_components_consistent(s):
    """policy.components only: the six single components partition the stored fields, carry A_p / sqrt(3)
    each, are closed under the 96 operations (signed permutations), and fold onto the stored grid's basis."""
    pol = s["config"]["policy"].get("components")
    if not pol:
        return None
    c = _dec(s).get("components")
    if not c:
        return ("COMPONENTS", "policy.components set but f1 recorded no components")
    tol = float(pol.get("tol_A", 1e-4))            # stored ISODISTORT numbers carry 5 decimals
    if c["partition_residual_A"] > 1e-9:
        return ("COMPONENTS", f"components do not sum to the stored fields ({c['partition_residual_A']:.2e} Å)")
    irr = _dec(s).get("irreps", {})
    for k, ir in ((0, pol["polar"]), (3, pol["rotation"])):
        want = c["irrep_Ap_tf"][ir] / 3 ** 0.5
        if any(abs(a - want) > tol for a in c["component_Ap"][k:k + 3]):
            return ("COMPONENTS", f"{ir}: component amplitudes {c['component_Ap'][k:k + 3]} != A_p/sqrt3 {want:.5f}")
        if ir in irr and "Ap_tf" in irr[ir] and abs(irr[ir]["Ap_tf"] - c["irrep_Ap_tf"][ir]) > tol:
            return ("COMPONENTS", f"{ir}: translation-free A_p {c['irrep_Ap_tf'][ir]:.5f} != f1 {irr[ir]['Ap_tf']:.5f}")
    g = c.get("grid")
    if g is None:
        return None if not pol.get("grid_toolkit", True) else ("COMPONENTS", "grid toolkit requested but not compared")
    if not (g["closure_n_ops"] == 96 and g["closure_distinct"] == 96 and g["closure_signed_permutations"]
            and g["closure_residual"] <= tol):
        return ("COMPONENTS", f"closure: {g['closure_distinct']}/96 distinct, signed permutations "
                              f"{g['closure_signed_permutations']}, residual {g['closure_residual']:.2e}")
    if not g["matrices_equal_grid_toolkit"]:
        return ("BASIS_DISAGREE", "the 96 derived 6x6 matrices differ from the grid toolkit's mode_matrices()")
    if max(g["fold_residual_A"]) > tol:
        return ("BASIS_DISAGREE", f"folded components differ from the grid basis vectors by {max(g['fold_residual_A']):.2e} Å")
    if any(abs(x - 2.0) > 1e-9 for x in g["basis_norm_sq"]):
        return ("BASIS_DISAGREE", f"grid basis |B|^2 {g['basis_norm_sq']} != n_cells = 2")
    if any(abs(x - round(x)) > 1e-3 for x in g["child_node"]):
        return ("BASIS_DISAGREE", f"child is not on a grid node: {g['child_node']}")
    return None


# ---- G2: grid valid -------------------------------------------------------------------------
def _grid(s):
    return s.get("grid") or {}


def g2_c1_active_set_generates_H(s):
    sel = s.get("selection") or {}
    if sel.get("code") != "OK":
        return (sel.get("code", "SELECTION"), sel.get("detail", "mode selection failed"))
    if not sel.get("c1_generates_H"):
        return ("R3_FAIL", f"active set {sel.get('active')} generates #{sel.get('c1_intersection_sg')}, not H")
    return None


def g2_r5_decision_applied(s):
    """A recorded R5 answer must be the one the grid was built on: the grid's axes equal the selection's active set
    after the decision, removed irreps are held at zero, and anchor_only has its anchor frames."""
    sel, g = s.get("selection") or {}, _grid(s)
    dec = s.get("overrides", {}).get("f2", {}).get("r5_decision")
    if not dec and not sel.get("r5_decision"):
        return None
    if dec and not sel.get("borderline"):
        return None          # an R5 answer recorded where the selection has no borderline irreps is moot, not a fault
    if sel.get("r5_decision") != dec:
        return ("R5_NOT_APPLIED", f"decision {dec!r} recorded, selection carries {sel.get('r5_decision')!r}")
    if g.get("built") and list(g.get("active") or []) != list(sel.get("active") or []):
        return ("R5_NOT_APPLIED", f"grid axes {g.get('active')} differ from the selection {sel.get('active')}")
    if dec == "anchor_only":
        want = set(sel.get("r5_anchors") or [])
        have = {a["irrep"] for a in ((g.get("r5") or {}).get("anchors") or [])}
        if want != have:
            return ("R5_NOT_APPLIED", f"anchor frames for {sorted(want)} expected, grid has {sorted(have)}")
    return None


def g2_c2_atom_matching(s):
    am = _grid(s).get("certify", {}).get("atom_matching", {})
    if am.get("max_disp_A") is None:
        return ("ATOM_MATCH", "child could not be mapped onto the parent supercell")
    if am["max_disp_A"] >= am.get("limit_A", 2.0):
        return ("ATOM_MATCH", f"max child displacement {am['max_disp_A']:.3f} Å >= 2 Å")
    return None


def g2_c2_translation_free(s):
    for ir, t in _grid(s).get("certify", {}).get("translation", {}).items():
        if not t.get("removed") and t.get("f_T", 0) > 1e-6:
            return ("TRANSLATION", f"{ir}: rigid translation not removed (f_T = {t.get('f_T'):.3f})")
    vec = _grid(s).get("vectors", {})
    import numpy as _np
    for ir, v in vec.items():
        if _np.abs(_np.asarray(v).mean(axis=0)).max() > 1e-6:
            return ("TRANSLATION", f"{ir}: vector still has a mean displacement")
    return None


def g2_c2_calibration(s):
    """Each vector, scaled to its irrep's A_p, must reproduce the child's projection on it. The movie
    factors s_i = A_child / A_movie are recorded per irrep but need not agree between irreps (CsSnI3:
    1.25 for both; Ca3Ti2O7: X3- 1.25, X2+ 2.50 -- the ISODISTORT movie scales each irrep separately)."""
    cal = _grid(s).get("certify", {}).get("calibration", {})
    for ir, c in cal.items():
        if "child_projection_Ap" in c and abs(c["child_projection_Ap"] - c["Ap_child"]) > 0.02 * c["Ap_child"]:
            return ("CALIBRATION", f"{ir}: child projects to {c['child_projection_Ap']:.4f} Å, "
                                   f"vector calibrated to {c['Ap_child']:.4f} Å")
    return None


def g2_c2_single_mode_sg_strict(s):
    for ir, c in _grid(s).get("certify", {}).get("single_mode", {}).items():
        if c.get("sg_1e-2") != c.get("expected"):
            loose = c.get("expected") in (c.get("ladder") or {}).values()
            return ("SINGLE_MODE_SG", f"{ir}: SG #{c.get('sg_1e-2')} at 1e-2, expected #{c.get('expected')}"
                                      + (" (matches only at another tolerance)" if loose else ""))
    return None


def g2_c3_budget_and_tree_coverage(s):
    g = _grid(s)
    if not g.get("built"):
        sz = g.get("sizing") or {}
        why = (f"N = m^n = {sz.get('m')}^{sz.get('n')} = {sz.get('N')} (+{len(s['config']['policy'].get('anchors') or [])} anchors) "
               f"> budget {sz.get('budget')} at dq = {sz.get('dq')} Å; D3 reduction not implemented") if sz else ""
        return (g.get("reason", "GRID"), "grid not built" + (": " + why if why else ""))
    sz = g["sizing"]
    if g["n_frames"] > sz["budget"]:
        return ("OVER_BUDGET", f"{g['n_frames']} frames > budget {sz['budget']}")
    on_grid = {f["sg"] for f in g["frames"]}
    missing = [sg for sg in set(sz["descent_tree"].values()) if sg not in on_grid]
    if missing:
        return ("TREE_COVERAGE", f"descent-tree subgroups missing from the grid: {missing}")
    return None


def g2_audit_every_frame_sg_and_dmin(s):
    g = _grid(s)
    d_cut = s["config"]["policy"]["d_cut"]
    for f in g.get("frames", []):
        if f["sg"] != f["expected_sg"]:
            return ("FRAME_SG", f"frame {f['id']} Q={f['Q']}: SG #{f['sg']}, descent tree says #{f['expected_sg']}")
        if f["d_min"] < d_cut:
            return ("D_MIN", f"frame {f['id']}: d_min {f['d_min']} Å < {d_cut} Å")
    return None


# ---- G2 for the six-component grid (policy.grid.six; nodes/f2_grid6.py) ---------------------------
def _g6(s):
    return _grid(s) if _grid(s).get("kind") == "six_component" else None


def g2s_active_set(s):
    sel = s.get("selection") or {}
    want = {s["config"]["policy"]["components"]["polar"], s["config"]["policy"]["components"]["rotation"]}
    if sel.get("code") != "OK":
        return (sel.get("code", "SELECTION"), sel.get("detail", "mode selection failed"))
    if set(sel.get("active") or []) != want:
        return ("R3_FAIL", f"active set {sel.get('active')} != components {sorted(want)}")
    return None


def g2s_orbits_burnside(s):
    g = _g6(s)
    if not g:
        return ("GRID", "six-component grid not built")
    for d in g["datasets"]:
        if abs(d["burnside"] - d["n_orbits"]) > 1e-9 or d["sum_mult"] != d["n_nodes"] or not d["mult_divides_96"] \
                or not d["unfold_ok"]:
            return ("ORBITS", f"{d['name']}: {d['n_orbits']} orbits vs Burnside {d['burnside']}, sum of multiplicities "
                              f"{d['sum_mult']} vs {d['n_nodes']} nodes, divides 96 {d['mult_divides_96']}, unfold {d['unfold_ok']}")
        want = (s["config"]["policy"]["grid"]["six"].get("expected") or {}).get(d["name"])
        if want and [d["n_orbits"], d["n_orbits_included"]] != list(want):
            return ("ORBITS", f"{d['name']}: {d['n_orbits']} -> {d['n_orbits_included']} orbits, expected {want[0]} -> {want[1]}")
    return None


def g2s_orbits_equal_stored(s):
    g = _g6(s)
    for d in g["datasets"]:
        st = d.get("stored") or {}
        if not st:
            return ("STORED_MISSING", f"{d['name']}: stored orbits.npz not found")
        bad = [k for k in ("nodes_equal", "reps_equal", "mult_equal", "node_orbit_equal", "mats_equal", "steps_equal") if not st.get(k)]
        if bad:
            return ("ORBITS_DISAGREE", f"{d['name']}: differs from the stored orbits.npz in {bad}")
        man = st["manifest"]
        mine = {"n_nodes": d["n_nodes"], "n_orbits": d["n_orbits"], "n_orbits_included": d["n_orbits_included"],
                "n_nodes_included": d["n_nodes_included"]}
        if any(man.get(k) != v for k, v in mine.items()):
            return ("ORBITS_DISAGREE", f"{d['name']}: {mine} vs stored manifest {man}")
    return None


def g2s_contact_cut_equal_stored(s):
    g = _g6(s)
    for d in g["datasets"]:
        st = d["stored"]
        if not st.get("included_equal"):
            return ("CONTACT_CUT", f"{d['name']}: included orbits differ from the stored set (closest orbit to the cut "
                                   f"{d['closest_to_cut_A']:.2e} Å, max dmin difference {st.get('dmin_max_diff_A'):.2e} Å)")
        if st["dmin_max_diff_A"] > 1e-3:
            return ("CONTACT_CUT", f"{d['name']}: contact distances differ from the stored ones by {st['dmin_max_diff_A']:.2e} Å")
    if (g.get("extra") or {}).get("below_cut"):
        return ("CONTACT_CUT", f"{g['extra']['below_cut']} extra points below the contact cut")
    return None


def g2s_planned_equal_stored(s):
    g = _g6(s)
    for name, a in g["audit"].items():
        if a["n_missing_in_store"] or a["n_unplanned_in_store"] or a["n_field_mismatch"]:
            return ("PLAN_DISAGREE", f"{name}: {a['n_missing_in_store']} planned not stored {a['missing_in_store']}, "
                                     f"{a['n_unplanned_in_store']} stored not planned {a['unplanned_in_store']}, "
                                     f"{a['n_field_mismatch']} with other index/orbit/multiplicity/contact {a['field_mismatch']}")
        c = a.get("controls")
        if c and (c["n"] != c["expected"] or c["n_invalid"]):
            return ("CONTROLS", f"{name}: {c['n']} stored controls (expected {c['expected']}), {c['n_invalid']} not a "
                                f"non-representative image of an included orbit {c['invalid']}")
    p = g.get("planes") or {}
    if p and (p.get("n") != p.get("stored_n_points") or p.get("skipped") != p.get("stored_n_skipped")
              or p.get("n_missing_in_store") or p.get("n_unplanned_in_store") or p.get("n_q_mismatch")):
        return ("PLAN_DISAGREE", f"refine planes: {p}")
    e = g.get("extra") or {}
    if e and e.get("n") != e.get("stored_n_runs"):
        return ("PLAN_DISAGREE", f"extra points: {e.get('n')} read vs manifest {e.get('stored_n_runs')}")
    return None


def g2s_space_groups(s):
    g = _g6(s)
    if g["n_sg_mismatch"]:
        return ("SG_DISAGREE", f"{g['n_sg_mismatch']} frames: IRIS space group != stored point_info {g['sg_mismatch'][:5]}")
    bad = {k: v for k, v in g["special_nodes"].items() if v["sg"] != v["expected"]}
    if bad:
        return ("SINGLE_MODE_SG", f"special nodes: {bad}")
    return None


def g2s_budget(s):
    g = _g6(s)
    if g["n_frames"] > g["budget"]:
        return ("OVER_BUDGET", f"{g['n_frames']} frames > budget {g['budget']}")
    return None


# ---- G2 for a straight-line path (policy.path; nodes/f2_path.py) ------------------------------------
def _gp(s):
    g = _grid(s)
    return g if g.get("kind") == "path" else None


def g2p_child_metric(s):
    g = _gp(s)
    if not g:
        return ("GRID", "path not built")
    if g["lattice"]["metric_dev_A2"] > 1e-6:
        return ("PATH_LATTICE", f"lambda = 1 cell differs from the child metric by {g['lattice']['metric_dev_A2']:.2e} Å²")
    lim = s["config"]["policy"]["path"].get("max_rigid_rotation_deg")
    if lim is not None and g["lattice"]["rigid_rotation_deg"] > lim:
        return ("PATH_LATTICE", f"the child cell carries a rigid rotation of {g['lattice']['rigid_rotation_deg']:.3f} deg "
                                f"relative to the parent (> {lim}); the interpolated cells are not a pure strain path")
    return None


def g2p_end_is_child(s):
    g = _gp(s)
    rms = g.get("child_match_rms")
    tol = float(s["config"]["policy"]["path"].get("child_rms_tol", 1e-3))
    if rms is None or rms[0] > tol:
        return ("PATH_END", f"lambda = 1 frame does not match the child CIF (StructureMatcher rms {rms})")
    return None


def g2p_space_groups(s):
    g = _gp(s)
    bad = [(f["name"], f["sg"], f["expected_sg"]) for f in g["frames"] if f["sg"] != f["expected_sg"]]
    if bad:
        return ("FRAME_SG", f"frames off the expected space group: {bad}")
    d_cut = s["config"]["policy"]["d_cut"]
    low = [(f["name"], f["d_min"]) for f in g["frames"] if f["d_min"] < d_cut]
    if low:
        return ("D_MIN", f"contacts below {d_cut} Å: {low}")
    return None


def g2p_equals_stored(s):
    g = _gp(s)
    st = g.get("stored") or {}
    if not st:
        return None
    if st["n_points"] != g["n_frames"] or st["lambda_max_dev"] > 1e-4 or st["Ap_max_dev_A"] > 2e-4 \
            or set(st["irreps"]) != set(g["active"]) or st["lattice_max_dev_A"] > 1e-4 \
            or st.get("sg_stored", [f["sg"] for f in g["frames"]]) != [f["sg"] for f in g["frames"]]:
        return ("PLAN_DISAGREE", f"path differs from the stored path.json: {st}")
    return None


# ---- G2 / G5 for a two-component plane (grid kind plane2) ----------------------------------
def _g2p2(s):
    g = _grid(s)
    return g if g.get("kind") == "plane2" else None


def g2q_components(s):
    g = _g2p2(s)
    if not g:
        return ("GRID", "plane not built")
    c = g["components"]
    if abs(c["norm_2_A"] / c["norm_1_A"] - 1) > 1e-9:
        return ("COMPONENTS", f"|e_2| != |e_1| ({c['norm_2_A']:.6f} vs {c['norm_1_A']:.6f} Å)")
    if abs(c["overlap"]) > 1e-6:
        return ("COMPONENTS", f"the two components are not orthogonal (overlap {c['overlap']:.3e})")
    return None


def g2q_orbits(s):
    g = _g2p2(s)
    o = g["orbits"]
    if not (o["n"] == o["burnside"] == g["n_frames"]):
        return ("ORBITS", f"{o['n']} orbit representatives, Burnside {o['burnside']}, {g['n_frames']} frames")
    if o["multiplicity_sum"] != g["n_grid_points"]:
        return ("ORBITS", f"orbit multiplicities sum to {o['multiplicity_sum']} != {g['n_grid_points']} grid points")
    if g["n_frames"] > s["config"]["run"]["budget_runs"]:
        return ("BUDGET", f"{g['n_frames']} frames > budget {s['config']['run']['budget_runs']}")
    return None


def g2q_space_groups(s):
    g = _g2p2(s)
    bad = [(f["name"], f["sg"], f["expected_sg"]) for f in g["frames"] if f.get("expected_sg") and f["sg"] != f["expected_sg"]]
    if bad:
        return ("FRAME_SG", f"origin/axis frames off the expected space group: {bad}")
    d_cut = s["config"]["policy"]["d_cut"]
    low = [(f["name"], f["d_min"]) for f in g["frames"] if f["d_min"] < d_cut]
    if low:
        return ("D_MIN", f"contacts below {d_cut} Å: {low}")
    return None


def _mq(s):
    m = s.get("model") or {}
    return m if m.get("kind") == "plane2" else None


def g5q_coverage(s):
    m = _mq(s)
    if not m:
        return ("NOT_FITTED", "no plane fit")
    if m["n_points"] != _grid(s).get("n_frames"):
        return ("THIN_GRID", f"{m['n_points']} of {_grid(s).get('n_frames')} orbit representatives have energies")
    if m["n_full_points"] != _grid(s).get("n_grid_points"):
        return ("THIN_GRID", f"symmetry images cover {m['n_full_points']} of {_grid(s).get('n_grid_points')} grid points")
    return None


def g5q_fit(s):
    m = _mq(s)
    if m["rms_meV"] > m["max_rms_meV"]:
        return ("FIT_RMS", f"Landau fit rms {m['rms_meV']:.3f} meV/f.u. > {m['max_rms_meV']}")
    if m["max_abs_res_meV"] > m["max_abs_res_meV_allowed"]:
        return ("FIT_RESIDUAL", f"largest residual {m['max_abs_res_meV']:.3f} meV/f.u. > {m['max_abs_res_meV_allowed']}")
    return None


def g5q_minimum_inside(s):
    m = _mq(s)
    mn = m["minimum"]
    if mn["on_border"]:
        return ("MIN_ON_BORDER", f"fitted minimum at the grid border (Q1 {mn['Q1']:.3f}, Q2 {mn['Q2']:.3f} Å of {m['q_max_A']:.3f}); widen q_max")
    if mn["where"] == "origin" and m["E_axis_min_meV"] < -1.0:
        return ("MIN_INCONSISTENT", "the fit puts the minimum at the origin but a computed axis point is lower")
    return None


# ---- G3: jobs finished ----------------------------------------------------------------------
def g3_none_queued_or_running(s):
    j = s.get("jobs") or {}
    if j.get("queued") or j.get("running"):
        return ("JOBS_PENDING", f"{j.get('queued')} queued, {j.get('running')} running")
    if j.get("cancelled"):
        return ("JOBS_CANCELLED", f"{j['cancelled']} parts were cancelled")
    if j.get("unmatched"):
        u = j["unmatched"]
        return ("UNMATCHED", f"{len(u)} frames have no stored computed structure (first: {u[0]})")
    if j.get("n_matched") != j.get("n_frames"):
        return ("UNMATCHED", f"{j.get('n_matched')} of {j.get('n_frames')} frames matched")
    lim = (s.get("config", {}).get("run", {}).get("replay") or {}).get("max_rigid_shift_A", 0.05)
    if j.get("modulo_translation") and j.get("max_rigid_shift_A", 0) > lim:
        return ("RIGID_SHIFT", f"frames matched only after a rigid shift of up to {j['max_rigid_shift_A']:.4f} Å > {lim} Å")
    return None


# ---- G4 and G5 (every grid kind): frames dropped from the grid need the human's authorisation ----------------
def g4_missing_frames_authorized(s, after_fit=False):
    """A fit on fewer frames than the plan is a different result (replay showed 7 of 22 wrong results came from exactly
    this: `flag_and_continue` after a job failure, caught only by the replay-only comparison with the stored campaign).
    In production the dropped frames are known, so the check is local: accepted flags require
    policy.fit.allow_missing_frames, which only a recorded human decision sets; the default route is to resubmit."""
    e, g = s.get("energies") or {}, s.get("grid") or {}
    have = e.get("eV_per_cell") or {}
    # dropped = accepted AND no energy in the fit (an SCF-limited frame whose energy is kept under policy qc.scf_limited
    # and only its gradients dropped, as in the BiFeO3 campaign, is not a missing frame)
    # at G4 only accepted flags count (an un-accepted failed frame already fails G4 with its job code); at G5, after the
    # fit, every planned frame without an energy counts, however it got there (G4 ablated, or a frame lost silently)
    dropped = [f for f in e.get("flagged", []) if (after_fit or f.get("accepted")) and not f.get("energy_kept")
               and str(f.get("id")) not in have]
    if not dropped:
        return None
    if s["config"]["policy"].get("fit", {}).get("allow_missing_frames"):
        return None
    n = g.get("n_frames") or (e.get("n", 0) + len(e.get("flagged", [])))
    return ("MISSING_FRAMES", f"{len(dropped)} of {n} frames dropped from the grid (first {dropped[0]['id']}: "
                              f"{dropped[0].get('reason', '')}); a fit on fewer frames than planned needs "
                              f"policy.fit.allow_missing_frames (a recorded human decision) — resubmit the parts instead")


def g5_missing_frames(s):
    """G5 form of the same check: a fit on fewer frames than planned, whatever removed them."""
    return g4_missing_frames_authorized(s, after_fit=True)



# ---- G4: energies converged or flagged ------------------------------------------------------
def g4_converged_or_flagged(s):
    e = s.get("energies") or {}
    g = _grid(s)
    if e.get("n", 0) + len(e.get("flagged", [])) != g.get("n_frames"):
        return ("ACCOUNTING", "every frame must be either converged or flagged")
    failed = [f for f in e.get("flagged", []) if f.get("code") and not f.get("accepted")]
    if failed:
        codes = sorted({f["code"] for f in failed})
        return (codes[0], f"{len(failed)} frames from failed jobs ({', '.join(codes)}), first: frame {failed[0]['id']}")
    if e.get("E0_eV") is None:
        return ("NO_ORIGIN", "the parent (Q = 0) frame has no energy")
    rng = e.get("range_meV_per_fu")
    if rng is None or not e["sanity"]["min_range_meV"] <= rng <= e["sanity"]["max_range_meV"]:
        return ("ENERGY_RANGE", f"energy range {rng} meV/f.u. outside sanity bounds")
    if len(e.get("stored_input_sets", {})) > 1:
        # D4 scans may carry their own settings (policy.d4.settings: own_per_scan): each scan is used only through
        # energy differences inside itself, so it must be consistent within itself and the main grid within itself
        d4 = s["config"]["policy"].get("d4") or {}
        grp = e.get("stored_input_sets_by_group") or {}
        if d4.get("settings") == "own_per_scan" and grp and all(len(v) == 1 for v in grp.values()):
            return None
        return ("DFT_INCONSISTENT", f"stored frames use different INCAR/KPOINTS: {e['stored_input_sets']}"
                                    + (f"; by group {grp}" if grp else ""))
    return None


# ---- G4 for the six-component grid (nodes/f4_grid6.py) ----------------------------------------
def _e6(s):
    return s.get("energies") or {}


def _qc(s):
    return s["config"]["policy"].get("qc") or {}


def g4s_accounting(s):
    e, g = _e6(s), _grid(s)
    with_E = {fr["id"] for i, fr in enumerate(g["frames"]) if str(i) in e.get("eV_per_cell", {})}
    flagged = {f["id"] for f in e.get("flagged", [])}
    missing = [fr["id"] for fr in g["frames"] if fr["id"] not in with_E and fr["id"] not in flagged]
    if missing:
        return ("ACCOUNTING", f"{len(missing)} frames neither have an energy nor are flagged (first {missing[0]})")
    failed = [f for f in e["flagged"] if f.get("code") and not f.get("accepted")]
    if failed:
        return (failed[0]["code"], f"{len(failed)} flagged frames not accepted, first {failed[0]['id']}: {failed[0]['reason']}")
    lost = [f for f in e["flagged"] if not f.get("code")]
    if lost:
        return ("NO_ENERGY", f"{len(lost)} frames without an energy, first {lost[0]['id']}: {lost[0]['reason']}")
    lim = _qc(s).get("max_scf_limited")
    if lim is not None and e.get("n_scf_limited", 0) > lim:
        return ("SCF_LIMITED", f"{e['n_scf_limited']} SCF-limited runs > {lim}")
    return None


def g4s_rows_rederived(s):
    e = _e6(s)
    if e.get("n_missing_rows"):
        return ("NO_ENERGY", f"{e['n_missing_rows']} frames have no row in the collected CSV {e['missing_rows']}")
    if set(e.get("origins", {})) != {fr["dataset"] for fr in _grid(s)["frames"]}:
        return ("NO_ORIGIN", f"datasets without a q = 0 run: origins {e.get('origins')}")
    if e["E_csv_max_dev_meV"] > 1e-3:
        return ("ENERGY_MISMATCH", f"E_meV_per_fu re-derived from E0_cell differs from the CSV by {e['E_csv_max_dev_meV']:.2e} meV/f.u.")
    if any(v > 1e-3 for v in e["origin_copies_spread_meV"].values()):
        return ("ENERGY_MISMATCH", f"q = 0 copies disagree: {e['origin_copies_spread_meV']}")
    if e["label_max_dev_A"] > 1e-6:
        return ("LABEL_MISMATCH", f"CSV q differs from the planned label by {e['label_max_dev_A']:.2e} Å")
    if e["n_sg_mismatch"]:
        return ("SG_DISAGREE", f"{e['n_sg_mismatch']} CSV space groups != IRIS {e['sg_mismatch'][:3]}")
    rng = e.get("range_meV_per_fu")
    if rng is None or not e["sanity"]["min_range_meV"] <= rng <= e["sanity"]["max_range_meV"]:
        return ("ENERGY_RANGE", f"energy range {rng} meV/f.u. outside sanity bounds")
    return None


def g4s_controls_symmetric(s):
    c, q = _e6(s)["controls"], _qc(s)
    want = q.get("controls_expected")
    if want is not None and c["n"] != want:
        return ("CONTROLS", f"{c['n']} controls compared, expected {want}")
    if c["max_dE_meV"] > q.get("control_dE_meV", 0.01):
        return ("CONTROLS", f"control energy differs from its orbit by {c['max_dE_meV']:.4f} meV/f.u. ({c['worst']})")
    if c["max_dgrad"] > q.get("control_dgrad_meV_per_A", 0.5):
        return ("CONTROLS", f"control gradient != G x orbit gradient by {c['max_dgrad']:.3f} meV/Å/f.u.")
    r = _e6(s)["refine_on_main"]
    if q.get("refine_on_main_expected") is not None and r["n"] != q["refine_on_main_expected"]:
        return ("CONTROLS", f"{r['n']} refine points on main nodes, expected {q['refine_on_main_expected']}")
    if r["max_dE_meV"] > q.get("control_dE_meV", 0.01):
        return ("CONTROLS", f"refine point differs from the main node by {r['max_dE_meV']:.4f} meV/f.u.")
    return None


def g4s_gradients_consistent(s):
    t, q = _e6(s)["line_integral"], _qc(s)
    if not t["n_pairs"]:
        return ("GRADIENTS", "no grid-line pairs to check the gradients")
    if abs(t["slope"] - 1) > q.get("line_slope_tol", 0.02):
        return ("GRADIENTS", f"E(c) - E(a) vs Simpson of the gradients on grid lines: slope {t['slope']:.4f} (sign or units wrong)")
    return None


def g4s_magnetism(s):
    m, q = _e6(s)["magnetism"], _qc(s)
    lo, hi = q.get("mFe_range", [3.5, 4.5])
    # the two Fe sites are not symmetry-related in a low-symmetry frame, so |m1| != |m2| is allowed (recorded);
    # G-AFM means opposite site moments and a vanishing total moment
    if m["min_abs_mFe"] < lo or m["max_abs_mFe"] > hi or m["n_same_sign"] or m["max_abs_Mtot"] > q.get("max_abs_Mtot", 0.05):
        return ("MAGNETISM", f"G-AFM not kept everywhere: {m}")
    return None


def g4s_dft_consistent(s):
    sets = _e6(s).get("stored_input_sets", {})
    if len(sets) > 1:
        return ("DFT_INCONSISTENT", f"stored frames use different INCAR/KPOINTS: {sets}")
    return None


# ---- G5: fit acceptable ---------------------------------------------------------------------
def _model(s):
    return s.get("model") or {}


def g5_d4_secondaries_hold(s):
    """D4 (policy.d4 only): every secondary held at zero must be hard (positive curvature) and the energy it would
    release at any scanned base point must stay below max_fraction x the smallest interpreted energy difference
    (policy.d4.compare_to). Otherwise SECONDARY_COUPLED -> human (keep it at zero with the caveat, or stop)."""
    d4 = (_model(s) or {}).get("d4")
    if not s["config"]["policy"].get("d4"):
        return None
    if not d4:
        return ("D4_MISSING", "policy.d4 set but f5 recorded no D4 scans")
    soft = [x["name"] for x in d4["scans"] if x["class"] == "soft"]
    if soft:
        return ("SECONDARY_SOFT", f"secondary soft (negative curvature) in scans {soft}")
    edge = [x["name"] for x in d4["scans"] if x["edge_minimum"]]
    if edge:
        return ("SECONDARY_SCAN_EDGE", f"scan minimum at the edge of the scanned range in {edge}")
    lim = d4["max_fraction"] * d4["reference_meV"] if d4["reference_meV"] is not None else None
    if lim is not None and d4["largest_gain_meV"] > lim and not d4.get("accepted"):
        return ("SECONDARY_COUPLED", f"{d4['largest_gain_scan']}: relaxing the secondary releases {d4['largest_gain_meV']:.2f} meV/f.u. "
                                     f"> {d4['max_fraction']} x {d4['compare_to']} ({d4['reference_meV']:.3f} meV/f.u.)")
    return None


def g5_cv_error_ok(s):
    m, lim = _model(s), s["config"]["policy"]["fit"]
    if not m.get("fitted"):
        return ("NO_FIT", m.get("reason", "no fit"))
    if m["cv"]["rms_meV"] > lim["max_cv_rms_meV"]:
        return ("CV_ERROR", f"{m['cv']['folds']}-fold CV RMS {m['cv']['rms_meV']:.3f} > {lim['max_cv_rms_meV']} meV/f.u.")
    return None


def g5_residuals_ok(s):
    m, lim = _model(s), s["config"]["policy"]["fit"]
    if not m.get("fitted"):
        return ("NO_FIT", m.get("reason", "no fit"))
    if m["rms_meV"] > lim["max_rms_meV"] or m["max_abs_res_meV"] > lim["max_abs_res_meV"]:
        return ("RESIDUALS", f"RMS {m['rms_meV']:.3f} / max {m['max_abs_res_meV']:.2f} meV/f.u. above "
                             f"{lim['max_rms_meV']} / {lim['max_abs_res_meV']}")
    return None


def g5_coverage_ok(s):
    m, lim = _model(s), s["config"]["policy"]["fit"]
    if not m.get("fitted"):
        return ("NO_FIT", m.get("reason", "no fit"))
    if m["n_fit"] < lim["min_points_per_coef"] * 8:
        return ("THIN_GRID", f"{m['n_fit']} nodes for 8 coefficients (< {lim['min_points_per_coef']} per coefficient)")
    if m["ring"]["radius_max_A"] > m["rmax_A"] - 2 * m["grid_dq_A"]:
        return ("COVERAGE", f"ring of minima reaches {m['ring']['radius_max_A']} Å, within 2 grid steps of the "
                            f"fit edge {m['rmax_A']} Å")
    return None


# G5 for policy.analysis = surface (no fit: the DFT surface itself is the result)
def _surf(s):
    m = _model(s)
    if not m.get("fitted") or m.get("kind") != "surface":
        return None, ("NO_SURFACE", m.get("reason", "no surface analysis"))
    return m, None


def g5s_coverage_complete(s):
    m, err = _surf(s)
    if err:
        return err
    if m["n_nodes"] != m["n_nodes_expected"]:
        return ("THIN_GRID", f"{m['n_nodes']} of {m['n_nodes_expected']} plane nodes have an energy")
    if any(p["E_meV"] is None for p in m["phases"].values()):
        return ("COVERAGE", "a phase point (anchor) has no energy: " +
                ", ".join(n for n, p in m["phases"].items() if p["E_meV"] is None))
    return None


def g5s_minimum_inside_grid(s):
    m, err = _surf(s)
    if err:
        return err
    need = s["config"]["policy"].get("surface", {}).get("edge_margin_steps", 2)
    if m["minimum_edge_distance_steps"] < need:
        return ("COVERAGE", f"grid minimum {m['minima'][0]['Ap']} Å lies {m['minimum_edge_distance_steps']:.1f} "
                            f"steps from the grid edge (< {need}): the surface may continue downhill outside")
    return None


def g5s_mirror_symmetry(s):
    m, err = _surf(s)
    if err:
        return err
    tol = s["config"]["policy"].get("surface", {}).get("mirror_tol_meV", 1.0)
    worst = max(m["mirror_meV"].values())
    if worst > tol:
        return ("MIRROR", f"E(x,y) vs E(-x,y)/E(x,-y) differ by {worst:.3f} meV/f.u. > {tol} (parent symmetry)")
    return None


def g5s_script_agrees(s):
    m, err = _surf(s)
    if err:
        return err
    sc = m["script"]
    if not sc.get("ok"):
        return ("SCRIPT_FAILED", sc.get("stderr", "surface script failed")[-300:])
    ph = m["phases"]
    pairs = [("mirror x", sc["mirror_x_meV"], m["mirror_meV"]["x"], 1e-3),
             ("mirror y", sc["mirror_y_meV"], m["mirror_meV"]["y"], 1e-3),
             ("parent", sc["parent_meV"], ph["parent"]["E_meV"], 0.01)]
    pairs += [(n, sc[f"{n}_meV"], ph[n]["E_meV"], 0.01) for n in ("cmcm", "cmce", "a21am") if n in ph]
    bad = [f"{n}: script {a} vs node {b:.3f}" for n, a, b, t in pairs if abs(a - b) > t]
    return ("SCRIPT_MISMATCH", "; ".join(bad)) if bad else None


# G5 for policy.analysis = meier_QP (energies per cell; limits from policy.fit)
def _meier(s):
    m = _model(s)
    if not m.get("fitted") or m.get("kind") not in ("meier_QP", "meier_joint"):
        return None, ("NO_FIT", m.get("reason", "no (Q, P) fit"))
    return m, None


def g5m_cv_error_ok(s):
    m, err = _meier(s)
    if err:
        return err
    lim = s["config"]["policy"]["fit"]["max_cv_rms_meV"]
    if m["cv"]["rms_meV"] > lim:
        return ("CV_ERROR", f"{m['cv']['folds']}-fold CV RMS {m['cv']['rms_meV']:.2f} > {lim} meV/cell")
    return None


def g5m_residuals_ok(s):
    m, err = _meier(s)
    if err:
        return err
    f = s["config"]["policy"]["fit"]
    if m["rms_meV"] > f["max_rms_meV"] or m["max_abs_res_meV"] > f["max_abs_res_meV"]:
        return ("RESIDUALS", f"RMS {m['rms_meV']:.2f} / max {m['max_abs_res_meV']:.2f} meV/cell above "
                             f"{f['max_rms_meV']} / {f['max_abs_res_meV']}")
    return None


def g5m_coverage_ok(s):
    m, err = _meier(s)
    if err:
        return err
    f = s["config"]["policy"]["fit"]
    ncoef = sum(1 for k, v in m.get("coefficients_As", {}).items()) - (1 if str(m.get("aP", "")).startswith("fixed") else 0)
    ncoef = ncoef or 6
    if m["n_fit"] < f["min_points_per_coef"] * ncoef:
        return ("THIN_GRID", f"{m['n_fit']} nodes for {ncoef} coefficients (< {f['min_points_per_coef']} per coefficient)")
    need = f.get("edge_margin_steps", 2)
    edge = m["window"]["qmax_A"] - need * m["grid_dq_A"]
    worst = max(m["Q_star_A"], m["coupled"]["Q_A"])
    if worst > edge + 1e-9:
        return ("COVERAGE", f"K3 minimum at Q = {worst:.3f} Å lies within {need} grid steps of the fit edge "
                            f"{m['window']['qmax_A']} Å")
    return None


# ---- G5 for the six-component invariant fit (nodes/f5_landau6d.py) ----------------------------
def _m6(s):
    m = s.get("model") or {}
    return m if m.get("kind") == "landau6d" else None


def g5l_invariants_complete(s):
    m = _m6(s)
    if not m or not m.get("fitted"):
        return ("NOT_FITTED", (m or {}).get("reason", "no landau6d model"))
    want = round(m["molien_total_2_to_deg"])
    if abs(m["molien_total_2_to_deg"] - want) > 1e-6 or m["n_invariants"] != want:
        return ("BASIS_INCOMPLETE", f"{m['n_invariants']} invariants built, Molien's formula gives {m['molien_total_2_to_deg']:.4f}")
    odd = [d for d, x in enumerate(m["molien_per_degree"]) if d % 2 and abs(x) > 1e-9]
    if odd:
        return ("BASIS_INCOMPLETE", f"odd-degree invariants exist (degrees {odd}) but only even degrees are built")
    return None


def g5l_cv_error_ok(s):
    m, fit = _m6(s), s["config"]["policy"]["fit"]
    if m["cv"]["rms_meV"] > fit["max_cv_rms_meV"]:
        return ("CV_ERROR", f"10-fold CV RMS {m['cv']['rms_meV']:.2f} > {fit['max_cv_rms_meV']} meV/f.u.")
    ho = m["tests"]["final scheme: hold-out"]
    if ho["rms_meV"] > fit["max_cv_rms_meV"]:
        return ("CV_ERROR", f"20 % hold-out RMS {ho['rms_meV']:.2f} > {fit['max_cv_rms_meV']} meV/f.u.")
    return None


def g5l_residuals_ok(s):
    m, fit = _m6(s), s["config"]["policy"]["fit"]
    if m["rms_meV"] > fit["max_rms_meV"] or m["max_abs_res_meV"] > fit["max_abs_res_meV"]:
        return ("RESIDUALS", f"training RMS {m['rms_meV']:.2f} (limit {fit['max_rms_meV']}), max {m['max_abs_res_meV']:.2f} "
                             f"(limit {fit['max_abs_res_meV']}) meV/f.u.")
    return None


def g5l_coverage_ok(s):
    m, fit = _m6(s), s["config"]["policy"]["fit"]
    if m["points_per_coef"] < fit["min_points_per_coef"]:
        return ("THIN_GRID", f"{m['n_fit']} energies for {m['n_invariants']} coefficients ({m['points_per_coef']:.1f} per coefficient)")
    return None


def g5l_child_is_ground_state(s):
    m = _m6(s)
    st, gl = m["stationary"], m["global_search"]
    low = min(st, key=lambda k: st[k]["E_meV"])
    child = s["config"]["policy"]["fit"]["six"].get("child_phase", "R3c")
    if low != child or st[child]["index"] != 0:
        return ("WRONG_GROUND_STATE", f"lowest stationary point {low} (index {st[low]['index']}), expected {child} (index 0)")
    if abs(gl["lowest_meV"] - st[child]["E_meV"]) > 0.5:
        return ("WRONG_GROUND_STATE", f"global search finds {gl['lowest_meV']} meV/f.u., below {child} {st[child]['E_meV']:.1f}")
    return None


# ---- G4 / G5 for a straight-line path (nodes/f4_path.py, nodes/f5_path.py) ----------------------
def g4p_accounting(s):
    e, g = s.get("energies") or {}, _grid(s)
    if e.get("n", 0) + len(e.get("flagged", [])) != g.get("n_frames"):
        return ("ACCOUNTING", "every path point must be either converged or flagged")
    bad = [f for f in e.get("flagged", []) if not f.get("accepted")]
    if bad:
        return (bad[0].get("code") or "NO_ENERGY", f"{len(bad)} points flagged, first {bad[0]['id']}: {bad[0]['reason']}")
    if e.get("E0_eV") is None:
        return ("NO_ORIGIN", "the lambda = 0 point has no energy")
    rng = e.get("range_meV_per_fu")
    if rng is None or not e["sanity"]["min_range_meV"] <= rng <= e["sanity"]["max_range_meV"]:
        return ("ENERGY_RANGE", f"energy range {rng} meV/f.u. outside sanity bounds")
    return None


def g4p_rederived(s):
    e = s.get("energies") or {}
    if e.get("per_fu") != e.get("per_fu_from_composition"):
        return ("PER_FU", f"policy.fit.per_fu {e.get('per_fu')} != {e.get('per_fu_from_composition')} f.u. per cell")
    d = e.get("rederive_dev") or {}
    if e.get("csv_rows") != _grid(s).get("n_frames"):
        return ("NO_ENERGY", f"{e.get('csv_rows')} rows for this path in {e.get('csv')}")
    worst = max(d.values()) if d else None
    if worst is None or worst > 6e-4:            # stored values carry 3 decimals in meV
        return ("ENERGY_MISMATCH", f"E / dE re-derived from E0 of the cell differ from result.json / energies.csv: {d}")
    if e.get("sg_mismatch"):
        return ("FRAME_SG", f"stored space group differs from the frame's: {e['sg_mismatch']}")
    return None


def g4p_magnetism(s):
    e = s.get("energies") or {}
    if e.get("max_abs_mag_muB") is None or e["max_abs_mag_muB"] > e["mag_max_muB"]:
        return ("MAGNETIC", f"|m| up to {e.get('max_abs_mag_muB')} μB per cell > {e.get('mag_max_muB')} (non-magnetic expected)")
    return None


def g4p_dft_consistent(s):
    e = s.get("energies") or {}
    sets = e.get("stored_input_sets") or {}
    if len(sets) != 1:
        return ("DFT_INCONSISTENT", f"path points use different INCAR/KPOINTS: {sets}")
    if e.get("incar_template_hash") and not next(iter(sets)).startswith(f"INCAR {e['incar_template_hash']} "):
        return ("DFT_INCONSISTENT", f"INCAR differs from the campaign template {e['incar_template']}")
    if len(e.get("potcar_sets", [])) != 1 or "NOT SET" in e["potcar_sets"][0]:
        return ("DFT_INCONSISTENT", f"POTCAR sets along the path: {e.get('potcar_sets')}")
    return None


def _mp(s):
    m = s.get("model") or {}
    return m if m.get("kind") == "path" else None


def g5p_profile_complete(s):
    m = _mp(s)
    if not m:
        return ("NOT_FITTED", "no path profile")
    if m["n_points"] != _grid(s).get("n_frames") or any(x is None for x in m["dE_meV"]):
        return ("THIN_GRID", f"{m['n_points']} of {_grid(s).get('n_frames')} points in the profile")
    return None


def g5p_cross_setting(s):
    net = (_mp(s) or {}).get("network")
    if not net:
        return None
    bad = [c for c in net["cross_setting"] if abs(c["diff_meV"]) > net["cross_setting_tol_meV"]]
    if bad:
        return ("CROSS_SETTING", f"the same structure differs between settings by more than {net['cross_setting_tol_meV']} "
                                 f"meV/f.u.: {[(c['own'], c['other'], round(c['diff_meV'], 4)) for c in bad]}")
    return None


def g5p_closure(s):
    net = (_mp(s) or {}).get("network")
    if not net:
        return None
    for c in net["closure"]:
        if not c["connected"]:
            return ("CLOSURE", f"chain {c['chain']} does not connect this path's ends by structure: {c['links']}")
        if abs(c["gap_meV"]) > net["closure_tol_meV"]:
            return ("CLOSURE", f"dE_end {c['own_meV']:.3f} vs chain {c['chain']} {c['sum_meV']:.3f} meV/f.u. "
                               f"(gap {c['gap_meV']:.3f} > {net['closure_tol_meV']})")
    return None


def g5q_network(s):
    """The plane's cubic origin must agree with lambda = 0 of every finished path of the campaign per formula unit:
    a different functional, cut-off or potential set between runs shows up here (a 0.2 eV gap for PBE vs PBEsol)."""
    net = (_mq(s) or {}).get("network")
    if not net:
        return None
    bad = [o for o in net["others"] if abs(o["diff_meV"]) > net["tol_meV"]]
    if bad:
        return ("NETWORK", f"the plane's origin differs from the campaign's paths at lambda = 0 by more than "
                           f"{net['tol_meV']} meV/f.u.: {[(o['path'], round(o['diff_meV'], 3)) for o in bad]} "
                           f"(different DFT settings between runs?)")
    return None


# ---- G6: every number re-derived ------------------------------------------------------------
def g6_every_number_rederived(s):
    r = s.get("report") or {}
    bad = [x for x in r.get("rows", []) if not x["ok"]]
    if not r.get("rows"):
        return ("NOT_REDERIVED", "empty report")
    if bad:
        return ("MISMATCH", "; ".join(f"{x['name']}: {x['value']} vs {x['rederived']}" for x in bad[:5]))
    return None


TESTS: dict[str, list[tuple[str, Callable]]] = {
    "G0": [("intake_in_scope", g0_intake_in_scope), ("intake_decidable", g0_intake_decidable),
           ("intake_consistent", g0_intake_consistent), ("intake_stored_data", g0_intake_stored_data),
           ("matches_schema", g0_matches_schema), ("cif_files_exist", g0_cif_files_exist),
           ("cif_space_groups", g0_cif_space_groups), ("cif_checksums", g0_cif_checksums),
           ("budget_within_limits", g0_budget_within_limits), ("faults_only_in_replay", g0_faults_only_in_replay),
           ("writes_inside_agent_root", g0_writes_inside_agent_root)],
    "G1": [("H_subgroup_of_G", g1_H_subgroup_of_G), ("basis_det_equals_k", g1_basis_det_equals_k),
           ("isodistort_sg_equals_spglib", g1_isodistort_sg_equals_spglib),
           ("mode_norms_equal_As", g1_mode_norms_equal_As), ("components_consistent", g1_components_consistent)],
    "G2": [("c1_active_set_generates_H", g2_c1_active_set_generates_H), ("r5_decision_applied", g2_r5_decision_applied),
           ("c2_atom_matching", g2_c2_atom_matching), ("c2_translation_free", g2_c2_translation_free),
           ("c2_calibration", g2_c2_calibration), ("c2_single_mode_sg_strict", g2_c2_single_mode_sg_strict),
           ("c3_budget_and_tree_coverage", g2_c3_budget_and_tree_coverage),
           ("audit_every_frame_sg_and_dmin", g2_audit_every_frame_sg_and_dmin)],
    "G3": [("none_queued_or_running", g3_none_queued_or_running)],
    "G4": [("converged_or_flagged", g4_converged_or_flagged), ("missing_frames_authorized", g4_missing_frames_authorized)],
    "G5": [("missing_frames", g5_missing_frames), ("cv_error_ok", g5_cv_error_ok), ("residuals_ok", g5_residuals_ok), ("coverage_ok", g5_coverage_ok),
           ("d4_secondaries_hold", g5_d4_secondaries_hold)],
    "G6": [("every_number_rederived", g6_every_number_rederived)],
    "G5_landau6d": [("missing_frames", g5_missing_frames), ("invariants_complete", g5l_invariants_complete), ("cv_error_ok", g5l_cv_error_ok),
                    ("residuals_ok", g5l_residuals_ok), ("coverage_ok", g5l_coverage_ok),
                    ("child_is_ground_state", g5l_child_is_ground_state)],
    "G2_path": [("child_metric", g2p_child_metric), ("end_is_child", g2p_end_is_child),
                ("space_groups", g2p_space_groups), ("equals_stored", g2p_equals_stored)],
    "G4_path": [("accounting", g4p_accounting), ("rederived", g4p_rederived), ("magnetism", g4p_magnetism),
                ("dft_consistent", g4p_dft_consistent), ("missing_frames_authorized", g4_missing_frames_authorized)],
    "G5_path": [("missing_frames", g5_missing_frames), ("profile_complete", g5p_profile_complete), ("cross_setting", g5p_cross_setting),
                ("closure", g5p_closure)],
    "G2_plane2": [("components", g2q_components), ("orbits_burnside", g2q_orbits), ("space_groups", g2q_space_groups)],
    "G5_plane2": [("missing_frames", g5_missing_frames), ("coverage", g5q_coverage), ("fit", g5q_fit), ("minimum_inside", g5q_minimum_inside), ("network", g5q_network)],
    "G4_grid6": [("accounting", g4s_accounting), ("rows_rederived", g4s_rows_rederived),
                 ("controls_symmetric", g4s_controls_symmetric), ("gradients_consistent", g4s_gradients_consistent),
                 ("magnetism", g4s_magnetism), ("dft_consistent", g4s_dft_consistent), ("missing_frames_authorized", g4_missing_frames_authorized)],
    "G2_grid6": [("active_set", g2s_active_set), ("orbits_burnside", g2s_orbits_burnside),
                 ("orbits_equal_stored", g2s_orbits_equal_stored), ("contact_cut_equal_stored", g2s_contact_cut_equal_stored),
                 ("planned_equal_stored", g2s_planned_equal_stored), ("space_groups", g2s_space_groups),
                 ("budget", g2s_budget)],
    "G5_meier_QP": [("missing_frames", g5_missing_frames), ("cv_error_ok", g5m_cv_error_ok), ("residuals_ok", g5m_residuals_ok),
                    ("coverage_ok", g5m_coverage_ok)],
    "G5_surface": [("missing_frames", g5_missing_frames), ("coverage_complete", g5s_coverage_complete), ("minimum_inside_grid", g5s_minimum_inside_grid),
                   ("mirror_symmetry", g5s_mirror_symmetry), ("script_agrees", g5s_script_agrees)],
}


def tests_for(gate: str, state: dict) -> list:
    pol = state.get("config", {}).get("policy", {})
    kind = pol.get("analysis")
    if gate in ("G2", "G4") and pol.get("path"):
        return TESTS[f"{gate}_path"]
    if gate == "G5" and kind == "path":
        return TESTS["G5_path"]
    if gate == "G2" and pol.get("plane2"):
        return TESTS["G2_plane2"]
    if gate == "G4" and pol.get("plane2"):
        return TESTS["G4_path"]                 # same accounting / re-derivation / magnetism / one-INCAR checks
    if gate == "G5" and kind == "plane2":
        return TESTS["G5_plane2"]
    if gate in ("G2", "G4") and pol.get("components") and (pol.get("grid") or {}).get("six"):
        return TESTS[f"{gate}_grid6"]
    if gate == "G5" and kind == "landau6d":
        return TESTS["G5_landau6d"]
    if gate == "G5" and kind in ("surface", "meier_QP", "meier_joint"):
        return TESTS["G5_meier_QP" if kind == "meier_joint" else f"G5_{kind}"]
    return TESTS[gate]


def run_gate(gate: str, state: dict) -> dict:
    mode = state.get("config", {}).get("run", {}).get("mode", "skeleton")
    if mode == "skeleton" and gate != "G0":           # f1-f6 are stubs in skeleton mode
        return {"ok": True, "gate": gate, "code": "OK", "detail": "skeleton mode",
                "tests": [{"test": n, "status": "skipped"} for n, _ in tests_for(gate, state)]}
    results, first_fail = [], None
    for name, fn in tests_for(gate, state):
        try:
            r = fn(state)
        except Exception as exc:          # a crashing test is a failing test
            r = ("TEST_ERROR", f"{name}: {type(exc).__name__}: {exc}")
        if r is None:
            results.append({"test": name, "status": "pass"})
        elif r == SKIP:
            if mode == "skeleton":
                results.append({"test": name, "status": "skipped"})
            else:
                results.append({"test": name, "status": "fail", "code": "NOT_IMPLEMENTED"})
                first_fail = first_fail or ("NOT_IMPLEMENTED", f"{gate}.{name} has no implementation yet")
        else:
            code, detail = r
            results.append({"test": name, "status": "fail", "code": code, "detail": detail})
            first_fail = first_fail or (code, detail)
    if first_fail:
        return {"ok": False, "gate": gate, "code": first_fail[0], "detail": first_fail[1], "tests": results}
    return {"ok": True, "gate": gate, "code": "OK", "detail": "", "tests": results}
