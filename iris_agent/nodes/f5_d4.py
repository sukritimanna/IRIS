"""D4 hard-secondary scans (policy.d4), analysed in f5 after the main fit.

For each scan (one secondary held at zero, scanned along its own calibrated vector at fixed primaries) the
energies E(a) per f.u., relative to the scan's a = 0 frame, are fitted by polynomials of degree 2 and 4; from
the quartic: curvature k = d2E/da2 at a = 0, linear term (the coupling to the primaries at that base point),
the relaxed amplitude a* and the energy the secondary would release, gain = min E - E(0) (inside the scanned
range). G5 (G5 d4 test) compares the largest gain with the smallest energy difference the run interprets
(policy.d4.compare_to, e.g. the ring corrugation of the plane fit) times policy.d4.max_fraction.
"""
from __future__ import annotations

import numpy as np


def _model_value(model: dict, path: str):
    cur = model
    for p in path.split("."):
        cur = cur[p]
    return float(cur)


def d4_analysis(state: dict, model: dict) -> dict | None:
    grid, en, cfg = state["grid"], state["energies"], state["config"]
    info = grid.get("d4")
    if not info:
        return None
    pol = cfg["policy"]["d4"]
    per_fu = cfg["policy"]["fit"]["per_fu"]
    E = en["eV_per_cell"]
    scans = []
    for sc in info["scans"]:
        fr = [f for f in grid["frames"] if f["tag"] == sc["tag"] and str(f["id"]) in E]
        a = np.array([f["Q"][sc["irrep"]] for f in fr])
        o = np.argsort(a)
        a = a[o]
        e = np.array([E[str(fr[i]["id"])] for i in o])
        i0 = int(np.argmin(np.abs(a)))
        y = (e - e[i0]) * 1000 / per_fu
        rec = {"name": sc["name"], "irrep": sc["irrep"], "base": sc["base"], "base_over_child": sc["base_over_child"],
               "n": int(len(a)), "range_A": [float(a.min()), float(a.max())]}
        for deg in (2, 4):
            c = np.polyfit(a, y, deg)
            r = y - np.polyval(c, a)
            xx = np.linspace(a.min(), a.max(), 20001)
            ff = np.polyval(c, xx)
            j = int(np.argmin(ff))
            rec[f"deg{deg}"] = {"curvature_meV_per_A2": float(2 * c[-3]), "linear_meV_per_A": float(c[-2]),
                                "a_star_A": float(xx[j]), "gain_meV": float(ff[j] - np.polyval(c, 0.0)),
                                "rms_meV": float(np.sqrt(np.mean(r ** 2)))}
        q = rec["deg4"]
        step = float(np.min(np.diff(a))) if len(a) > 1 else 0.0
        rec["edge_minimum"] = bool(abs(q["a_star_A"] - a.min()) < 1e-9 or abs(q["a_star_A"] - a.max()) < 1e-9)
        rec["class"] = ("soft" if q["curvature_meV_per_A2"] < 0 else
                        "induced" if abs(q["a_star_A"]) > step / 2 else "hard")
        rec["grid_min_meV"] = float(y.min())
        scans.append(rec)
    ref = pol.get("compare_to")
    ref_v = _model_value(model, ref) if isinstance(ref, str) else (float(ref) if ref is not None else None)
    worst = min(scans, key=lambda s: s["deg4"]["gain_meV"])
    return {"scans": scans, "compare_to": ref, "reference_meV": ref_v, "max_fraction": float(pol.get("max_fraction", 1.0)),
            "largest_gain_meV": -worst["deg4"]["gain_meV"], "largest_gain_scan": worst["name"],
            "child_secondary_Ap": {k: v["Ap_child"] for k, v in info["vectors"].items()}}
