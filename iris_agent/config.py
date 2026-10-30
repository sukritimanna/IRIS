"""Run config: one YAML file per system holds every data path and policy value.

`validate()` is plain Python (no LLM). It returns a list of error strings; G0 fails with code
SCHEMA when the list is non-empty. In step 6 the f0 LLM will produce this same structure from a
plain-language request and be re-asked with these error strings on failure.
"""
from __future__ import annotations

from pathlib import Path

import yaml

MODES = ("skeleton", "replay", "live")
ENGINES = ("dft", "mace")
STRAIN_POLICIES = ("P1", "P2", "P3", "P4", "P5")
ANALYSES = ("landau_plane", "surface", "meier_QP", "meier_joint", "landau6d", "path", "plane2")
MAX_BUDGET = 20000          # hard ceiling on runs per campaign (safety; B itself is per-config)

# key -> (type, required, check)   check returns an error string or None
SCHEMA: dict[str, tuple] = {
    "system": (str, True, None),
    "thread_id": (str, True, None),
    "request": (str, False, None),
    "run.mode": (str, True, lambda v: None if v in MODES else f"must be one of {MODES}"),
    "run.engine": (str, True, lambda v: None if v in ENGINES else f"must be one of {ENGINES}"),
    "run.budget_runs": (int, True,
                        lambda v: None if 0 < v <= MAX_BUDGET else f"must be in 1..{MAX_BUDGET}"),
    "run.allow_live_submission": (bool, True, None),      # true only together with run.mode: live (checked below)
    "run.live.submit_cmd": (str, False, None),            # e.g. "qsub" (PBS) ; the live executor is the only caller
    "run.live.queue_cmd": (str, False, None),             # e.g. "qstat" ; used to see which job ids are still known
    "run.live.job_header": (str, False, None),            # scheduler header lines for one job part (PBS #PBS ...)
    "run.live.vasp_cmd": (str, False, None),              # e.g. "mpirun vasp_std"
    "run.live.potcar_dir": (str, False, None),            # PotcarDirs: POTCAR = cat <dir>/<Element>/POTCAR in POSCAR order (writePotcar)
    "run.live.potcar_labels": (dict, False, None),        # optional element -> subfolder map (default: the element name)
    "run.live.incar": (dict, False, None),                # INCAR tags for every frame
    "run.live.kspacing": ((int, float), False, lambda v: None if 0.05 <= v <= 1.0 else "spacing in 1/A (2pi incl.), 0.05..1"),  # kpointsUtilities rule (default 0.20)
    "run.live.kpoints": (list, False, lambda v: None if len(v) == 3 and all(isinstance(k, int) and k > 0 for k in v)
                         else "three positive integers"),
    "run.live.poll_s": ((int, float), False, lambda v: None if v >= 5 else "must be >= 5 s"),
    "run.jobs.wait": (bool, False, None),
    "run.stop_after": (str, False, lambda v: None if v in ("f1", "f2", "f3", "f4", "f5")
                       else "must be f1..f5 (staged replays: END after that node's gate passes)"),
    "policy.components": (dict, False, lambda v: None if {"kind", "polar", "rotation"} <= set(v) and v["kind"] == "cubic_perovskite_GR"
                          else "needs kind: cubic_perovskite_GR, polar, rotation (and grid_toolkit: true/false)"),
    "run.jobs.part_size": (int, False, lambda v: None if v >= 1 else "must be >= 1"),
    "paths.repo_root": (str, True, None),
    "paths.agent_root": (str, True, None),
    "paths.parent_cif": (str, True, None),
    "paths.child_cif": (str, True, None),
    "paths.system_json": (str, True, None),
    "paths.test_runs": (str, True, None),
    "expected.parent_sg": (int, True, lambda v: None if 1 <= v <= 230 else "not a space-group number"),
    "expected.child_sg": (int, True, lambda v: None if 1 <= v <= 230 else "not a space-group number"),
    "expected.parent_sha256": (str, False, lambda v: None if len(v) == 64 else "must be a sha256 hex digest"),
    "expected.child_sha256": (str, False, lambda v: None if len(v) == 64 else "must be a sha256 hex digest"),
    "policy.a_thr": ((int, float), True, lambda v: None if 0 < v < 1 else "must be in (0, 1) Å"),
    "policy.amplitude_basis": (str, True, lambda v: None if v in ("As", "Ap", "As_tf")
                               else "must be As, Ap or As_tf (A_s of the translation-free vector)"),
    "policy.hold_at_zero": (list, False, None),
    "policy.hold_at_zero_reason": (str, False, None),
    "policy.analysis": (str, False, lambda v: None if v in ANALYSES else f"must be one of {ANALYSES}"),
    "policy.surface.mirror_tol_meV": ((int, float), False, lambda v: None if v > 0 else "must be > 0"),
    "policy.surface.edge_margin_steps": (int, False, lambda v: None if v >= 1 else "must be >= 1"),
    "run.replay.label_scale": ((int, float), False, lambda v: None if v > 0 else "must be > 0"),
    "run.replay.match_modulo_translation": (bool, False, None),
    "run.replay.extra_references": (list, False, lambda v: None if all({"tag", "grid", "energies", "labels"} <= set(x) for x in v)
                                    else "each entry needs tag, grid, energies, labels"),
    "policy.grid.polar": (dict, False, lambda v: None if {"irrep", "secondary", "Q", "phi_deg", "P", "translation",
                                                          "expected_sg"} <= set(v) else "polar grid needs irrep, secondary, Q, phi_deg, P, translation, expected_sg"),
    "policy.fit.joint": (dict, False, None),
    "policy.fit.allow_missing_frames": (bool, False, None),   # human authorisation for a fit on fewer frames (G4 MISSING_FRAMES)
    "policy.grid.six": (dict, False, lambda v: None if {"steps_A", "datasets"} <= set(v) and all(
        {"name", "radius", "a_c", "dmin_cut", "stored"} <= set(d) for d in v["datasets"])
        else "needs steps_A and datasets (name, radius, a_c, dmin_cut, stored)"),
    "paths.grid_packages": (list, False, None),
    "policy.path": (dict, False, lambda v: None if v.get("n_points", 10) >= 3 and (v.get("child_lattice") or {}).get("orientation", "pure_stretch")
                    in ("stored", "pure_stretch") else "n_points >= 3; child_lattice.orientation stored | pure_stretch"),
    "policy.plane2": (dict, False, lambda v: None if v.get("irrep") and 2 <= int(v.get("levels", 5)) <= 15 and float(v.get("q_max", 1.2)) > 0
                      and v.get("stored") and v.get("collected") else "needs irrep, stored, collected; levels 2..15, q_max > 0"),
    "policy.path.network": (dict, False, lambda v: None if isinstance(v.get("paths"), list) and all(
        isinstance(c, list) and c for c in v.get("closure") or []) else "needs paths: [...] (and closure: [[...], ...])"),
    "paths.incar_template": (str, False, None),
    "paths.recovery": (str, False, None),          # recovery table (default recovery.yaml; live runs: recovery_live.yaml)
    "run.replay.tol_lattice_A": ((int, float), False, lambda v: None if 0 < v < 0.1 else "must be in (0, 0.1) Å"),
    "policy.d4": (dict, False, lambda v: None if v.get("scans") and all({"name", "irrep", "base", "amplitudes"} <= set(x) for x in v["scans"])
                  else "needs scans: [{name, irrep, base, amplitudes}] (and compare_to, max_fraction)"),
    "policy.fit.six": (dict, False, lambda v: None if {"degree", "E_window_meV", "grad_weight_A", "parts"} <= set(v)
                       else "needs degree, E_window_meV, grad_weight_A, parts"),
    "policy.qc": (dict, False, lambda v: None if v.get("scf_limited", "keep_energy_drop_gradients") in
                  ("keep_energy_drop_gradients", "drop") else "scf_limited: keep_energy_drop_gradients or drop"),
    "run.replay.tol_A": ((int, float), False, lambda v: None if 0 < v < 0.1 else "must be in (0, 0.1) Å"),
    "run.replay.poscar_dirs": (list, False, lambda v: None if all(isinstance(d, dict) and "dir" in d for d in v)
                               else "each entry needs dir (and id_offset)"),
    "run.replay.max_rigid_shift_A": ((int, float), False, lambda v: None if 0 < v < 0.5 else "must be in (0, 0.5) Å"),
    "policy.grid.axes": (dict, False, lambda v: None if all(isinstance(a, dict) and a.get("q_max", 0) > 0 and a.get("dq", 0) > 0
                                                          for a in v.values()) else "each axis needs q_max > 0 and dq > 0"),
    "policy.fit.qmax": ((int, float), False, lambda v: None if v > 0 else "must be > 0"),
    "policy.fit.aP_axis": (dict, False, lambda v: None if v.get("pmax", 0) > 0 else "needs pmax > 0 (and powers, tag_prefix)"),
    "policy.fit.pmax": ((int, float), False, lambda v: None if v > 0 else "must be > 0"),
    "policy.fit.edge_margin_steps": ((int, float), False, lambda v: None if v >= 0 else "must be >= 0"),
    "policy.r5_margin": ((int, float), True, lambda v: None if 0 < v < 1 else "must be in (0, 1) Å"),
    "policy.strain_policy": (str, True,
                             lambda v: None if v in STRAIN_POLICIES else f"must be one of {STRAIN_POLICIES}"),
    "policy.d_cut": ((int, float), True, lambda v: None if 0 < v < 3 else "must be in (0, 3) Å"),
    "policy.grid.q_max": ((int, float), True, lambda v: None if v > 0 else "must be > 0"),
    "policy.grid.dq": ((int, float), True, lambda v: None if v > 0 else "must be > 0"),
    "policy.anchors": (list, False, None),
    "policy.basis_dmax_A": ((int, float), False, lambda v: None if v > 0 else "must be > 0"),
    "policy.remove_translation": (bool, False, None),
    "policy.single_mode_check_on": (str, False, lambda v: None if v in ("fixed_parent_lattice", "movie_frame")
                                     else "fixed_parent_lattice or movie_frame"),
    "faults": (dict, False, lambda v: None if set(v) <= {"inject_translation", "hide_stored_ids"}
               else f"unknown fault {sorted(set(v) - {'inject_translation', 'hide_stored_ids'})}"),
    "policy.fit.rmax": ((int, float), True, lambda v: None if v > 0 else "must be > 0"),
    "policy.fit.per_fu": (int, True, lambda v: None if v >= 1 else "must be >= 1"),
    "policy.fit.cv_folds": (int, True, lambda v: None if 2 <= v <= 50 else "must be in 2..50"),
    "policy.fit.max_rms_meV": ((int, float), True, lambda v: None if v > 0 else "must be > 0"),
    "policy.fit.max_cv_rms_meV": ((int, float), True, lambda v: None if v > 0 else "must be > 0"),
    "policy.fit.max_abs_res_meV": ((int, float), True, lambda v: None if v > 0 else "must be > 0"),
    "policy.fit.min_points_per_coef": (int, True, lambda v: None if v >= 1 else "must be >= 1"),
    "retry.max_per_node": (int, True, lambda v: None if 0 <= v <= 10 else "must be in 0..10"),
    "llm.enabled": (bool, True, None),
    "llm.api_key_env": (str, True,
                        lambda v: None if v in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "OPENAI_COMPAT_API_KEY", "none")
                        else "keys are read only from ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY or OPENAI_COMPAT_API_KEY"),
    "llm.provider": (str, False, lambda v: None if v in ("anthropic", "openai", "google", "fake") else "anthropic, openai, google or fake"),
    "llm.mode": (str, False, lambda v: None if v in ("constrained", "free") else "constrained or free"),
}


