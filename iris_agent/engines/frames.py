"""Frame construction shared by f2 (build), f3 (replay matching) and f6 (rebuild).

Cartesian frames: r = r0 + sum_i Q_i e_i (Q in Å of translation-free A_p).
Polar frames (a two-component irrep sampled in amplitude and direction, e.g. K3 in the hexagonal
manganites): the frame carries "phi_deg" and the polar irrep's amplitude Q; its displacement is
Q (cos phi e_1 + sin phi e_2), with e_2 = the second component of the same irrep (vectors["<irrep>@c2"]).
"""
from __future__ import annotations

import numpy as np


def frame_frac(fr: dict, f0, vec: dict, active: list[str]):
    Q = fr["Q"]
    frac = np.array(f0, dtype=float).copy()
    polar = fr.get("polar")
    for ir in list(active) + [k for k in Q if k not in active and k in vec]:   # + D4 secondaries
        q = float(Q.get(ir, 0.0))
        if q == 0.0:
            continue
        if polar and ir == polar:
            ph = np.radians(float(fr["phi_deg"]))
            frac = frac + q * (np.cos(ph) * np.asarray(vec[ir]) + np.sin(ph) * np.asarray(vec[f"{ir}@c2"]))
        else:
            frac = frac + q * np.asarray(vec[ir])
    return frac


def second_component(e1, f0, lattice, species, translation):
    """Second component of a two-dimensional irrep at k = (1/3, 1/3, 0)-type points: translate the
    displacement field of the first component by a parent lattice vector t (child fractional
    coordinates), which rotates the order-parameter phase by 120 deg; orthogonalise and normalise.
    Returns (e2, info). Raises if t does not map the reference frame onto itself."""
    f0, L, t = np.asarray(f0, float), np.asarray(lattice, float), np.asarray(translation, float)
    perm = np.empty(len(f0), dtype=int)
    for j in range(len(f0)):
        d = f0 - (f0[j] + t)
        d -= np.round(d)
        k = int(np.argmin(np.linalg.norm(d @ L, axis=1)))
        if np.linalg.norm(d[k] @ L) > 1e-3 or species[k] != species[j]:
            raise ValueError(f"translation {t.tolist()} does not map atom {j} onto an equal atom")
        perm[j] = k
    eT = np.zeros_like(e1)
    eT[perm] = e1
    n1 = float(np.sum((e1 @ L) ** 2))
    cos = float(np.sum((eT @ L) * (e1 @ L)) / n1)
    e2 = eT - cos * e1
    e2 = e2 * np.sqrt(n1 / np.sum((e2 @ L) ** 2))
    return e2, {"cos_T": cos, "phase_shift_deg": float(np.degrees(np.arccos(np.clip(cos, -1, 1)))),
                "norm_ratio_T": float(np.sqrt(np.sum((eT @ L) ** 2) / n1)), "translation": t.tolist()}


def polar_expected_sg(phi_deg: float, P: float, sg_phi0: int, sg_phi30_p0: int, sg_general: int) -> int:
    """Space group of a K3-type frame by its direction (hexagonal manganites: Phi = 0 mod 60 -> P6_3cm,
    Phi = 30 mod 60 with P = 0 -> P-3c1, otherwise P3c1)."""
    m = round(float(phi_deg), 6) % 60
    if abs(m) < 1e-6 or abs(m - 60) < 1e-6:
        return sg_phi0
    if abs(m - 30) < 1e-6 and abs(P) < 1e-12:
        return sg_phi30_p0
    return sg_general
