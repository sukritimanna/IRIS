"""Replay for the six-component grid (BiFeO3 stage B3). No DFT, VASP, MACE or Slurm, ever.

Each frame f2 planned (main orbits, controls, refine planes, extra points) is matched to its stored run folder
inside the campaign packages (paths.grid_packages):
  - the stored POSCAR must have the frame's lattice (1e-6 Å), species order and every atom within tol_A of the
    position IRIS builds from its own vectors (periodic, minimum image);
  - independently, the stored displacement is projected back onto IRIS's six vectors: the recovered q must equal
    the planned label (tol_A) and the part outside the six-vector span must vanish.
Settings: INCAR as its sorted set of tag = value lines, KPOINTS without its comment line (as engines/replay).
Energies, gradients and QC are linked from the collected CSVs (paths.collected_dir, runs_<dataset>.csv).
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import numpy as np


def parse_poscar(text: str):
    ln = text.splitlines()
    s = float(ln[1].split()[0])
    lat = np.array([[float(x) for x in ln[i].split()[:3]] for i in (2, 3, 4)]) * s
    names, counts = ln[5].split(), [int(x) for x in ln[6].split()]
    spec = [n for n, c in zip(names, counts) for _ in range(c)]
    k = 7
    if ln[k].strip()[:1].lower() == "s":
        k += 1
    cart = ln[k].strip()[:1].lower() in ("c", "k")
    X = np.array([[float(x) for x in ln[k + 1 + i].split()[:3]] for i in range(len(spec))])
    if not cart:
        X = X @ lat
    elif s != 1.0:
        X = X * s
    return lat, spec, X


def settings_hash(incar: str | None, kpoints: str | None) -> dict:
    out = {}
    if incar is not None:
        tags = sorted(" = ".join(x.strip().upper() for x in ln.split("#")[0].split("=", 1))
                      for ln in incar.splitlines() if "=" in ln.split("#")[0])
        out["INCAR"] = hashlib.sha256("\n".join(tags).encode()).hexdigest()[:16]
    if kpoints is not None:
        body = [" ".join(ln.split()) for ln in kpoints.splitlines()[1:] if ln.strip()]
        out["KPOINTS"] = hashlib.sha256("\n".join(body).encode()).hexdigest()[:16]
    return out


def compare(cell, q, lat, spec, X) -> dict:
    """Stored POSCAR vs the frame IRIS builds (Cell from nodes/f2_grid6)."""
    if spec != cell.spec:
        return {"ok": False, "why": "species order"}
    dl = float(np.abs(lat - cell.lat).max())
    if dl > 1e-6:
        return {"ok": False, "why": f"lattice differs by {dl:.2e} Å"}
    inv = np.linalg.inv(cell.lat)
    built = cell.cart(q)
    d = (X - built) @ inv
    d = (d - np.round(d)) @ cell.lat
    dev = float(np.linalg.norm(d, axis=1).max())
    u = (X - cell.cart0) @ inv
    u = (u - np.round(u)) @ cell.lat                       # stored displacement from the cubic cell
    V = cell.V.reshape(6, -1)
    nrm = (V * V).sum(1)
    qs = V @ u.ravel() / nrm
    rest = u.ravel() - qs @ V
    return {"ok": True, "dev_A": dev, "q_recovered": qs.tolist(), "dq_A": float(np.abs(qs - np.asarray(q)).max()),
            "outside_span_A": float(np.abs(rest).max())}


def run_name(frame: dict) -> tuple[str, str]:
    """(stored folder relative to the dataset, CSV run name) of a planned frame."""
    ds, name = frame["id"].split(":", 1)
    if frame["role"] == "production":
        return f"points/{name}", f"points/{name}"
    if frame["role"] == "control_img":
        return f"controls/{name}", f"controls/{name}"
    return name, name


def read_collected(path: Path) -> dict:
    with open(path) as fh:
        return {r["run"]: r for r in csv.DictReader(fh)}


GRAD_KEYS = [f"dEdq_{k}_meV_per_A_fu" for k in ("P1", "P2", "P3", "R1", "R2", "R3")]
Q_KEYS = [f"q_{k}" for k in ("P1", "P2", "P3", "R1", "R2", "R3")]


def truthy(x) -> bool:
    return str(x).strip().lower() in ("true", "1", "yes")


def fnum(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None
