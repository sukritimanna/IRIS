"""f5 Analyst, analysis kind "surface" (policy.analysis: surface): the DFT energy surface of a 2-mode
plane read directly, without a Landau fit (Ca3Ti2O7: the manuscript reports the surface itself).

Runs the existing plotting script (paths.surface_script, e.g. demo/ca3ti2o7/plot_ca3ti2o7_plane.py)
UNCHANGED, as a subprocess, on a layout written inside IRIS_AGENT (test_runs/<thread>/f5_surface/):
grid_spec.json, grid_manifest.json (ap_A = Q, tag "plane" for grid nodes), e_<irrep>.txt (Cartesian
vector per Å of Q) and energies.csv (f4). Its stdout gives the mirror check and the phase energies.

Computed here as well (f6 re-derives every number by another route):
  E_min and the grid minima (A_p, and A_s = A_p * sqrt(s)), E range, edge distance of the minimum,
  energies at the phase points (anchors: DFT; the true child at its A_p: bilinear between nodes),
  mirror asymmetry max |E(x,y) - E(-x,y)|, max |E(x,y) - E(x,-y)|.
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

from ..paths import from_config


def plane_table(grid, energies):
    """xs, ys, Z (eV per cell; NaN where a node has no energy) for the non-anchor frames."""
    m0, m1 = grid["active"]
    E = energies["eV_per_cell"]
    pts = [f for f in grid["frames"] if not f["tag"]]
    xs = sorted({round(f["Q"][m0], 10) for f in pts})
    ys = sorted({round(f["Q"][m1], 10) for f in pts})
    Z = np.full((len(xs), len(ys)), np.nan)
    for f in pts:
        if str(f["id"]) in E:
            Z[xs.index(round(f["Q"][m0], 10)), ys.index(round(f["Q"][m1], 10))] = E[str(f["id"])]
    return np.array(xs), np.array(ys), Z


def bilinear(xs, ys, Z, x, y):
    i = int(np.clip(np.searchsorted(xs, x) - 1, 0, len(xs) - 2))
    j = int(np.clip(np.searchsorted(ys, y) - 1, 0, len(ys) - 2))
    tx, ty = (x - xs[i]) / (xs[i + 1] - xs[i]), (y - ys[j]) / (ys[j + 1] - ys[j])
    return float((1 - tx) * (1 - ty) * Z[i, j] + tx * (1 - ty) * Z[i + 1, j]
                 + (1 - tx) * ty * Z[i, j + 1] + tx * ty * Z[i + 1, j + 1])


def f5_surface(state: dict) -> dict:
    cfg, grid, en, dec = state["config"], state["grid"], state["energies"], state["decomposition"]
    P, pol = from_config(cfg), cfg["policy"]
    modes = grid["active"]
    if len(modes) != 2:
        return {"model": {"fitted": False, "kind": "surface", "reason": f"surface needs 2 active modes, got {modes}"},
                "last_node": "f5"}
    m0, m1 = modes
    per_fu = pol["fit"]["per_fu"]
    k = 1000.0 / per_fu
    E = en["eV_per_cell"]
    xs, ys, Z = plane_table(grid, en)
    anchors = {f["tag"][len("anchor_"):]: f for f in grid["frames"] if f["tag"].startswith("anchor_")}
    e_anchor = {n: E.get(str(f["id"])) for n, f in anchors.items()}
    e_min = float(min([np.nanmin(Z)] + [v for v in e_anchor.values() if v is not None]))
    Zm = (Z - e_min) * k
    zmin = float(np.nanmin(Zm))
    ii = np.argwhere(np.isclose(Zm, zmin, atol=1e-9))
    minima = [{"Ap": [float(xs[i]), float(ys[j])]} for i, j in ii]
    # the parent mirrors map the minimum onto (±x, ±y); list those images with their DFT energies
    i_, j_ = ii[0]
    images = sorted({(int(a), int(b)) for a in (i_, len(xs) - 1 - i_) for b in (j_, len(ys) - 1 - j_)})
    equivalent = [{"Ap": [float(xs[a]), float(ys[b])], "E_meV": float(Zm[a, b])} for a, b in images]
    s = float(dec["isodistort"]["s"])
    for mn in minima:
        mn["As"] = [round(v * np.sqrt(s), 6) for v in mn["Ap"]]
    dq = float(xs[1] - xs[0])
    edge = min(min(xs[-1] - abs(mn["Ap"][0]), ys[-1] - abs(mn["Ap"][1])) for mn in minima) / dq

    def mirror(axis):
        Zf = Zm[::-1, :] if axis == 0 else Zm[:, ::-1]
        return float(np.nanmax(np.abs(Zm - Zf)))

    # phase points: parent at Q = 0, the anchors (DFT), the true child (bilinear between nodes)
    i0, j0 = int(np.argmin(np.abs(xs))), int(np.argmin(np.abs(ys)))
    child = {m: abs(dec["irreps"][m]["Ap"]) for m in modes}
    phases = {"parent": {"Q": [0.0, 0.0], "E_meV": float(Zm[i0, j0]), "source": "DFT node"}}
    for n, f in anchors.items():
        v = e_anchor[n]
        phases[n] = {"Q": [f["Q"][m0], f["Q"][m1]], "E_meV": None if v is None else (v - e_min) * k,
                     "source": "DFT anchor", "frame": f["id"]}
    phases["child"] = {"Q": [child[m0], child[m1]], "E_meV": bilinear(xs, ys, Zm, child[m0], child[m1]),
                       "source": "bilinear between DFT nodes (true child A_p)"}

    # ---- the existing script, unchanged, on a layout inside IRIS_AGENT ---------------------------
    wd = P.out(P.run_dir(cfg["thread_id"]), "f5_surface")
    gdir = P.out(wd, "grid")
    gdir.mkdir(parents=True, exist_ok=True)
    a21 = anchors.get("a21am")
    spec_child = {m0: a21["Q"][m0], m1: a21["Q"][m1]} if a21 else child
    P.out(gdir, "grid_spec.json").write_text(json.dumps(
        {"modes": modes, "units": "Ap_A", "child_Ap": spec_child, "per_fu": per_fu, "quadrant": False,
         "note": "written by IRIS f5; child_Ap = the A2_1am anchor the script labels"}))
    P.out(gdir, "grid_manifest.json").write_text(json.dumps(
        [{"id": f["id"], "ap_A": f["Q"], "tag": f["tag"] or "plane", "status": "pending"} for f in grid["frames"]]))
    L = np.array(dec["vectors"]["r0"]["lattice"])
    for m in modes:
        np.savetxt(P.out(gdir, f"e_{m}.txt"), np.array(grid["vectors"][m]) @ L)
    ecsv = P.out(wd, "energies.csv")
    with open(ecsv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "energy_eV"])
        for i, e in E.items():
            w.writerow([i, f"{e:.8f}"])
    script = P.repo("surface_script")
    cmd = [sys.executable, "-I", str(script), "--grid", str(gdir), "--energies", str(ecsv),
           "--per-fu", str(per_fu), "--rmax", str(float(xs[-1])), "--out", str(P.out(wd, "surface"))]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "MPLBACKEND": "Agg"}
    pr = subprocess.run(cmd, capture_output=True, text=True, cwd=str(wd), env=env, timeout=600)
    P.out(wd, "surface_script.stdout.txt").write_text(pr.stdout + pr.stderr)
    scr = {"ok": pr.returncode == 0, "script": str(script.relative_to(P.repo_root)) + " (unchanged)"}
    if pr.returncode == 0:
        o = pr.stdout
        mx = re.search(r"max\|E\(x,y\)-E\(-x,y\)\| = ([\d.]+), max\|E\(x,y\)-E\(x,-y\)\| = ([\d.]+)", o)
        ph = re.search(r"I4/mmm ([-\d.]+) \| Cmcm ([-\d.]+) \((\w+)\) \| Cmce ([-\d.]+) \((\w+)\) \| A2_1am ([-\d.]+) \((\w+)\)", o)
        gm = re.search(r"grid minimum at \(([+-][\d.]+), ([+-][\d.]+)\)", o)
        scr.update({"mirror_x_meV": float(mx.group(1)), "mirror_y_meV": float(mx.group(2)),
                    "parent_meV": float(ph.group(1)), "cmcm_meV": float(ph.group(2)), "cmce_meV": float(ph.group(4)),
                    "a21am_meV": float(ph.group(6)), "sources": [ph.group(3), ph.group(5), ph.group(7)],
                    "grid_minimum_Ap": [float(gm.group(1)), float(gm.group(2))],
                    "figure": str(P.out(wd, "surface.png")), "plane_csv": str(P.out(wd, "surface_plane.csv"))})
    else:
        scr["stderr"] = pr.stderr[-2000:]

    n_nodes = int(np.isfinite(Z).sum())
    model = {"fitted": True, "dropped_frames": dropped_frames(state), "kind": "surface", "modes": modes, "per_fu": per_fu,
             "units": {"Q": "Å of A_p (calibrated, translation-free)", "E": "meV/f.u. above E_min"},
             "grid_dq_A": dq, "q_max_A": float(xs[-1]), "n_nodes": n_nodes, "n_nodes_expected": Z.size,
             "E_min_eV_per_cell": e_min, "E_min_source": "lowest plane node or anchor (as the script)",
             "range_meV": float(np.nanmax(Zm)), "minimum_meV": zmin, "minima": minima,
             "minimum_mirror_images": equivalent,
             "minimum_edge_distance_steps": float(edge),
             "mirror_meV": {"x": mirror(0), "y": mirror(1)}, "phases": phases, "s": s, "script": scr,
             "files": {"dir": str(wd)}}
    return {"model": model, "last_node": "f5"}
