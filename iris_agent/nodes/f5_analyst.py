"""f5 Analyst: Landau fit of the plane, cross-validation, ring of minima, barriers.

Runs the existing demo/staged_walkthrough/fit_landau_plane.py UNCHANGED, as a subprocess, on a
run-dir layout written inside IRIS_AGENT (test_runs/<thread>/f5_fit/): grid_spec.json and
grid_manifest.json come from the frames f2 built (ap_A = Q), energies.csv from f4. The script then
writes its landau_fit_plane.json there too, never into the repo.

Added here (not in the script): k-fold cross-validation of the same model on the same fit set.
"""
from __future__ import annotations

from ._layout import dropped_frames

import csv
import json
import os
import re
import subprocess
import sys

import numpy as np

from ..engines import legacy
from ..paths import from_config

NAMES = ["a1", "b1", "c1", "a2", "b2", "c2", "λ", "μ"]


def design(A, B):
    """F(A,B) = a1/2 A² + b1/4 A⁴ + c1/6 A⁶ + a2/2 B² + b2/4 B⁴ + c2/6 B⁶ + λ/2 A²B² + μ/6 (A⁴B² + A²B⁴)."""
    return np.column_stack([A**2 / 2, A**4 / 4, A**6 / 6, B**2 / 2, B**4 / 4, B**6 / 6,
                            A**2 * B**2 / 2, (A**4 * B**2 + A**2 * B**4) / 6])


def fit_set(grid, energies, rmax, per_fu):
    """The script's fit set: non-anchor frames with energies, E relative to the origin, r <= rmax."""
    modes = grid["active"]
    E = energies["eV_per_cell"]
    pts = [f for f in grid["frames"] if str(f["id"]) in E and not f["tag"].startswith(("anchor_", "d4_"))]
    p0 = min(pts, key=lambda f: sum(f["Q"][m] ** 2 for m in modes))
    A = np.array([f["Q"][modes[0]] for f in pts])
    B = np.array([f["Q"][modes[1]] for f in pts])
    y = np.array([(E[str(f["id"])] - E[str(p0["id"])]) / per_fu for f in pts])
    keep = np.hypot(A, B) <= rmax
    return A[keep], B[keep], y[keep], [f["id"] for f, k in zip(pts, keep) if k]


def kfold_cv(A, B, y, k):
    X = design(A, B)
    idx = np.arange(len(y)) % k                      # deterministic folds
    res = np.empty_like(y)
    for f in range(k):
        tr, te = idx != f, idx == f
        c, *_ = np.linalg.lstsq(X[tr], y[tr], rcond=None)
        res[te] = y[te] - X[te] @ c
    return float(np.sqrt(np.mean(res**2)) * 1000), float(np.abs(res).max() * 1000)


