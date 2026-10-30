"""Replay regression report: every number of a completed IRIS thread against the paper and against
the stored 12 Sep results. Writes test_runs/<thread>/regression_report.{md,json}.

  python -m iris_agent.regression --config configs/cssni3.yaml [--thread cssni3_221_62]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import yaml
from langgraph.checkpoint.sqlite import SqliteSaver

from . import config as cfgmod
from .paths import from_config


def _v(x, nd=4):
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def check(rows, quantity, iris, paper=None, ptol=None, stored=None, stol=None, note=""):
    def ok(ref, tol):
        if ref is None:
            return None
        if tol is None:
            return iris == ref
        return abs(float(iris) - float(ref)) <= tol
    rows.append({"quantity": quantity, "iris": iris, "paper": paper, "paper_ok": ok(paper, ptol),
                 "stored": stored, "stored_ok": ok(stored, stol), "note": note})


def build(cfg_path: str, thread: str | None) -> dict:
    cfg = cfgmod.load(cfg_path)
    thread = thread or cfg["thread_id"]
    P = from_config(cfg)
    rd = P.run_dir(thread)
    st = SqliteSaver(sqlite3.connect(str(P.out(rd, "iris.sqlite")))).get(
        {"configurable": {"thread_id": thread}})["channel_values"]
    rf = Path(cfg_path).parent / f"{Path(cfg_path).stem}_reference.yaml"            # <config>_reference.yaml
    if not rf.is_file():
        rf = Path(cfg_path).parent / f"{cfg['system']}_reference.yaml"                 # one file per system (HfO2 T1-T5)
    ref = yaml.safe_load(rf.read_text())
    if cfg["policy"].get("analysis") == "path":
        return _build_path(cfg, thread, P, rd, st, ref)
    if cfg["policy"].get("analysis") == "surface":
        return _build_surface(cfg, thread, P, rd, st, ref)
    if cfg["policy"].get("analysis") == "meier_QP":
        return _with_sensitivity(_build_meier(cfg, thread, P, rd, st, ref), st)
    if cfg["policy"].get("analysis") == "meier_joint":
        return _with_sensitivity(_build_joint(cfg, thread, P, rd, st, ref), st)
    if cfg["policy"].get("analysis") == "landau6d":
        return _build_landau6d(cfg, thread, P, rd, st, ref)
    pp, sp = ref["paper"], ref["stored"]
    dec, sel, grid, model, rep = st["decomposition"], st["selection"], st["grid"], st["model"], st["report"]
    rows: list[dict] = []
    cls = json.loads((P.repo(sp["classification"]) / "step3_isodistort/01_verdict/classification.json").read_text())

    for ir, v in pp["Ap"].items():
        check(rows, f"A_p {ir} (Å)", abs(dec["irreps"][ir]["Ap"]), v, 5e-4, cls["Ap"][ir], 5e-5)
    for ir, v in pp["As"].items():
        check(rows, f"A_s {ir} (Å)", abs(dec["irreps"][ir]["As"]), v, 1e-3, cls["As"][ir], 5e-5)
    check(rows, "active set (axes)", sel["active"], pp["active"], None, cls["active"], None,
          "stored step 3 listed all 4 modes above A_thr; the 2-mode plane was a hand choice, now rule R2")
    check(rows, "held at zero (secondaries)", sel["held_at_zero"], pp["held_at_zero"])
    cal = grid["certify"]["calibration"]
    for ir, c in cal.items():
        check(rows, f"calibration s {ir}", c["s_matrix_over_movie"], pp["calibration_s"], 5e-3,
              json.loads((P.repo("reference_grid") / "grid_spec.json").read_text())["label_scale_applied"][ir] ** -1, 5e-3,
              "stored = 1 / label_scale_applied")
    check(rows, "child displacement |Δr| (Å)", grid["certify"]["overall_child_disp_A"], pp["child_displacement_A"], 5e-4,
          dec["overall"]["As"], 5e-4, "stored = ISODISTORT 'Overall' A_s")
    sz = grid["sizing"]
    for k in ("n", "m", "N"):
        check(rows, f"grid {k}", sz[k], pp["grid"][k])
    stored_man = json.loads((P.repo(sp["grid_manifest"]) / "grid_manifest.json").read_text())
    stored_cnt = {}
    for m in stored_man:
        if not m["tag"].startswith("anchor"):
            stored_cnt[str(m["sg_1e-2"])] = stored_cnt.get(str(m["sg_1e-2"]), 0) + 1
    iris_cnt = rep["summary"]["grid"]["sg_count_grid"]
    for sg, n in pp["frames_by_sg"].items():
        check(rows, f"frames in #{sg}", iris_cnt.get(sg, 0), n, None, stored_cnt.get(sg, 0), None)
    n_d4 = sum(1 for f in grid["frames"] if f["tag"].startswith("d4_"))
    check(rows, "frames matched to stored structures" + (f" (plane; + {n_d4} D4 scan frames)" if n_d4 else ""),
          st["jobs"]["n_matched"] - n_d4, None, None, len(stored_man), None,
          f"max |Δfrac| {st['jobs']['max_dev_frac']:.1e} (tolerance {st['jobs']['tolerance_frac']:.0e})")
    fp = json.loads(P.repo(sp["fit_plane"]).read_text())
    fa = json.loads(P.repo(sp["fit_all_sets"]).read_text())[sp["fit_all_sets_key"]]
    for k in ("a1", "b1", "c1", "a2", "b2", "c2", "λ", "μ"):
        check(rows, f"Landau {k}", model["coefficients"][k], pp["landau"].get(k), 5e-4 if k in pp["landau"] else None,
              fp["coefficients"][k], 1e-9,
              f"all-sets notebook value {fa['coefficients'][k]:.6f}" + (" (μ normalised differently there: ×1/3)" if k == "μ" else ""))
    check(rows, "fit RMS (meV/f.u.)", model["rms_meV"], pp["rms_meV"], 5e-3, fp["rms_meV"], 1e-9)
    check(rows, "fit nodes (r ≤ 1.05 Å)", model["n_fit"], pp["n_fit"], None, fa["n"], None)
    check(rows, "10-fold CV RMS (meV/f.u.)", model["cv"]["rms_meV"], None, None, None, None, "new in IRIS (G5)")
    ring = model["ring"]
    check(rows, "fit ring depth below cubic (meV/f.u.)", ring["depth_meV"], pp["ring_depth_meV"], 1.0, fp["crown_height_meV"], 1e-9)
    check(rows, "fit ring corrugation (meV/f.u.)", ring["corrugation_meV"], pp["corrugation_meV"], 0.05, fp["corrugation_meV"], 1e-9)
    check(rows, "fit ring radius mean (Å)", ring["radius_mean_A"], None, None, fp["brim_radius_A"], 1e-9)
    check(rows, "fit ring radius range (Å)", f"{ring['radius_min_A']:.2f}–{ring['radius_max_A']:.2f}",
          "%.2f–%.2f" % tuple(pp["ring_radius_A"]), None, None, None,
          "paper range not reproduced by the fit; see DFT-grid row")
    rg = model.get("ring_dft_grid", {})
    if rg.get("ok"):
        check(rows, "DFT-grid radial minima (Å, ring_profile.py)", "%.2f–%.2f" % tuple(rg["radial_min_radius_A"]),
              "%.2f–%.2f" % tuple(pp["ring_radius_A"]), None, None, None,
              "lower bound 0.72 matches; upper 0.80 (grid) vs 0.76 (fit)")
        check(rows, "DFT-grid corrugation at r = %.2f Å (meV/f.u.)" % rg["ring_radius_A"], rg["corrugation_meV"],
              pp["corrugation_meV"], 0.05, None, None, "grid, bilinear; the fit gives 1.38")
    out = {"thread": thread, "system": cfg["system"], "rows": rows, "skeptic": {"n_numbers": rep["n_numbers"], "n_ok": rep["n_ok"]},
           "gates": [h for h in st.get("history", []) if "gate" in h]}
    return _with_d4((out, rd, P), st, ref)


def _build_surface(cfg, thread, P, rd, st, ref):
    """Regression for policy.analysis = surface (Ca3Ti2O7). Old-unit (A_s label) and A_p numbers side by side."""
    import numpy as np
    pp, sp = ref["paper"], ref["stored"]
    dec, sel, grid, model, rep = st["decomposition"], st["selection"], st["grid"], st["model"], st["report"]
    rows: list[dict] = []
    cls = json.loads((P.repo(sp["classification"]) / "step3_isodistort/01_verdict/classification.json").read_text())
    for ir, v in pp["Ap"].items():
        check(rows, f"A_p {ir} (Å)", abs(dec["irreps"][ir]["Ap"]), v, 5e-4, cls["Ap"].get(ir), 5e-5)
    for ir, v in pp["As"].items():
        check(rows, f"A_s {ir} (Å)", abs(dec["irreps"][ir]["As"]), v, 5e-4, cls["As"].get(ir), 5e-5)
    for ir, v in dec["irreps"].items():
        if v.get("f_T", 0) > 1e-6:
            check(rows, f"f_T {ir} (rigid-translation fraction)", v["f_T"], None, None, None, None,
                  f"translation-free A_s {v['As_tf']:.4f} Å used by the walk")
    check(rows, "primaries (translation-free walk)", sel["primaries"], pp["primaries"])
    check(rows, "active set (axes)", sel["active"], pp["active"], None, cls.get("active"), None,
          "stored step 3: raw-A_s classification")
    check(rows, "held at zero", sel["held_at_zero"], pp["held_at_zero"], None, None, None,
          "; ".join(f"{o['rule']} overridden for {o['irrep']}" for o in sel.get("policy_overrides", [])))
    for ir, c in grid["certify"]["calibration"].items():
        check(rows, f"calibration s {ir} (A_child / A_movie)", c["s_matrix_over_movie"], pp["calibration_s"][ir], 5e-3)
        check(rows, f"child projection {ir} (Å A_p)", c["child_projection_Ap"], pp["Ap"][ir], 5e-4)
    sz = grid["sizing"]
    for k in ("n", "m", "N"):
        check(rows, f"grid {k}", sz[k], pp["grid"][k])
    check(rows, "grid step dq (Å A_p) [old labels 0.1]", sz["dq"], 0.1 / np.sqrt(2), 1e-12)
    check(rows, "grid half-width q_max (Å A_p) [old labels 1.8]", sz["q_max"], 1.8 / np.sqrt(2), 1e-12)
    man = json.loads((P.repo(sp["grid_manifest"]) / "grid_manifest.json").read_text())
    check(rows, "frames matched to stored structures", st["jobs"]["n_matched"], None, None, len(man), None,
          f"max |Δfrac| {st['jobs']['max_dev_frac']:.1e} (tolerance {st['jobs']['tolerance_frac']:.0e}); "
          f"labels × {st['jobs'].get('label_scale', 1):.6f}")
    ph = model["phases"]
    for n, v in pp["phases_meV"].items():
        check(rows, f"E {n} − E_min (meV/f.u.) at A_p ({ph[n]['Q'][0]:.3f}, {ph[n]['Q'][1]:.3f})",
              ph[n]["E_meV"], v, 0.05, None, None, ph[n]["source"])
    check(rows, f"E A2₁am child − E_min at its true A_p ({ph['child']['Q'][0]:.3f}, {ph['child']['Q'][1]:.3f})",
          ph["child"]["E_meV"], None, None, None, None, "new: bilinear between DFT nodes; the old marker sat at the anchor")
    check(rows, "E range (meV/f.u.)", model["range_meV"], pp["range_meV"], 0.5)
    mn = model["minima"][0]
    check(rows, "grid minimum |A_s| (old labels)", [abs(round(x, 4)) for x in mn["As"]], pp["minimum_As"], None)
    check(rows, "grid minimum |A_p| (Å)", [abs(round(x, 4)) for x in mn["Ap"]],
          [round(float(x / np.sqrt(2)), 4) for x in pp["minimum_As"]], None)
    check(rows, "mirror asymmetry max (meV/f.u.)", max(model["mirror_meV"].values()), None, None, None, None,
          f"G5 tolerance {cfg['policy'].get('surface', {}).get('mirror_tol_meV')}")
    # the published figure's data: same energies, axes × 1/√2
    fig = np.loadtxt(P.repo(sp["figure_csv"]), delimiter=",", skiprows=1)
    ours = np.loadtxt(model["script"]["plane_csv"], delimiter=",", skiprows=1)
    key = lambda a: {(round(x, 6), round(y, 6)): e for x, y, e in a}
    fk = key(np.c_[fig[:, 0] / np.sqrt(2), fig[:, 1] / np.sqrt(2), fig[:, 2]])
    ok = key(ours)
    common = set(fk) & set(ok)
    dmax = max(abs(fk[k] - ok[k]) for k in common) if common else None
    check(rows, "figure CSV nodes reproduced (axes × 1/√2)", len(common), None, None, len(fk), None,
          f"max |ΔE| {dmax:.2e} meV/f.u." if dmax is not None else "no common nodes")
    check(rows, "figure CSV max |ΔE| (meV/f.u.)", dmax, None, None, 0.0, 1e-6)
    out = {"thread": thread, "system": cfg["system"], "rows": rows,
           "skeptic": {"n_numbers": rep["n_numbers"], "n_ok": rep["n_ok"]},
           "gates": [h for h in st.get("history", []) if "gate" in h]}
    return out, rd, P


def _build_meier(cfg, thread, P, rd, st, ref):
    """Regression for policy.analysis = meier_QP (InMnO3 plane). Coefficients in A_s (Meier), per cell."""
    import numpy as np
    from .nodes.f5_meier import NAMES, POWER, design
    pp, sp = ref["paper"], ref["stored"]
    dec, sel, grid, model, rep = st["decomposition"], st["selection"], st["grid"], st["model"], st["report"]
    rows: list[dict] = []
    cls = json.loads((P.repo(sp["classification"]) / "step3_isodistort/01_verdict/classification.json").read_text())
    for ir, v in pp["Ap"].items():
        check(rows, f"A_p {ir} (Å)", abs(dec["irreps"][ir]["Ap"]), v, 5e-4, cls["Ap"].get(ir), 5e-4)
    for ir, v in pp["As"].items():
        check(rows, f"A_s {ir} (Å)", abs(dec["irreps"][ir]["As"]), v, 5e-4, cls["As"].get(ir), 5e-4)
    spec = json.loads((P.repo(sp["grid_spec"]) / "grid_spec.json").read_text())
    g2 = dec["irreps"]["GM2-"]
    check(rows, "f_T GM2- (rigid-translation fraction)", g2["f_T"], None, None, None, None,
          pp.get("f_T_note", ""))
    check(rows, "A_p^tf GM2- (Å) = child on the translation-free axis", g2["Ap_tf"], None, None,
          (spec.get("child_Ap_translation_free") or spec["child_Ap"])["GM2-"], 1e-4)
    check(rows, "primaries", sel["primaries"], pp["primaries"], None, None, None, "K3 alone already gives P6_3cm")
    check(rows, "active set (axes)", sel["active"], pp["active"], None, cls.get("active"), None, "GM2- kept by R4 (polar child)")
    hist = st.get("history", [])
    r5 = [h for h in hist if h.get("code") == "R5_BORDERLINE" and h.get("level")]
    check(rows, "R5 margin (Å, A_s^tf)", sel["r5_gap"], pp.get("r5_gap_A"), 0.003, None, None,
          pp.get("r5_note", ""))
    if r5 or pp.get("r5_gap_A", 1) < cfg["policy"]["r5_margin"]:
        check(rows, "R5 borderline -> decided by", ", ".join(f"{h['level']}: {h.get('option') or h.get('rule') or (h.get('human_answer') or {}).get('option', '')}" for h in r5) or "—",
              None, None, None, None, "run-time human decision (option include_borderline)")
    for ir, c in grid["certify"]["calibration"].items():
        check(rows, f"child projection {ir} (Å A_p^tf)", c["child_projection_Ap"], None, None, c["Ap_child"], 2e-4)
    sz = grid["sizing"]
    for k in ("n", "m", "N"):
        check(rows, f"grid {k}", sz[k], pp["grid"][k])
    man = json.loads((P.repo(sp["grid_manifest"]) / "grid_manifest.json").read_text())
    scnt, by_id = {}, {m_["id"]: m_ for m_ in man}
    anchor_ids = {f["id"] for f in grid["frames"] if f["tag"]}
    for k_, v_ in st["jobs"]["matched"].items():                # stored frames linked to the grid frames (not anchors)
        if int(k_) not in anchor_ids:
            sg_ = str(by_id[v_["stored_id"]]["sg_1e-2"])
            scnt[sg_] = scnt.get(sg_, 0) + 1
    icnt = rep["summary"]["grid"]["sg_count_grid"]
    for sg in sorted(set(scnt) | set(icnt)):
        check(rows, f"frames in #{sg}", icnt.get(sg, 0), None, None, scnt.get(sg, 0), None)
    j = st["jobs"]
    check(rows, "frames matched to stored structures", j["n_matched"], None, None, len(man), None,
          f"max |Δfrac| {j['max_dev_frac']:.1e}" + (f" after removing a rigid shift of up to {j.get('max_rigid_shift_A', 0):.4f} Å"
                                                   if j.get("modulo_translation") else ""))
    # the stored fit = the same procedure on the stored grid labels (rounded to 4 dp) and the same energies:
    # free fit (InMnO3) -> stored json; a_P fixed from the P axis (ErMnO3) -> the published row
    from copy import deepcopy
    from .nodes.f5_meier import f5_meier
    lab = {m_["id"]: m_["ap_A"] for m_ in man}
    mQ, mP = grid["active"]
    stored_of = {int(k): v["stored_id"] for k, v in j["matched"].items()}
    g_lab = deepcopy(grid)
    for f in g_lab["frames"]:
        f["Q"] = {k: float(lab[stored_of[f["id"]]].get(k, 0.0)) for k in (mQ, mP)}
    if model.get("aP_axis"):
        ms = f5_meier({**st, "grid": g_lab})["model"]
        sf = {"coefficients": ms["coefficients_Ap"], "rms_meV": ms["rms_meV"], "Q_star": ms["Q_star_A"],
              "depth": ms["depth_meV"] / 1000, "coupled": [ms["coupled"]["Q_A"], ms["coupled"]["P_A"], ms["coupled"]["E_meV"] / 1000]}
        src, n_w = "procedure on the stored labels", ms["n_fit"]
    else:
        sf = json.loads(P.repo(sp["fit"]).read_text())
        E = st["energies"]["eV_per_cell"]
        pts = [(f["Q"][mQ], f["Q"][mP], E[str(f["id"])]) for f in g_lab["frames"]]
        Q, Pp, Y = map(np.array, zip(*pts))
        o = int(np.argmin(Q**2 + Pp**2)); Y = Y - Y[o]
        w = (np.abs(Q) <= model["window"]["qmax_A"] + 1e-9) & (np.abs(Pp) <= model["window"]["pmax_A"] + 1e-9)
        co, *_ = np.linalg.lstsq(design(Q[w], Pp[w]), Y[w], rcond=None)
        dmax = max(abs(c - sf["coefficients"][k]) for k, c in zip(NAMES, co))
        check(rows, "refit on the stored 4-dp labels: max |Δcoef| vs stored fit (A_p)", float(dmax), None, None, 0.0, 1e-6,
              "same energies, stored labels -> stored coefficients exactly")
        src, n_w = "stored json", int(w.sum())
    nc = model["n_cells"]
    if model.get("aP_axis"):
        ax = model["aP_axis"]
        check(rows, f"a_P from the P axis ({ax['n']} points, P^{'+P^'.join(map(str, ax['powers']))}, |P| ≤ {ax['pmax_A']} Å)",
              model["coefficients_As"]["a_P"], pp["landau_As"]["a_P"], 5e-4, None, None, f"axis fit RMS {ax['rms_meV']:.2f} meV/cell")
    for k in NAMES:
        st_s = sf["coefficients"][k] / np.sqrt(nc) ** POWER[k]
        check(rows, f"{k} (A_s, eV/cell)", model["coefficients_As"][k], pp["landau_As"][k], 5e-4 if k != "g'" else 5e-3,
              st_s, 1e-6, f"stored = {src}; grid labels rounded to 4 dp, IRIS uses the exact Q")
    if model.get("aP_axis"):
        for k in NAMES:
            check(rows, f"{k} (A_s) from the stored labels vs paper", round(sf["coefficients"][k] / np.sqrt(nc) ** POWER[k], 3),
                  pp["landau_As"][k], 5e-4 if k != "g'" else 5e-3, None, None, "isolates the label rounding")
    check(rows, "fit RMS (meV/cell)", model["rms_meV"], pp["rms_meV"], 0.05, sf["rms_meV"], 0.01)
    check(rows, "fit nodes in window", model["n_fit"], pp.get("n_fit"), None, n_w, None)
    check(rows, "10-fold CV RMS (meV/cell)", model["cv"]["rms_meV"], None, None, None, None, "new in IRIS (G5)")
    check(rows, "K3 well Q* (Å, A_s)", model["Q_star_As"], pp["Q_star_As"], 5e-4, sf["Q_star"] * np.sqrt(nc), 2e-3)
    check(rows, "well depth (meV/cell)", model["depth_meV"], pp["depth_meV"], 0.5, sf["depth"] * 1000, 0.5)
    check(rows, "coupled minimum Q (Å, A_s)", model["coupled_As"][0], pp["coupled_As"][0], 5e-4, sf["coupled"][0] * np.sqrt(nc), 2e-3)
    check(rows, "coupled minimum P (Å, A_s)", model["coupled_As"][1], pp["coupled_As"][1], 5e-4, sf["coupled"][1] * np.sqrt(nc), 2e-3)
    check(rows, "hat height (meV/cell)", model["hat_meV_per_cell"], pp["hat_meV"], 0.5, -sf["coupled"][2] * 1000, 0.5)
    out = {"thread": thread, "system": cfg["system"], "rows": rows,
           "skeptic": {"n_numbers": rep["n_numbers"], "n_ok": rep["n_ok"]},
           "gates": [h for h in hist if "gate" in h]}
    return out, rd, P


def _build_joint(cfg, thread, P, rd, st, ref):
    """Regression for policy.analysis = meier_joint (stage 2: plane + hat wedge, joint Meier fit with c')."""
    import numpy as np
    from copy import deepcopy
    from .nodes.f5_joint import f5_joint
    pp, sp = ref["paper"], ref["stored"]
    sel, grid, model, rep, j = st["selection"], st["grid"], st["model"], st["report"], st["jobs"]
    rows: list[dict] = []
    hist = st.get("history", [])
    check(rows, "active set (axes)", sel["active"], pp["active"])
    r5 = [h for h in hist if h.get("code") == "R5_BORDERLINE" and h.get("level")]
    if r5:
        check(rows, "R5 borderline -> decided by", ", ".join(f"{h['level']}: {h.get('option') or ''}" for h in r5), None, None,
              None, None, "run-time human decision")
    pol = grid["polar"]
    check(rows, "second K3 component: phase shift of the translation (deg)", pol["phase_shift_deg"], 120.0, 1e-6)
    check(rows, "second K3 component: |T e1| / |e1|", pol["norm_ratio_T"], 1.0, 1e-9)
    check(rows, "hat frames (Q x Phi x P)", pol["n"], pp["hat_frames"], None)
    stored_hat = json.loads((P.repo_root / cfg["run"]["replay"]["extra_references"][0]["grid"] / "grid_manifest.json").read_text())
    check(rows, "frames matched to stored structures", j["n_matched"], None, None, j["n_frames"], None,
          f"plane{' + P axis' if grid['n_anchors'] else ''} + {len(stored_hat)} hat; max |Δfrac| {j['max_dev_frac']:.1e}")
    check(rows, "DFT input sets across all frames", len(j["stored_input_sets"]), 1, None, None, None,
          "INCAR/KPOINTS settings identical for plane, hat (and P axis)")
    pcnt = {}
    for f in grid["frames"]:
        if f.get("polar"):
            pcnt[str(f["sg"])] = pcnt.get(str(f["sg"]), 0) + 1
    for sg, n in sorted(pp["hat_frames_by_sg"].items()):
        check(rows, f"hat frames in #{sg}", pcnt.get(str(sg), 0), n, None)
    # the same joint procedure on the stored labels (4-dp plane labels, hat Q/theta/P labels) = the published script
    man = json.loads((P.repo("reference_grid") / "grid_manifest.json").read_text())
    lab = {m_["id"]: m_ for m_ in man}
    hl = {m_["id"]: m_ for m_ in stored_hat}
    mQ, mP = grid["active"]
    g_lab = deepcopy(grid)
    for f in g_lab["frames"]:
        rec = j["matched"][str(f["id"])]
        if rec.get("ref"):
            h = hl[int(str(rec["stored_id"]).split(":")[1])]
            f["Q"] = {mQ: float(h["Q_A"]), mP: float(h["P_A"])}; f["phi_deg"] = float(h["theta_deg"])
        else:
            a_ = lab[rec["stored_id"]]["ap_A"]
            f["Q"] = {mQ: float(a_.get(mQ, 0.0)), mP: float(a_.get(mP, 0.0))}
    ms = f5_joint({**st, "grid": g_lab})["model"]
    note = "IRIS uses the exact amplitudes; the stored grid labels are rounded to 4 dp (rows below)"
    for k in ("a", "b", "c", "c'", "a_P", "g", "g'"):
        check(rows, f"{k} (A_s, eV/cell)", model["coefficients_As"][k], pp["coef_As"][k], 5e-4 if k != "g'" else 5e-3, None, None, note)
    check(rows, "joint fit nodes (plane + hat)", f"{model['n_fit_plane']} + {model['n_fit_hat']}", f"{pp['n_fit'][0]} + {pp['n_fit'][1]}")
    check(rows, "joint RMS (meV/cell)", model["rms_meV"], pp["rms_meV"], 0.05)
    check(rows, "  plane / hat RMS (meV/cell)", f"{model['rms_plane_meV']:.1f} / {model['rms_hat_meV']:.1f}",
          f"{pp['rms_plane_hat'][0]} / {pp['rms_plane_hat'][1]}")
    check(rows, "10-fold CV RMS (meV/cell)", model["cv"]["rms_meV"], None, None, None, None, "new in IRIS (G5)")
    check(rows, "hat height (meV/f.u.)", model["hat_meV_per_fu"], pp["hat_meV_per_fu"], 0.05)
    check(rows, "brim barrier, Q and P relaxed (meV/f.u.)", model["brim_meV_per_fu"], pp["brim_meV_per_fu"], 0.005)
    check(rows, "brim barrier with c' = 0 (meV/f.u.)", model["brim_cprime0_meV_per_fu"], pp["brim_c0_meV_per_fu"], 0.005)
    # the same procedure on the stored labels reproduces the published script (isolates the label rounding)
    for k in ("a", "b", "c", "c'", "a_P", "g", "g'"):
        check(rows, f"stored labels: {k} (A_s)", round(ms["coefficients_As"][k], 3), pp["coef_As"][k], 5e-4 if k != "g'" else 5e-3)
    check(rows, "stored labels: RMS / hat / brim / brim c'=0",
          f"{ms['rms_meV']:.1f} / {ms['hat_meV_per_fu']:.1f} / {ms['brim_meV_per_fu']:.2f} / {ms['brim_cprime0_meV_per_fu']:.2f}",
          f"{pp['rms_meV']} / {pp['hat_meV_per_fu']} / {pp['brim_meV_per_fu']:.2f} / {pp['brim_c0_meV_per_fu']:.2f}")
    out = {"thread": thread, "system": cfg["system"], "rows": rows,
           "skeptic": {"n_numbers": rep["n_numbers"], "n_ok": rep["n_ok"]},
           "gates": [h for h in hist if "gate" in h]}
    return out, rd, P


def _with_d4(res, st, ref):
    """D4 scan rows (policy.d4): curvature, relaxed amplitude and released energy per scan vs the stored
    12 Sep step-5 resolution (grid minimum of each scan), and the G5 decision."""
    out, rd, P = res
    d4 = (st.get("model") or {}).get("d4")
    if not d4:
        return res
    sd = (ref.get("stored") or {}).get("d4") or {}
    for sc in d4["scans"]:
        q = sc["deg4"]
        check(out["rows"], f"D4 {sc['name']} ({sc['irrep']}; primaries {', '.join(f'{k} {v:.3f}' for k, v in sc['base'].items() if v) or 'none'}): "
              "curvature / relaxed / released", f"{q['curvature_meV_per_A2']:.1f} / {q['a_star_A']:.3f} / {abs(q['gain_meV']):.2f}",
              None, None, None, None, f"{sc['class']}; quartic fit RMS {q['rms_meV']:.3f} meV")
        if sc["name"] in sd:
            check(out["rows"], f"D4 {sc['name']}: grid minimum (meV/f.u.)", sc["grid_min_meV"], None, None, sd[sc["name"]], 1e-3,
                  "stored step5_analysis_x5_* resolution.json")
    check(out["rows"], "D4 largest released energy vs max_fraction x reference (meV/f.u.)",
          f"{d4['largest_gain_meV']:.2f} vs {d4['max_fraction']} x {d4['reference_meV']:.3f}", None, None, None, None,
          "accepted by the human (kept at zero, caveat)" if d4.get("accepted") else "")
    return out, rd, P


def _with_sensitivity(res, st):
    """a_P sensitivity rows (policy.fit.aP_axis.sensitivity; reported only, Q20)."""
    out, rd, P = res
    sens = (st.get("model") or {}).get("aP_sensitivity") or []
    for r in sens:
        if "error" in r:
            check(out["rows"], f"a_P sensitivity |P| <= {r['pmax_A']}, powers {r['powers']}", r["error"])
            continue
        derived = {k: v for k, v in r.items() if k in ("hat_meV_per_cell", "depth_meV", "hat_meV_per_fu", "brim_meV_per_fu")}
        txt = f"a_P {r['a_P_As']:.4f} (axis n {r['n_axis']}, RMS {r['axis_rms_meV']:.2f} meV); fit RMS {r['rms_meV']:.2f}; " + \
            ", ".join(f"{k} {v:.2f}" for k, v in derived.items())
        check(out["rows"], f"a_P sensitivity |P| <= {r['pmax_A']} Å, P^{'+P^'.join(map(str, r['powers']))}", txt, None, None, None, None,
              "published choice" if r["published"] else "reported only")
    if sens:
        ok = [r for r in sens if "error" not in r]
        for k in ("hat_meV_per_cell", "hat_meV_per_fu", "brim_meV_per_fu"):
            v = [r[k] for r in ok if r.get(k) is not None]
            if v:
                check(out["rows"], f"a_P sensitivity: spread of {k} over all choices", f"{max(v) - min(v):.3f}", None, None, None, None,
                      f"a_P {min(r['a_P_As'] for r in ok):.3f}–{max(r['a_P_As'] for r in ok):.3f}")
    return out, rd, P


def _build_landau6d(cfg, thread, P, rd, st, ref):
    """Regression for policy.analysis = landau6d (BiFeO3 B1-B4)."""
    pp, sp = ref["paper"], ref["stored"]
    dec, grid, jobs, en, model, rep = (st[k] for k in ("decomposition", "grid", "jobs", "energies", "model", "report"))
    hist = st.get("history", [])
    rows: list[dict] = []
    c = dec["components"]
    note = "IRIS from the stored mode matrix; the grid used the printed 5-decimal amplitudes"
    check(rows, "B1 GM4- per-component A_p (Å)", c["component_Ap"][0], None, None, sp["component_Ap"][0], 5e-5, note)
    check(rows, "B1 R5- per-component A_p (Å)", c["component_Ap"][3], None, None, sp["component_Ap"][1], 5e-5, note)
    for k, v in sp["composition"].items():
        check(rows, f"B1 polar composition {k}", c["composition_unit_fu"]["P1"][k], None, None, v, 1e-4)
    g = c["grid"]
    check(rows, "B1 96 matrices = grid toolkit's", g["matrices_equal_grid_toolkit"], None, None, True, None)
    check(rows, "B1 folded vectors vs grid basis, max (Å)", max(g["fold_residual_A"]), None, None, 0.0, 1e-4)
    for d in grid["datasets"]:
        n, o, k, nk = sp["orbits"][d["name"]]
        check(rows, f"B2 {d['name']} nodes / orbits / kept / kept nodes",
              f"{d['n_nodes']} / {d['n_orbits']} / {d['n_orbits_included']} / {d['n_nodes_included']}", None, None,
              f"{n} / {o} / {k} / {nk}", None, "representatives, multiplicities, node map identical to orbits.npz")
    check(rows, "B2 frames planned (all roles)", grid["n_frames"], None, None, sp["frames"], None)
    check(rows, "B3 frames matched to stored POSCARs", jobs["n_matched"], None, None, sp["frames"], None,
          f"max |Δr| {jobs['max_dev_A']:.1e} Å")
    ct = en["controls"]
    check(rows, "B3 controls compared", ct["n"], None, None, sp["controls"]["n"], None)
    check(rows, "B3 controls max |ΔE| (meV/f.u.)", ct["max_dE_meV"], None, None, sp["controls"]["max_dE_meV"], 1e-4)
    check(rows, "B3 controls max |Δgrad| (meV/Å/f.u.)", ct["max_dgrad"], None, None, sp["controls"]["max_dgrad_meV_per_A"], 1e-3)
    r = en["refine_on_main"]
    check(rows, "B3 refine points on main nodes", r["n"], None, None, sp["refine_vs_main"]["n"], None)
    check(rows, "B3 refine vs main max |ΔE| (meV/f.u.)", r["max_dE_meV"], None, None, sp["refine_vs_main"]["max_dE_meV"], 1e-4)
    check(rows, "B3 SCF-limited runs", en["n_scf_limited"], None, None, sp["scf_limited"], None)
    check(rows, "B3 Simpson line-integral slope", en["line_integral"]["slope"], None, None, None, None, "new in IRIS (G4)")
    check(rows, "B4 invariants (Molien)", model["n_invariants"], pp["n_invariants"], None, round(model["molien_total_2_to_deg"]), None)
    for nm, n_ in pp["n_rows"].items():
        check(rows, f"B4 rows {nm}", model["n_rows"][nm], n_, None)
    for k, (n_, rms, mx) in pp["refit_log"].items():
        t = model["tests"][k]
        check(rows, f"B4 {k}: n / RMS / max", f"{t['n']} / {t['rms_meV']:.2f} / {t['max_meV']:.2f}", f"{n_} / {rms:.2f} / {mx:.2f}")
    check(rows, "B4 10-fold CV RMS (meV/f.u.)", model["cv"]["rms_meV"], None, None, None, None, "new in IRIS (G5)")
    vs = model["vs_stored_coef"]
    check(rows, "B4 coefficients vs coef_V1_deg12_E1000_final.npy, max relative", f"{vs['max_rel_diff']:.1e}", "0", None, None, None,
          "IRIS labels (exact amplitudes)")
    rows[-1]["paper_ok"] = vs["max_rel_diff"] <= 1e-4
    check(rows, "B4 coefficients, stored labels, max relative", f"{vs['stored_labels_max_rel_diff']:.1e}", "0", None, None, None,
          "the same procedure on the CSV's own q (7 dp): the published file to floating-point round-off")
    rows[-1]["paper_ok"] = vs["stored_labels_max_rel_diff"] <= 1e-9
    for nm, (e, p, r_, idx) in pp["stationary"].items():
        s = model["stationary"][nm]
        check(rows, f"B4 {nm}: E / |P| / |R| / index", f"{s['E_meV']:.1f} / {s['P_A']:.3f} / {s['R_A']:.3f} / {s['index']}",
              f"{e:.1f} / {p:.3f} / {r_:.3f} / {idx}")
    check(rows, "B4 global minimum (60 starts, meV/f.u.)", model["global_search"]["lowest_meV"], pp["global_minimum_meV"], 0.05)
    v0, p0 = (model.get("secondary") or {}).get("V0"), pp.get("V0")
    if v0 and p0:
        x = v0["iris"]
        check(rows, "V0 (SI) training n / RMS", f"{x['training']['n']} / {x['training']['rms_meV']:.3f}",
              f"{p0['training'][0]} / {p0['training'][1]:.3f}")
        check(rows, "V0 (SI) 20 % hold-out RMS / max", f"{x['hold-out']['rms_meV']:.3f} / {x['hold-out']['max_meV']:.3f}",
              f"{p0['holdout'][0]:.3f} / {p0['holdout'][1]:.3f}", None, None, None, "")
        rows[-1]["paper_ok"] = abs(x["hold-out"]["rms_meV"] - p0["holdout"][0]) < 5e-4 and abs(x["hold-out"]["max_meV"] - p0["holdout"][1]) < 5e-3
        check(rows, "V0 (SI) coefficients vs coef_V0_deg12_E1000.npy, max relative (IRIS / stored labels)",
              f"{v0['vs_stored_coef']['max_rel_diff']:.1e} / {v0['vs_stored_coef']['stored_labels_max_rel_diff']:.1e}", "0 / 0")
        rows[-1]["paper_ok"] = v0["vs_stored_coef"]["max_rel_diff"] <= 1e-4 and v0["vs_stored_coef"]["stored_labels_max_rel_diff"] <= 1e-9
        for nm, (e, p, r_, idx) in p0["stationary"].items():
            s = x["stationary"][nm]
            check(rows, f"V0 (SI) {nm}: E / |P| / |R| / index", f"{s['E_meV']:.1f} / {s['P_A']:.4f} / {s['R_A']:.4f} / {s['index']}",
                  f"{e:.1f} / {p:.4f} / {r_:.4f} / {idx}")
        check(rows, "V0 (SI) global minimum (60 starts)", x["global_search"]["lowest_meV"], p0["global_minimum_meV"], 0.05)
    if model.get("rbf"):
        mx = max(abs(v["diff_meV"]) for v in model["rbf"]["at_stationary"].values())
        check(rows, "B4 RBF − polynomial at the nine stationary points, max (meV/f.u.)", mx, None, None, None, None,
              "cross-check only (work/fit_rbf6d.py, trend 8)")
    out = {"thread": thread, "system": cfg["system"], "rows": rows,
           "skeptic": {"n_numbers": rep["n_numbers"], "n_ok": rep["n_ok"]},
           "gates": [h for h in hist if "gate" in h]}
    return out, rd, P


def _build_path(cfg, thread, P, rd, st, ref):
    """Regression for policy.analysis = path (HfO2 T1-T5, H1-H3): certified decomposition (Paper 1), the runbook
    table of 2026-10-08 and the stored collector output (energies_summary.json)."""
    dec, grid, jobs, en, model, rep = (st[k] for k in ("decomposition", "grid", "jobs", "energies", "model", "report"))
    hist = st.get("history", [])
    pp = cfg["policy"]["path"]
    pid = pp["stored"].rstrip("/").split("/")[-1]
    t = pid.split("_")[0]
    r = ref["transitions"][t]
    summ = json.loads((P.repo_root / pp["collected"] / "energies_summary.json").read_text())
    ss = summ["paths"][pid]
    rows: list[dict] = []
    for ir, v in r["Ap"].items():
        check(rows, f"H1 A_p {ir} (Å)", abs(dec["irreps"][ir]["Ap"]), v, 6e-5, None, None, "certified Paper 1 value")
    for ir, v in (r.get("Ap_tf") or {}).items():
        check(rows, f"H1 A_p {ir} translation-free (Å)", dec["irreps"][ir]["Ap_tf"], v, 2e-4)
    for ir, comps in r["strain"].items():
        got = [x["amplitude"] for x in dec["strain_components"][ir]][-len(comps):]
        check(rows, f"H1 strain {ir}", " / ".join(f"{x:.4f}" for x in got), " / ".join(f"{x:.4f}" for x in comps), None, None, None)
        rows[-1]["paper_ok"] = all(abs(a - b) <= 6e-4 for a, b in zip(got, comps))
    g = grid["stored"]
    check(rows, "H2 path frames", grid["n_frames"], None, None, g["n_points"], None)
    check(rows, "H2 A_p along the path vs path.json, max |Δ| (Å)", g["Ap_max_dev_A"], None, None, 0.0, 2e-4)
    check(rows, "H2 cells vs point.json, max |Δ| (Å)", g["lattice_max_dev_A"], None, None, 0.0, 1e-4)
    check(rows, "H2 rigid rotation of the child cell (deg)", grid["lattice"]["rigid_rotation_deg"], None, None, None, None,
          f"orientation {grid['lattice']['orientation']}; pure stretch would be 0 (Q36)")
    check(rows, "H3 frames matched to stored POSCARs", jobs["n_matched"], None, None, g["n_points"], None,
          f"max |Δr| {jobs['max_dev_A']:.1e} Å, cells {jobs['max_lattice_dev_A']:.1e} Å")
    dmax = max(abs(a - b) for a, b in zip(model["dE_meV"], ss["dE_meV_per_fu"]))
    check(rows, "H3 dE(λ), 10 points vs energies_summary.json, max |Δ| (meV/f.u.)", dmax, None, None, 0.0, 6e-4,
          "stored values rounded to 3 decimals")
    b, lb = r["barrier"]
    check(rows, "H3 frozen-path barrier (meV/f.u.)", model["barrier_meV"], b, 0.005, ss["barrier_meV_per_fu"], 6e-4,
          "upper bound (no relaxation); runbook table")
    check(rows, "H3 barrier at λ", model["barrier_lambda"], lb, 6e-4, ss["barrier_at_lambda"], 1e-4)
    check(rows, "H3 dE end (meV/f.u.)", model["dE_end_meV"], r["dE_end"], 0.005, ss["dE_end_meV_per_fu"], 6e-4)
    if r.get("paper1_barrier") is not None:
        check(rows, "H3 barrier vs Paper 1 frozen barrier (meV/f.u.)", model["barrier_meV"], r["paper1_barrier"], None, None, None,
              f"Paper 1 path construction differs; Δ = {model['barrier_meV'] - r['paper1_barrier']:+.2f}")
        rows[-1]["paper_ok"] = None
    bs = model["barrier_spline"]
    check(rows, "H3 spline barrier / λ (meV/f.u.)", f"{bs['meV']:.2f} / {bs['lambda']:.3f}", None, None, None, None,
          "new in IRIS: between-point estimate, not gated")
    net = model.get("network") or {}
    groups = {c["structure"]: c for c in summ.get("cross_checks", [])}
    for c in net.get("cross_setting", []):
        k_own = f"{pid}:{c['own']}"
        grp = next((n for n, gg in groups.items() if k_own in gg["E0_per_fu_eV"] and c["other"] in gg["E0_per_fu_eV"]), None)
        sd = None if grp is None else 1000 * (groups[grp]["E0_per_fu_eV"][k_own] - groups[grp]["E0_per_fu_eV"][c["other"]])
        check(rows, f"H3 cross-setting {c['own']} vs {c['other'].replace('__lin10', '')} (meV/f.u.)", c["diff_meV"],
              ref.get("cross_setting_meV", {}).get(grp), None, sd, 1e-6,
              f"found by structure ({grp or 'not paired by the collector'}); Γ {c.get('kmesh_own')} vs {c.get('kmesh_other')}; "
              "paper column = runbook spread of the group")
        rows[-1]["paper_ok"] = None if grp is None else abs(c["diff_meV"]) <= ref["cross_setting_meV"][grp] + 5e-4
    for cl in net.get("closure", []):
        rc = (ref.get("closure") or {}).get(t)
        check(rows, f"H3 closure: chain sum / own dE end (meV/f.u.)", f"{cl['sum_meV']:.2f} / {cl['own_meV']:.2f}",
              None if rc is None else f"{rc[0]:.2f} / {rc[1]:.2f}", None, None, None, " + ".join(x.split("__")[0] for x in cl["chain"]))
        check(rows, "H3 closure gap (meV/f.u.)", cl["gap_meV"], None, None, None, None,
              "= sum of the cross-setting differences at the shared structures (f6 identity)")
        rows[-1]["paper_ok"] = abs(cl["gap_meV"]) <= ref["closure_meV"] + 5e-4
    out = {"thread": thread, "system": cfg["system"], "transition": t, "rows": rows,
           "skeptic": {"n_numbers": rep["n_numbers"], "n_ok": rep["n_ok"]},
           "gates": [h for h in hist if "gate" in h]}
    return out, rd, P


TITLES = {"hfo2": "HfO₂", "cssni3": "CsSnI₃", "ca3ti2o7": "Ca₃Ti₂O₇", "inmno3": "InMnO₃", "ermno3": "ErMnO₃", "bifeo3": "BiFeO₃"}


def to_md(out) -> str:
    def mark(x):
        return "—" if x is None else ("✓" if x else "✗")
    L = [f"# {TITLES.get(out.get('system', 'cssni3'), out.get('system'))} replay regression — thread `{out['thread']}`", "",
         f"f6 Skeptic: {out['skeptic']['n_ok']}/{out['skeptic']['n_numbers']} numbers re-derived independently.", "",
         "Gate trail: " + " → ".join(f"{h['gate']} {h['code']}" for h in out["gates"]), "",
         "| quantity | IRIS rerun | paper | | stored | | note |", "|---|---|---|---|---|---|---|"]
    for r in out["rows"]:
        L.append(f"| {r['quantity']} | {_v(r['iris'])} | {'' if r['paper'] is None else r['paper']} | {mark(r['paper_ok'])} "
                 f"| {'' if r['stored'] is None else _v(r['stored'], 6)} | {mark(r['stored_ok'])} | {r['note']} |")
    n_p = [r["paper_ok"] for r in out["rows"] if r["paper_ok"] is not None]
    n_s = [r["stored_ok"] for r in out["rows"] if r["stored_ok"] is not None]
    L += ["", f"Paper: {sum(n_p)}/{len(n_p)} match · stored: {sum(n_s)}/{len(n_s)} match."]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--thread", default=None)
    a = ap.parse_args(argv)
    out, rd, P = build(a.config, a.thread)
    P.out(rd, "regression_report.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    md = to_md(out)
    P.out(rd, "regression_report.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