def _get(d: dict, dotted: str):
    cur = d
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            raise KeyError(dotted)
        cur = cur[k]
    return cur


def load(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).expanduser().read_text())


def validate(cfg: dict) -> list[str]:
    errs = []
    if not isinstance(cfg, dict):
        return ["config is not a mapping"]
    for key, (typ, required, check) in SCHEMA.items():
        try:
            v = _get(cfg, key)
        except KeyError:
            if required:
                errs.append(f"{key}: missing")
            continue
        if typ is int and isinstance(v, bool) or not isinstance(v, typ):
            errs.append(f"{key}: expected {typ}, got {type(v).__name__}")
            continue
        if check and (msg := check(v)):
            errs.append(f"{key}: {msg}")
    try:                                                  # live submission only in live mode, and live needs it on
        mode, allow = _get(cfg, "run.mode"), _get(cfg, "run.allow_live_submission")
        if allow and mode != "live":
            errs.append("run.allow_live_submission: live submission is disabled unless run.mode is live")
        if mode == "live" and allow is not True:
            errs.append("run.mode: live needs run.allow_live_submission: true")
        if mode == "live":
            for k in ("run.live.submit_cmd", "run.live.queue_cmd", "run.live.job_header", "run.live.vasp_cmd",
                      "run.live.potcar_dir", "run.live.incar"):
                try:
                    _get(cfg, k)
                except KeyError:
                    errs.append(f"{k}: missing (needed in live mode)")
        if mode == "live":
            lv = _get(cfg, "run.live") if isinstance(_get(cfg, "run.live"), dict) else {}
    except KeyError:
        pass
    if _has_secret(cfg):
        errs.append("an API key must not appear in the config file (set ANTHROPIC_API_KEY, OPENAI_API_KEY or GOOGLE_API_KEY in the environment)")
    return errs


def _has_secret(obj, key: str = "") -> bool:
    if isinstance(obj, dict):
        return any(_has_secret(v, k) for k, v in obj.items())
    if isinstance(obj, list):
        return any(_has_secret(v, key) for v in obj)
    if isinstance(obj, str):
        return obj.startswith(("sk-ant", "sk-proj-", "sk-", "AIza")) or (key.lower() in ("api_key", "apikey", "key", "token") and bool(obj))
    return False