def f5_analyst(state: dict) -> dict:
    if state["config"]["policy"].get("analysis", "landau_plane") == "surface":
        from .f5_surface import f5_surface
        return f5_surface(state)
    if state["config"]["policy"].get("analysis") == "path":
        from .f5_path import f5_path
        return f5_path(state)
    if state["config"]["policy"].get("analysis") == "plane2":
        from .f5_plane2 import f5_plane2
        return f5_plane2(state)
    if state["config"]["policy"].get("analysis") == "landau6d":
        from .f5_landau6d import f5_landau6d
        return f5_landau6d(state)
    if state["config"]["policy"].get("analysis") == "meier_joint":
        from .f5_joint import f5_joint
        return f5_joint(state)
    if state["config"]["policy"].get("analysis") == "meier_QP":
        from .f5_meier import f5_meier
        return f5_meier(state)
    cfg, grid, en = state["config"], state["grid"], state["energies"]
    P, fit = from_config(cfg), cfg["policy"]["fit"]
    over = state.get("overrides", {}).get("f5", {})
    modes = grid["active"]
    if len(modes) != 2:
        return {"model": {"fitted": False, "reason": f"plane fit needs 2 active modes, got {modes}"},
                "last_node": "f5"}
    tag = "plane"
    wd = P.out(P.run_dir(cfg["thread_id"]), "f5_fit")
    step = P.out(wd, f"step4_energy_{tag}")
    step.mkdir(parents=True, exist_ok=True)
    child_Ap = {m: abs(state["decomposition"]["irreps"][m]["Ap"]) for m in modes}
    P.out(step, "grid_spec.json").write_text(json.dumps({"modes": modes, "units": "Ap_A", "child_Ap": child_Ap}))
    P.out(step, "grid_manifest.json").write_text(json.dumps(
        [{"id": f["id"], "ap_A": f["Q"], "tag": f["tag"]} for f in grid["frames"] if not f["tag"].startswith("d4_")]))
    ecsv = P.out(wd, "energies.csv")
    with open(ecsv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "energy_eV"])
        for i, e in en["eV_per_cell"].items():
            w.writerow([i, f"{e:.6f}"])
    rmax = float(over.get("rmax", fit["rmax"]))
    cmd = [sys.executable, "-I", str(legacy.script(P, "fit_landau_plane.py")), str(wd), "--tag", tag,
           "--energies", str(ecsv), "--per-fu", str(fit["per_fu"]), "--rmax", str(rmax)]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "MPLBACKEND": "Agg"}
    pr = subprocess.run(cmd, capture_output=True, text=True, cwd=str(wd), env=env, timeout=600)
    P.out(wd, "fit_landau_plane.stdout.txt").write_text(pr.stdout + pr.stderr)
    if pr.returncode != 0:
        return {"model": {"fitted": False, "reason": "fit_landau_plane.py failed", "stderr": pr.stderr[-2000:]},
                "last_node": "f5"}
    res = json.loads(P.out(wd, f"step5_analysis_{tag}", "landau_fit_plane.json").read_text())
    so = pr.stdout
    n_fit = int(re.search(r"fit to (\d+) points", so).group(1))
    rms, maxres = map(float, re.search(r"RMS residual ([\d.]+) meV/f.u., max \|res\| ([\d.]+)", so).groups())
    r_lo, r_hi = map(float, re.search(r"radius ([\d.]+)–([\d.]+) Å", so).groups())

    # DFT-grid ring (no fit): existing ring_profile.py, bilinear interpolation of the grid energies
    cmd2 = [sys.executable, "-I", str(legacy.script(P, "ring_profile.py")), str(wd), "--tag", tag,
             "--energies", str(ecsv), "--per-fu", str(fit["per_fu"]), "--out", str(P.out(wd, "ring_profile.png"))]
    pr2 = subprocess.run(cmd2, capture_output=True, text=True, cwd=str(wd), env=env, timeout=600)
    P.out(wd, "ring_profile.stdout.txt").write_text(pr2.stdout + pr2.stderr)
    ring_grid = {"ok": pr2.returncode == 0}
    if pr2.returncode == 0:
        o = pr2.stdout
        ring_grid.update({
            "ring_radius_A": float(re.search(r"ring at r = ([\d.]+) Å", o).group(1)),
            "corrugation_meV": float(re.search(r"corrugation \(max−min around ring\) = ([\d.]+) meV", o).group(1)),
            "radial_min_radius_A": list(map(float, re.search(r"radial-minimum radius: ([\d.]+)–([\d.]+) Å", o).groups())),
            "valley_floor_meV": list(map(float, re.search(r"valley floor ([+-][\d.]+) … ([+-][\d.]+)", o).groups())),
            "script": "demo/staged_walkthrough/ring_profile.py (unchanged)"})

    A, B, y, ids = fit_set(grid, en, rmax, fit["per_fu"])
    cv_rms, cv_max = kfold_cv(A, B, y, fit["cv_folds"])
    model = {"fitted": True, "script": "demo/staged_walkthrough/fit_landau_plane.py (unchanged)", "dropped_frames": dropped_frames(state),
             "command": " ".join(cmd[2:]), "modes": modes, "rmax_A": rmax, "per_fu": fit["per_fu"],
             "n_fit": n_fit, "n_fit_ids": len(ids), "coefficients": res["coefficients"],
             "units": {"a": "eV Å⁻²", "b": "eV Å⁻⁴", "c": "eV Å⁻⁶", "λ": "eV Å⁻⁴", "μ": "eV Å⁻⁶"},
             "rms_meV": res["rms_meV"], "max_abs_res_meV": maxres,
             "cv": {"folds": fit["cv_folds"], "rms_meV": cv_rms, "max_abs_meV": cv_max},
             "ring": {"radius_min_A": r_lo, "radius_max_A": r_hi, "radius_mean_A": res["brim_radius_A"],
                      "depth_meV": res["crown_height_meV"], "corrugation_meV": res["corrugation_meV"],
                      "cos2_meV": res["cos2_meV"], "cos4_meV": res["cos4_meV"]},
             "ring_dft_grid": ring_grid,
             "barriers_meV": {"around_ring": res["corrugation_meV"], "through_parent": res["crown_height_meV"]},
             "grid_dq_A": cfg["policy"]["grid"]["dq"],
             "files": {"json": str(P.out(wd, f"step5_analysis_{tag}", "landau_fit_plane.json")),
                       "stdout": str(P.out(wd, "fit_landau_plane.stdout.txt"))}}
    from .f5_d4 import d4_analysis
    d4 = d4_analysis(state, model)
    if d4:
        d4["accepted"] = bool(over.get("d4_accept"))
        model["d4"] = d4
    return {"model": model, "last_node": "f5"}
