"""f3 live (run.mode = live): write every frame's VASP inputs; the live executor submits them.

Called by f3_runner in live mode, for grid kind "path" (first live build). The frames are written to
policy.path.stored (resolved by f0 to test_runs/<thread>/live/<path>/), one folder per point L<kk>:
POSCAR (IRIS's atom order), INCAR (run.live.incar), KPOINTS (run.live.kpoints) and frame.json. POTCAR and the
job script are written by the executor (iris_agent.live_executor), which is the only process that submits.
Nothing is written outside agent_root (Paths.out).

After the job-end events, f3_runner reads the results with nodes/f3_path.match_path, exactly as for stored
points: same species order, every atom and the cell within tolerance of the frame f2 built.
"""
from __future__ import annotations

import json

import numpy as np

from ..engines import live_vasp as LV
from ..engines.frames import frame_frac


def prepare_path(state: dict, P) -> dict:
    cfg, grid = state["config"], state["grid"]
    live = cfg["run"]["live"]
    from ._layout import grid_policy
    lay = grid_policy(cfg["policy"])
    stored = P.out(P.repo_root / lay["stored"])   # refuses anything outside agent_root
    stored.mkdir(parents=True, exist_ok=True)
    r0 = state["decomposition"]["vectors"]["r0"]
    f0 = np.array(r0["frac"])
    vec = {ir: np.array(v) for ir, v in grid["vectors"].items()}
    incar = LV.incar_text(live["incar"])
    written = {}
    # KPOINTS: the author's kpointsUtilities rule (Gamma mesh, k_i = ceil(|b_i|/spacing)), from the lambda = 0 POSCAR so the
    # whole path shares one mesh (G4 dft_consistent); an explicit run.live.kpoints overrides it
    kpts, mesh, ksrc = None, None, None
    written = {}
    for fr in grid["frames"]:
        d = P.out(stored, fr["name"])
        d.mkdir(exist_ok=True)
        frac = frame_frac(fr, f0, vec, grid["active"])
        title = (f"{cfg['system']} {fr['name']} lambda={fr['lambda']:.6f} (IRIS frame {fr['id']})" if fr.get("lambda") is not None
                 else f"{cfg['system']} {fr['name']} Q={fr['Q']} (IRIS frame {fr['id']})")
        P.out(d, "POSCAR").write_text(LV.poscar_text(title, fr["lattice"], r0["species"], frac))
        if kpts is None:
            if live.get("kpoints"):
                kpts, mesh, ksrc = LV.kpoints_text(live["kpoints"]), list(live["kpoints"]), "run.live.kpoints"
            else:
                from ..engines import kpoints_utilities as KU
                sp = float(live.get("kspacing", KU.SPACING))
                mesh = KU.writeKpoints(str(P.out(d, "POSCAR")), str(P.out(d, "KPOINTS")), sp)
                kpts, ksrc = P.out(d, "KPOINTS").read_text(), f"kpointsUtilities.writeKpoints(L00/POSCAR, spacing {sp}) for every frame"
        P.out(d, "INCAR").write_text(incar)
        P.out(d, "KPOINTS").write_text(kpts)
        P.out(d, "frame.json").write_text(json.dumps({k: fr.get(k) for k in ("id", "name", "lambda", "Q", "sg", "d_min", "multiplicity", "grid_index")}))
        written[str(fr["id"])] = fr["name"]
    return {"engine": "live", "stored": str(stored), "collected": str(P.out(P.repo_root / lay["collected"])),
            "frames": written, "per_fu": int(cfg["policy"]["fit"]["per_fu"]), "species": list(r0["species"]),
            "kmesh": mesh, "kpoints_source": ksrc,
            "potcar_source": f"writePotcar convention: {live['potcar_dir']}/<Element>/POTCAR in POSCAR species order"}
