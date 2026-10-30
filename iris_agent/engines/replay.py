"""Replay engine for f3. No DFT, VASP, MACE or Slurm, ever.

The stored campaign is a reference grid directory (step4_energy_<tag>/ with grid_manifest.json and
03_grid/NNNN/point_XXXXX/{POSCAR, INCAR, KPOINTS, point_info.json}) plus an energies CSV (id,energy_eV).
Each frame f2 builds is matched to a stored computed structure by its coordinates (species order,
lattice and every fractional coordinate within tolerance, after one fixed atom permutation found at
Q = 0); on a match the stored energy is linked. Frames without a match are flagged "unmatched" and
never computed.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np


class LiveSubmissionDisabled(RuntimeError):
    """Raised by any attempt to submit real jobs. run.allow_live_submission must stay false."""


def submit(*_a, **_k):
    raise LiveSubmissionDisabled("no DFT/VASP/MACE/Slurm submissions in this build")


class ReferenceGrid:
    def __init__(self, grid_dir: str | Path, energies_csv: str | Path | None = None, poscar_dirs=None):
        """poscar_dirs: [(03_grid dir, id offset), ...] when the manifest merges several stored grids
        (ErMnO3 planepax = plane ids 0-224 + paxis ids 0-10 as 225-235); default <grid_dir>/03_grid."""
        self.dir = Path(grid_dir)
        self.manifest = json.loads((self.dir / "grid_manifest.json").read_text())
        self.spec = json.loads((self.dir / "grid_spec.json").read_text())
        self._poscars = {}
        for d, off in (poscar_dirs or [(self.dir / "03_grid", 0)]):
            for p in Path(d).glob("*/point_*/POSCAR"):
                self._poscars[int(p.parent.name.split("_")[1]) + int(off)] = p.parent
        self.energies = {}
        if energies_csv and Path(energies_csv).is_file():
            with open(energies_csv) as fh:
                self.energies = {int(r["id"]): float(r["energy_eV"]) for r in csv.DictReader(fh)}

    def point_dir(self, pid: int) -> Path:
        return self._poscars[pid]

    def structure(self, pid: int):
        from pymatgen.core import Structure
        return Structure.from_file(str(self.point_dir(pid) / "POSCAR"))

    def origin_id(self) -> int:
        return next(m["id"] for m in self.manifest
                    if all(abs(v) < 1e-12 for v in m["q"].values()) and not m["tag"].startswith("anchor"))

    def labels(self, pid: int) -> dict:
        return next(m for m in self.manifest if m["id"] == pid)["ap_A"]

    def input_hashes(self, pid: int) -> dict:
        """Hashes of the DFT settings, not of the bytes: INCAR as its sorted set of tag = value lines
        (order and spacing ignored), KPOINTS without its free-text first line (ErMnO3: the paxis points have
        "GGA = CA" on another line and the comment "Gamma" instead of "Gamma 6x6x2", same settings)."""
        d = self.point_dir(pid)
        out = {}
        if (d / "INCAR").is_file():
            tags = sorted(" = ".join(x.strip().upper() for x in ln.split("#")[0].split("=", 1))
                          for ln in (d / "INCAR").read_text().splitlines() if "=" in ln.split("#")[0])
            out["INCAR"] = hashlib.sha256("\n".join(tags).encode()).hexdigest()[:16]
        if (d / "KPOINTS").is_file():
            body = [" ".join(ln.split()) for ln in (d / "KPOINTS").read_text().splitlines()[1:] if ln.strip()]
            out["KPOINTS"] = hashlib.sha256("\n".join(body).encode()).hexdigest()[:16]
        return out


class Matcher:
    """Match built frames to stored frames.

    Candidates are the stored frames whose axis labels (times `label_scale`) lie within `label_window`
    of the built frame's Q (labels only narrow the search); the match itself is decided by the structure: same lattice,
    same species on every site, every fractional coordinate within `tol_frac`, after one fixed atom
    permutation found from the Q = 0 frame.
    """

    def __init__(self, ref: ReferenceGrid, r0, modes: list[str], tol_frac: float = 1e-4,
                 tol_lattice_A: float = 1e-4, label_window: float = 0.01, hidden_ids=(), label_scale: float = 1.0,
                 modulo_translation: bool = False, label_keys: list | None = None):
        """label_keys: stored-manifest keys giving the labels in the order of `modes` (default ap_A[mode]);
        e.g. a polar hat grid: ["Q_A", "P_A", "theta_deg"] for modes [K3, GM2-, phi]."""
        from .stored_isodistort import match_atoms
        self.ref, self.modes, self.tol, self.tol_lat, self.win = ref, modes, tol_frac, tol_lattice_A, label_window
        try:
            s0 = ref.structure(ref.origin_id())
            is_origin = True
        except (StopIteration, KeyError):          # no Q = 0 frame (polar hat grid): smallest displacement
            key = (label_keys or ["Q_A"])[0]
            s0 = ref.structure(min(ref.manifest, key=lambda m: abs(m.get(key, 0.0)))["id"])
            is_origin = False
        self.perm = match_atoms(r0, s0)            # stored index for each built atom
        if sorted(self.perm) != list(range(len(r0))):
            raise ValueError("reference frame does not map one-to-one onto the built atoms")
        d = s0.frac_coords[self.perm] - r0.frac_coords
        self.origin_dev = float(np.abs(d - np.round(d)).max()) if is_origin else None
        keep = [m for m in ref.manifest if m["id"] not in set(hidden_ids)]   # fault injection: missing data
        self.ids = [m["id"] for m in keep]
        # stored axis labels -> this run's Q units (Ca3Ti2O7 xplane: labels are A_s, Q is A_p: x 1/sqrt 2).
        # Labels only pick candidates; the structure comparison decides the match.
        self.label_scale = float(label_scale)
        # modulo_translation: compare after removing the mean displacement (a rigid shift of every atom does
        # not change the energy). Used where the stored frames still carry an old polar-mode translation
        # (InMnO3 plane_v2: GM2- built before the polar-origin fix). The removed shift is returned.
        self.modulo_translation = bool(modulo_translation)
        self.last_shift_A = 0.0
        if label_keys:                          # "a.b" = nested key (D4 scans: "ap_A.X5+")
            def get(m, k):
                for part in k.split("."):
                    m = m[part]
                return float(m)
            self.labels = np.array([[get(m, k) for k in label_keys] for m in keep])
        else:
            self.labels = np.array([[m["ap_A"].get(k, 0.0) for k in modes] for m in keep]) * self.label_scale
        self._cache = {}

    def _stored(self, pid):
        if pid not in self._cache:
            s = self.ref.structure(pid)
            self._cache[pid] = (s.lattice.matrix, [str(x) for x in s.species], s.frac_coords)
        return self._cache[pid]

    def match(self, built, Q: dict, exclude=()) -> tuple[int | None, float | None]:
        """(stored id, max |Δfrac|) of the stored frame equal to `built`; (None, best dev) if none."""
        q = np.array([Q.get(k, 0.0) for k in self.modes])
        near = np.where(np.abs(self.labels - q).max(axis=1) <= self.win)[0]
        best_dev, best_id = None, None
        for j in near:
            pid = self.ids[j]
            if pid in exclude:                     # already linked to another frame (duplicate stored points)
                continue
            lat, sp, frac = self._stored(pid)
            if np.abs(lat - built.lattice.matrix).max() > self.tol_lat:
                continue
            if any(sp[self.perm[a]] != str(built.species[a]) for a in range(len(built))):
                continue
            d = frac[self.perm] - built.frac_coords
            d = d - np.round(d)
            shift = 0.0
            if self.modulo_translation:
                t = d.mean(axis=0)
                shift = float(np.linalg.norm(t @ built.lattice.matrix))
                d = d - t
            dev = float(np.abs(d).max())
            if best_dev is None or dev < best_dev:
                best_dev, best_id, best_shift = dev, pid, shift
        if best_dev is not None and best_dev <= self.tol:
            self.last_shift_A = best_shift
            return best_id, best_dev
        return None, best_dev


def reference_grid(P, cfg: dict, with_energies: bool = True) -> ReferenceGrid:
    """The stored grid named by paths.reference_grid. run.replay.poscar_dirs ([{dir, id_offset}], dirs
    relative to repo_root) when its POSCARs live in several stored grids (a merged manifest)."""
    pd = (cfg.get("run", {}).get("replay") or {}).get("poscar_dirs")
    extra = None
    if pd:
        extra = []
        for d in pd:
            q = Path(d["dir"]).expanduser()
            extra.append((q if q.is_absolute() else P.repo_root / q, int(d.get("id_offset", 0))))
    return ReferenceGrid(P.repo("reference_grid"), P.repo("energies_csv") if with_energies else None, extra)
