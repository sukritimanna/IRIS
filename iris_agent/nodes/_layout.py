"""Which policy block holds the stored/collected layout of a frame-based run: policy.path (straight-line path) or
policy.plane2 (two-component plane). Both write <stored>/<frame name>/ and <collected>/energies.csv."""
from __future__ import annotations


def grid_policy(pol: dict) -> dict:
    if pol.get("path"):
        return pol["path"]
    if pol.get("plane2"):
        return pol["plane2"]
    raise KeyError("policy.path or policy.plane2")


def dropped_frames(state: dict) -> dict:
    """Frames dropped from the grid by flag_and_continue and authorised by the human (policy.fit.allow_missing_frames);
    reported with every fit so that a result on fewer frames than planned is never silent."""
    e, g = state.get("energies") or {}, state.get("grid") or {}
    have = e.get("eV_per_cell") or {}
    d = [f["id"] for f in e.get("flagged", []) if f.get("accepted") and not f.get("energy_kept") and str(f.get("id")) not in have]
    return {"n_dropped": len(d), "n_planned": g.get("n_frames"), "ids": d[:50],
            "authorised": bool(state["config"]["policy"].get("fit", {}).get("allow_missing_frames"))}


def r5_anchor_report(state: dict) -> list | None:
    """For an R5 anchor_only decision: the energy each removed borderline irrep releases at the child, i.e.
    E(anchor frame) - E(the grid frame with the same axis amplitudes and the irrep at zero), in meV per f.u.
    Reported with the fit (or with the NO_FIT reason) so that the decision has a measured consequence."""
    g, e = state.get("grid") or {}, state.get("energies") or {}
    info = (g.get("r5") or {}).get("anchors") if g else None
    if not info:
        return None
    E = e.get("eV_per_cell") or {}
    per_fu = float(state["config"]["policy"]["fit"].get("per_fu", 1))
    frames = g.get("frames") or []
    out = []
    for a in info:
        anc = next((f for f in frames if f.get("tag") == a["tag"]), None)
        base = next((f for f in frames if not f.get("tag") and all(abs(float(f["Q"].get(k, 0.0)) - v) < 1e-9 for k, v in a["base"].items())), None)
        ea = E.get(str(anc["id"])) if anc else None
        eb = E.get(str(base["id"])) if base else None
        out.append({"irrep": a["irrep"], "amplitude_A": a["amplitude"], "anchor_id": anc["id"] if anc else None,
                    "base_id": base["id"] if base else None,
                    "dE_meV_per_fu": None if ea is None or eb is None else 1000.0 * (ea - eb) / per_fu})
    return out
