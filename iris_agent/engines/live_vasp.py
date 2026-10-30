"""Live VASP: write the inputs of every frame, read the outputs, and collect them in the layout the path nodes
already read (the same layout demo/hfo2/collect_paths.py wrote for the stored HfO2 paths):

  <stored>/L<kk>/POSCAR INCAR KPOINTS POTCAR      written before submission (POTCAR by the executor)
  <stored>/L<kk>/OSZICAR OUTCAR                   written by VASP
  <stored>/L<kk>/result.json                      written here after the job part ends
  <collected>/energies.csv                        one row per point (path, point, lambda, E0_eV, E0_per_fu_eV, dE_meV_per_fu, converged)
  <collected>/energies_summary.json               per path: barrier, its lambda, dE at the end

Convergence rule (OSZICAR, as collect_paths.py): the run finished (OUTCAR timing block present), the last
ionic step needed fewer than NELM electronic steps and its last |dE| < EDIFF. Nothing here decides a gate;
f4 and G4 do.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import numpy as np

FIN_MARK = "General timing and accounting"


# ---------------------------------------------------------------- inputs
def species_runs(species: list[str]) -> list[tuple[str, int]]:
    """Consecutive runs of the per-atom species list (POSCAR names/counts keep IRIS's atom order exactly)."""
    runs: list[tuple[str, int]] = []
    for s in species:
        if runs and runs[-1][0] == s:
            runs[-1] = (s, runs[-1][1] + 1)
        else:
            runs.append((s, 1))
    return runs


def poscar_text(title: str, lattice, species: list[str], frac) -> str:
    runs = species_runs(species)
    L = np.asarray(lattice, float)
    lines = [title, "   1.0"] + ["  " + " ".join(f"{x:20.12f}" for x in row) for row in L]
    lines += ["   " + "   ".join(s for s, _ in runs), "   " + "   ".join(str(n) for _, n in runs), "Direct"]
    lines += ["  " + " ".join(f"{x:20.14f}" for x in (np.asarray(r, float) % 1.0)) for r in frac]
    return "\n".join(lines) + "\n"


def incar_text(tags: dict, patch: dict | None = None) -> str:
    t = {**tags, **(patch or {})}
    return "".join(f"{k} = {_fmt(v)}\n" for k, v in t.items())


def _fmt(v):
    if isinstance(v, bool):
        return ".TRUE." if v else ".FALSE."
    return str(v)


def kpoints_text(mesh: list[int]) -> str:
    return f"Monkhorst-Pack {mesh[0]}x{mesh[1]}x{mesh[2]}\n0\nMonkhorst-Pack\n{mesh[0]} {mesh[1]} {mesh[2]}\n0 0 0\n"


def potcar_text(species: list[str], potcar_dir: str | Path, labels: dict | None = None) -> tuple[str, list[str]]:
    """POTCAR in POSCAR species order = the author's writePotcar: cat <potcar_dir>/<Element>/POTCAR (labels optional).
    Returns (text, TITEL lines)."""
    labels = labels or {}
    out, titles = [], []
    for s, _ in species_runs(species):
        p = Path(potcar_dir).expanduser() / labels.get(s, s) / "POTCAR"
        txt = p.read_text()
        out.append(txt)
        titles += [ln.split("=", 1)[1].strip() for ln in txt.splitlines() if "TITEL" in ln]
    return "".join(out), titles


# ---------------------------------------------------------------- outputs
def _incar_value(text: str, key: str, default=None):
    for ln in text.splitlines():
        m = re.match(rf"\s*{key}\s*=\s*([^\s!#]+)", ln, re.I)
        if m:
            return m.group(1)
    return default


def read_point(d: Path) -> dict:
    """Read one finished (or failed) VASP folder. Never raises on missing files."""
    d = Path(d)
    incar = (d / "INCAR").read_text() if (d / "INCAR").is_file() else ""
    ediff = float(_incar_value(incar, "EDIFF", "1E-4"))
    nelm = int(_incar_value(incar, "NELM", "60"))
    r = {"finished": False, "converged": False, "E0_eV": None, "F_eV": None, "mag": 0.0, "mag_outcar": 0.0,
         "scf_steps": None, "last_dE": None, "EDIFF": ediff, "NELM": nelm, "potcar": None, "flags": []}
    if (d / "POTCAR").is_file():
        r["potcar"] = [ln.split("=", 1)[1].strip() for ln in (d / "POTCAR").read_text().splitlines() if "TITEL" in ln]
    osz = (d / "OSZICAR").read_text() if (d / "OSZICAR").is_file() else ""
    out = (d / "OUTCAR").read_text(errors="replace") if (d / "OUTCAR").is_file() else ""
    r["finished"] = FIN_MARK in out
    steps, last = [], None
    for ln in osz.splitlines():
        m = re.match(r"\s*(DAV|RMM|CG|SDA):\s+(\d+)\s+(\S+)\s+(\S+)", ln)
        if m:
            steps.append((int(m.group(2)), abs(float(m.group(4)))))
        m = re.search(r"F=\s*(\S+)\s+E0=\s*(\S+)", ln)
        if m:
            r["F_eV"], r["E0_eV"] = float(m.group(1)), float(m.group(2))
            last = list(steps)
            steps = []
            mm = re.search(r"mag=\s*(\S+)", ln)
            r["mag"] = float(mm.group(1)) if mm else 0.0
    if last:
        r["scf_steps"], r["last_dE"] = last[-1][0], last[-1][1]
    elif steps:                                   # electronic loop never closed (killed or NELM hit)
        r["scf_steps"], r["last_dE"] = steps[-1][0], steps[-1][1]
    # ISPIN = 1: "number of electron  40.0000000 magnetization" (nothing after); ISPIN = 2: "... magnetization  0.0000003"
    mo = [m for m in re.findall(r"number of electron\s+\S+\s+magnetization[ \t]*([-+0-9.Ee]+)?[ \t]*\n", out) if m]
    if mo:
        r["mag_outcar"] = float(mo[-1])
    r["converged"] = bool(r["finished"] and r["E0_eV"] is not None and r["scf_steps"] is not None
                          and r["scf_steps"] < nelm and r["last_dE"] < ediff)
    if r["finished"] and r["scf_steps"] is not None and r["scf_steps"] >= nelm:
        r["flags"].append("NELM")
    if not r["finished"]:
        r["flags"].append("NOT_FINISHED")
    return r


def failure_code(results: list[dict], job_vanished_without_done: bool) -> str | None:
    """Part-level code from its frames, in the vocabulary of engines/jobs.FAILURE_CODES."""
    if job_vanished_without_done:
        return "WALLTIME"
    if any("NELM" in r.get("flags", []) for r in results):
        return "NELM"
    if any(not r.get("finished") for r in results):
        return "UNKNOWN"
    return None


# ---------------------------------------------------------------- collection
def collect_path(stored: Path, collected: Path, frames: list[dict], per_fu: int, sg_of) -> dict:
    """(Re)write result.json for every point that has outputs, energies.csv and energies_summary.json.

    frames: f2's frames (id, name, lambda); sg_of(point_dir) -> space group number of its POSCAR (f2's symprec).
    dE is relative to the first frame (L00 / P00, Q = 0) and is written only once it has a converged energy."""
    stored, collected = Path(stored), Path(collected)
    collected.mkdir(parents=True, exist_ok=True)
    pid = stored.name
    res = {}
    for fr in frames:
        d = stored / fr["name"]
        if not (d / "OSZICAR").is_file() and not (d / "OUTCAR").is_file():
            continue
        r = read_point(d)
        r["lambda"] = fr.get("lambda")
        if fr.get("Q") is not None:
            r["Q"] = fr["Q"]
        r["space_group"] = sg_of(d)
        res[fr["name"]] = r
    origin = frames[0]["name"]                                     # L00 (path) / P00 (plane): the Q = 0 frame
    e0 = res.get(origin, {}).get("E0_eV") if res.get(origin, {}).get("converged") else None
    rows = []
    for fr in frames:
        r = res.get(fr["name"])
        if r is None:
            continue
        r["E0_per_fu_eV"] = None if r["E0_eV"] is None else r["E0_eV"] / per_fu     # full precision: f5/f6 compare at 1e-9 eV
        r["dE_meV_per_fu"] = (None if (e0 is None or r["E0_eV"] is None)
                              else round(1000 * (r["E0_eV"] - e0) / per_fu, 3))
        (stored / fr["name"] / "result.json").write_text(json.dumps(r, indent=1))
        if r["converged"] and r["dE_meV_per_fu"] is not None:
            rows.append({"path": pid, "point": fr["name"], "lambda": "" if fr.get("lambda") is None else fr["lambda"], "E0_eV": f"{r['E0_eV']:.8f}",
                         "E0_per_fu_eV": f"{r['E0_eV'] / per_fu:.12f}",
                         "dE_meV_per_fu": f"{r['dE_meV_per_fu']:.3f}", "converged": "True"})
    # merge with rows of other paths already in the CSV
    csv_path = collected / "energies.csv"
    other = []
    if csv_path.is_file():
        with open(csv_path) as fh:
            other = [x for x in csv.DictReader(fh) if x["path"] != pid]
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["path", "point", "lambda", "E0_eV", "E0_per_fu_eV", "dE_meV_per_fu", "converged"])
        w.writeheader()
        for x in other + rows:
            w.writerow(x)
    sp = collected / "energies_summary.json"
    summ = json.loads(sp.read_text()) if sp.is_file() else {"paths": {}}
    if rows and len(rows) == len(frames):
        dE = [float(x["dE_meV_per_fu"]) for x in rows]
        k, kmin = int(np.argmax(dE)), int(np.argmin(dE))
        summ["paths"][pid] = {"barrier_meV_per_fu": round(dE[k], 3), "barrier_at_lambda": rows[k]["lambda"],
                              "dE_end_meV_per_fu": round(dE[-1], 3), "n_points": len(rows),
                              "min_meV_per_fu": round(dE[kmin], 3), "min_point": rows[kmin]["point"]}
    sp.write_text(json.dumps(summ, indent=1))
    return {"n_read": len(res), "n_converged_rows": len(rows), "results": res}
