"""Stored ISODISTORT responses (no web calls).

Reads <reference_run>/step3_isodistort/04_raw_isodistort/:
  modes_details.txt  amplitudes (As, Ap, dmax) per mode component and per irrep, strain, subgroup string
  tree.txt           subgroup tree (parsed by the existing step3 parse_tree)
  full_movie.cif     mode matrix: deltacoords = matrix . (amplitude x normfactor), per Wyckoff representative;
                     the movie header lists each irrep's isotropy subgroup

and builds, for every displacive irrep i, its displacement field in the parent-frame supercell at the
child amplitude (norm = A_s,i Å). Symmetry expansion of the Wyckoff representatives is done by
pymatgen's CIF parser on the stored block; atoms are matched to the undistorted frame by species +
nearest periodic image (Hungarian).
"""
from __future__ import annotations

import io
import re
import warnings
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

IRREP = r"(?:GM|[A-Z]{1,2})\d+[+-]?"


def _block(text: str, start: str, stop: str) -> str:
    return text.split(start, 1)[1].split(stop, 1)[0]


def irrep_of(label: str) -> str:
    return re.search(r"\](" + IRREP + r")\(", label).group(1)


def direction_of(label: str) -> str:
    return re.search(r"\]" + IRREP + r"(\([^)\]]*\))", label).group(1)


def free_components(direction: str) -> int:
    """D1: number of independent letters in an ISODISTORT direction label, e.g. (a,-a,0) -> 1."""
    return len(set(re.findall(r"[a-z]", direction)))


class StoredIsodistort:
    def __init__(self, raw_dir: str | Path):
        self.dir = Path(raw_dir)
        self.modes_details = (self.dir / "modes_details.txt").read_text()
        self.tree_text = (self.dir / "tree.txt").read_text()
        movie = (self.dir / "full_movie.cif").read_text()
        blocks = re.split(r"(?=^data_isodistort-output)", movie, flags=re.M)
        self.header, self.block = blocks[0], blocks[1]
        self._parse_matrix()

    # ---- parsing ---------------------------------------------------------------------------
    def _parse_matrix(self):
        b = self.block
        rows = re.findall(r"^\s+(\d+) (\S+\[\S+?\]\S+)\s+(-?\d+\.\d+)\s*$",
                          _block(b, "_iso_displacivemode_value", "loop_"), re.M)
        self.mode_labels = {int(i): lab for i, lab, _ in rows}
        self.norms = {int(i): float(v) for i, v in re.findall(
            r"^\s+(\d+)\s+(-?\d+\.\d+)\s*$", _block(b, "_iso_displacivemodenorm_value", "loop_"), re.M)}
        self.delta_labels = {int(i): lab for i, lab in re.findall(
            r"^\s+(\d+) (\S+)\s+-?\d+\.\d+\s*$", _block(b, "_iso_deltacoordinate_value", "loop_"), re.M)}
        self.matrix = [(int(r), int(c), float(v)) for r, c, v in re.findall(
            r"^\s+(\d+)\s+(\d+)\s+(-?\d+\.\d+)\s*$",
            _block(b, "_iso_displacivemodematrix_value", "_iso_magneticmode"), re.M)]
        if not (self.mode_labels and self.norms and self.delta_labels and self.matrix):
            raise ValueError("stored movie CIF has no displacive mode matrix")

    def subgroup(self) -> dict:
        m = re.search(r"^\s*(\d+)\s+(\S+),\s*basis=\{(.*?)\},\s*origin=\((.*?)\),\s*s=(\d+),\s*i=(\d+)",
                      self.modes_details.split("Subgroup details", 1)[1], re.M)
        vecs = [[int(x) for x in v.split(",")] for v in re.findall(r"\(([^)]*)\)", m.group(3))]
        frac = lambda t: float(Fraction(t.strip()))               # "1/2" -> 0.5
        return {"sg": int(m.group(1)), "symbol": m.group(2), "basis": vecs,
                "origin": [frac(t) for t in m.group(4).split(",")], "s": int(m.group(5)), "i": int(m.group(6))}

    def isotropy_by_irrep(self) -> dict:
        """From the movie header: 'Pm-3m[..]M3+(0;a;0) 127 P4/mbm s=2 i=6'."""
        out = {}
        for m in re.finditer(r"^#\s+\S+?\](" + IRREP + r")(\([^)]*\))\s+(\d+)\s+(\S+)\s+s=(\d+)\s+i=(\d+)",
                             self.header, re.M):
            out[m.group(1)] = {"direction": m.group(2), "sg": int(m.group(3)), "symbol": m.group(4),
                               "s": int(m.group(5)), "i": int(m.group(6))}
        return out

    def component_amplitudes(self) -> dict:
        """mode label (without parent symbol) -> As of that component, from modes_details."""
        return {m.group(1): float(m.group(2)) for m in re.finditer(
            r"^\s*(\[\S+?\]\S+?\[\S+?\]\S+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)", self.modes_details, re.M)}

    def max_displacement(self) -> float:
        """Largest per-site displacement ('displ' column of the distorted superstructure)."""
        sec = _block(self.modes_details, "Distorted superstructure", "Displacive mode definitions")
        return max(float(x) for x in re.findall(r"^\S+\s+\S+\s+(?:-?\d+\.\d+\s+){4}(-?\d+\.\d+)", sec, re.M))

    def child_superstructure_abc(self) -> list[float]:
        """Cell of the distorted (child) superstructure in the parent-supercell setting."""
        sec = self.modes_details.split("Distorted superstructure", 1)[1]
        return [float(x) for x in re.search(r"a=([\d.]+), b=([\d.]+), c=([\d.]+)", sec).groups()]

    # ---- structures ------------------------------------------------------------------------
    def structure(self, amps: dict[int, float] | None = None):
        """Supercell on the undistorted parent lattice with mode amplitudes {mode id: As}."""
        from pymatgen.io.cif import CifParser
        amps = amps or {}
        delta = dict.fromkeys(self.delta_labels, 0.0)
        for r, c, v in self.matrix:
            delta[r] += v * amps.get(c, 0.0) * self.norms[c]
        key_of = {lab: k for k, lab in self.delta_labels.items()}        # "O1_1_dx" -> delta id
        out = []
        for ln in self.block.splitlines():
            m = re.match(r"^(\S+)\s+(\S+)\s+(\d+)\s+(\S)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+\.\d+)\s+(\S+)\s*$", ln)
            if m:
                name, xyz = m.group(1), [float(m.group(i)) for i in (5, 6, 7)]
                # _atom_site_fract_symmform: how the site's free parameters Dx,Dy,Dz enter each coordinate, e.g.
                # "Dx,-Dx,Dz" on the hexagonal R3m 9b site (x += Dx, y -= Dx, z += Dz); "0,0,Dz" on a 3a site
                for i, comp in enumerate(symmform(m.group(9))):
                    for ax, coef in comp:
                        k = key_of.get(f"{name}_d{ax}")
                        if k is not None:
                            xyz[i] += coef * delta[k]
                ln = (f"{name} {m.group(2)} {m.group(3)} {m.group(4)} "
                      f"{xyz[0]:.10f} {xyz[1]:.10f} {xyz[2]:.10f} {m.group(8)} {m.group(9)}")
            out.append(ln)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return CifParser(io.StringIO("\n".join(out)), occupancy_tolerance=1.0).parse_structures(primitive=False)[0]

    def irrep_fields(self) -> tuple:
        """(r0, {irrep: (N,3) fractional displacement at the child amplitude}, {irrep: [mode ids]})."""
        r0 = self.structure()
        comp = self.component_amplitudes()
        groups: dict[str, list[int]] = {}
        for k, lab in self.mode_labels.items():
            groups.setdefault(irrep_of(lab), []).append(k)
        fields = {}
        for ir, ks in groups.items():
            amps = {k: comp[re.sub(r"^[^\[]+", "", self.mode_labels[k])] for k in ks}
            s = self.structure(amps)
            perm = match_atoms(r0, s)
            d = s.frac_coords[perm] - r0.frac_coords
            fields[ir] = d - np.round(d)
        return r0, fields, groups


