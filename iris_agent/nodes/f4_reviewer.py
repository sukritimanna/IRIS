"""f4 Reviewer: collect energies, check them, flag.

Convergence rule (demo/cssni3/perlmutter/collect_energies.py): a point is converged iff the last
electronic step in OSZICAR has |dE| < EDIFF in fewer than NELM steps; unconverged or missing points
are left out of the energies CSV. In replay the OSZICARs are not available locally, so a frame is
"converged" iff the stored CSV has its energy; frames without one are flagged, never recomputed.
Energy sanity follows iris/validation/energy_sanity.py (range of E - E0 between 1 meV and 10 eV).
"""
from __future__ import annotations

import math

MIN_RANGE_MEV, MAX_RANGE_MEV = 1.0, 10000.0     # iris/validation/energy_sanity.py


def f4_reviewer(state: dict) -> dict:
    jobs, grid = state["jobs"], state["grid"]
    if grid.get("kind") == "six_component":                # BiFeO3 6D (nodes/f4_grid6)
        from .f4_grid6 import f4_grid6
        return f4_grid6(state)
    if grid.get("kind") in ("path", "plane2"):             # straight-line path / two-component plane (nodes/f4_path)
        from .f4_path import f4_path
        return f4_path(state)
    per_fu = state["config"]["policy"]["fit"]["per_fu"]
    accept = bool(state.get("overrides", {}).get("f4", {}).get("flag_unconverged"))
    E, flagged = {}, []
    for fr in grid["frames"]:
        rec = jobs["matched"].get(str(fr["id"]))
        st = (rec or {}).get("status", "")
        if st.startswith("failed:"):
            # a failed job: G4 fails with its code (recovery.yaml) unless the frames are accepted as flagged
            flagged.append({"id": fr["id"], "code": st.split(":", 1)[1], "part": rec.get("part"),
                            "reason": f"job part {rec.get('part')} {st}", "accepted": accept})
            continue
        e = rec and rec.get("energy_eV")
        if e is None or not math.isfinite(e):
            flagged.append({"id": fr["id"], "reason": "no stored energy (unmatched or not converged)"})
            continue
        E[str(fr["id"])] = e
    vals = list(E.values())
    origin = next((str(f["id"]) for f in grid["frames"]
                   if all(abs(q) < 1e-12 for q in f["Q"].values()) and not f["tag"]), None)
    e0 = E.get(origin)
    rng = (max(vals) - min(vals)) * 1000 / per_fu if vals else None
    energies = {"eV_per_cell": E, "flagged": flagged, "n": len(E), "origin_id": origin,
                "E0_eV": e0, "range_meV_per_fu": rng, "per_fu": per_fu,
                "sanity": {"min_range_meV": MIN_RANGE_MEV, "max_range_meV": MAX_RANGE_MEV},
                "convergence_source": "stored CSV written by collect_energies.py (OSZICAR rule); "
                                      "OSZICAR/OUTCAR not available locally",
                "stored_input_sets": jobs.get("stored_input_sets", {}),
                "stored_input_sets_by_group": jobs.get("stored_input_sets_by_group", {})}
    return {"energies": energies, "last_node": "f4"}