def symmform(sf: str) -> list[list[tuple[str, float]]]:
    """'Dx,-Dx,Dz' -> [[('x', 1.0)], [('x', -1.0)], [('z', 1.0)]]; '0,0,Dz' -> [[], [], [('z', 1.0)]]; '2Dx' allowed."""
    comps = sf.split(",")
    if len(comps) != 3:
        return [[("x", 1.0)], [("y", 1.0)], [("z", 1.0)]]          # no symmform: independent Dx, Dy, Dz
    out = []
    for c in comps:
        terms = []
        for sign, num, ax in re.findall(r"([+-]?)(\d*\.?\d*)D([xyz])", c):
            coef = float(num) if num else 1.0
            terms.append((ax, -coef if sign == "-" else coef))
        out.append(terms)
    return out


def match_atoms(ref, s) -> np.ndarray:
    """perm such that s[perm[j]] is the atom of s matching ref[j] (species + nearest periodic image)."""
    perm = np.full(len(ref), -1)
    L = ref.lattice.matrix
    for sp in sorted({str(x) for x in ref.species}):
        ia = [i for i, x in enumerate(ref.species) if str(x) == sp]
        ib = [i for i, x in enumerate(s.species) if str(x) == sp]
        if len(ia) != len(ib):
            raise ValueError(f"species {sp}: {len(ia)} vs {len(ib)} atoms")
        d = ref.frac_coords[ia][:, None, :] - s.frac_coords[ib][None, :, :]
        d -= np.round(d)
        r, c = linear_sum_assignment(np.linalg.norm(d @ L, axis=2))
        for a, b in zip(r, c):
            perm[ia[a]] = ib[b]
    return perm


@lru_cache(maxsize=4)
def load(raw_dir: str) -> StoredIsodistort:
    return StoredIsodistort(raw_dir)
