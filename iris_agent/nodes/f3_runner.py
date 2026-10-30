"""f3 Runner — replay only, with the job wait of the real workflow.

1. Submit (once). Match every frame f2 built to a stored computed structure (engines/replay.py) and
   group the frames into parts. The submission record test_runs/<thread>/f3_jobs/submission.json is
   written before waiting; when LangGraph re-runs f3 on resume it finds the record for the same grid
   and reuses it, so a resumed run never submits twice.
2. Wait. interrupt() until every part has ended (engines/jobs.wait); job-end events come from
   `python -m iris_agent.jobend` (the stand-in for a Slurm job-end hook).
3. Collect. Energies are linked only for frames in finished parts; frames in failed parts carry the
   failure code for f4.

Live (run.mode = live, grid kind "path"): step 1 writes every frame's VASP inputs (nodes/f3_live.py) instead of
matching stored structures; the live executor (python -m iris_agent.live_executor) submits the parts, collects
the outputs into the same layout and sends the same job-end events. Step 3 then reads the computed points with
the path matcher (nodes/f3_path.match_path). Live submission is refused in any other mode (config + G0).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import numpy as np
from langgraph.types import interrupt

from ..engines import jobs as J
from ..engines.frames import frame_frac
from ..engines.replay import Matcher, reference_grid
from ..paths import from_config


def _grid_key(grid: dict, resubmit_tag: str = "") -> str:
    q = json.dumps([[f["id"], f.get("Q", f.get("q_A"))] for f in grid["frames"]], sort_keys=True) + resubmit_tag
    return hashlib.sha256(q.encode()).hexdigest()


def _match(state, P, tol, hidden=()):
    from pymatgen.core import Lattice, Structure
    grid = state["grid"]
    r0 = state["decomposition"]["vectors"]["r0"]
    lat, species, f0 = Lattice(r0["lattice"]), r0["species"], np.array(r0["frac"])
    vec = {ir: np.array(v) for ir, v in grid["vectors"].items()}
    ref = reference_grid(P, state["config"])
    rp = state["config"]["run"].get("replay") or {}
    m = Matcher(ref, Structure(lat, species, f0), grid["active"], tol_frac=tol, hidden_ids=hidden,
                label_scale=float(rp.get("label_scale", 1.0)), modulo_translation=bool(rp.get("match_modulo_translation")))
    # extra stored grids for tagged frames (run.replay.extra_references: polar hat grid), each with its own
    # manifest labels and energies; their stored ids are namespaced "<tag>:<id>" in the records
    extra = {}
    for x in rp.get("extra_references") or []:
        from ..engines.replay import ReferenceGrid
        xr = ReferenceGrid(P.repo_root / x["grid"], P.repo_root / x["energies"])
        lk = x["labels"]
        xm = Matcher(xr, Structure(lat, species, f0), [k for k in lk], tol_frac=tol, label_keys=list(lk.values()))
        extra[x["tag"]] = (xr, xm, {"grid": x["grid"], "energies": x["energies"]})
    shift_max = 0.0
    matched, unmatched, used, dev_max = {}, [], set(), 0.0
    used_x = {t: set() for t in extra}
    for fr in grid["frames"]:
        frac = frame_frac(fr, f0, vec, grid["active"])
        if fr["tag"] in extra:
            xr, xm, _ = extra[fr["tag"]]
            lab = {**fr["Q"], "phi": fr.get("phi_deg", 0.0)}
            pid, dev = xm.match(Structure(lat, species, frac), lab, exclude=used_x[fr["tag"]])
            if pid is None:
                unmatched.append({"id": fr["id"], "Q": fr["Q"], "phi_deg": fr.get("phi_deg"), "best_dev": dev})
                continue
            used_x[fr["tag"]].add(pid)
            matched[str(fr["id"])] = {"stored_id": f"{fr['tag']}:{pid}", "ref": fr["tag"], "dev_frac": dev,
                                      "energy_eV": xr.energies.get(pid)}
            dev_max = max(dev_max, dev)
            continue
        pid, dev = m.match(Structure(lat, species, frac), fr["Q"], exclude=used)
        if pid is None or pid in used:
            unmatched.append({"id": fr["id"], "Q": fr["Q"], "best_dev": dev})
            continue
        used.add(pid)
        matched[str(fr["id"])] = {"stored_id": pid, "dev_frac": dev, "energy_eV": ref.energies.get(pid)}
        if m.modulo_translation:
            matched[str(fr["id"])]["rigid_shift_A"] = m.last_shift_A
            shift_max = max(shift_max, m.last_shift_A)
        dev_max = max(dev_max, dev)
    hashes, by_group = {}, {}
    tag_of = {str(fr["id"]): fr["tag"] for fr in grid["frames"]}
    for fid, v in matched.items():
        if v.get("ref"):
            h = extra[v["ref"]][0].input_hashes(int(str(v["stored_id"]).split(":")[1]))
        else:
            h = ref.input_hashes(v["stored_id"])
        key = f"INCAR {h.get('INCAR')} / KPOINTS {h.get('KPOINTS')}"
        hashes[key] = hashes.get(key, 0) + 1
        grp = tag_of.get(fid, "") if tag_of.get(fid, "").startswith("d4_") else "main"
        by_group.setdefault(grp, {})
        by_group[grp][key] = by_group[grp].get(key, 0) + 1
    return {"matched": matched, "unmatched": unmatched, "max_dev_frac": dev_max, "tolerance_frac": m.tol,
            "origin_dev_frac": m.origin_dev, "stored_input_sets": hashes, "stored_input_sets_by_group": by_group,
            "label_scale": m.label_scale,
            "modulo_translation": m.modulo_translation, "max_rigid_shift_A": shift_max,
            "reference_grid": str(P.repo("reference_grid")), "energies_csv": str(P.repo("energies_csv")),
            "extra_references": {t: v[2] for t, v in extra.items()}}


def f3_runner(state: dict) -> dict:
    cfg, grid = state["config"], state["grid"]
    live = cfg["run"]["mode"] == "live"
    if cfg["run"].get("allow_live_submission") and not live:
        raise RuntimeError("live submission is only allowed with run.mode: live")
    if live and grid.get("kind") not in ("path", "plane2"):
        raise RuntimeError("live mode is built for grid kinds 'path' and 'plane2'")
    P = from_config(cfg)
    over = state.get("overrides", {}).get("f3", {})
    jcfg = cfg["run"].get("jobs", {})
    part_size = int(jcfg.get("part_size", 40))
    faults = (cfg.get("faults") or {}) if cfg["run"]["mode"] == "replay" else {}
    jdir = P.out(P.run_dir(cfg["thread_id"]), "f3_jobs")
    jdir.mkdir(exist_ok=True)
    key = _grid_key(grid)
    prev = state.get("jobs") if (state.get("jobs") or {}).get("grid_key") == key else None

    # ---- 1. submit once (round 0) or resubmit failed parts (round r) ----------------------------
    rec0_path = P.out(jdir, "submission.json")
    rec0 = json.loads(rec0_path.read_text()) if rec0_path.is_file() else None
    if live and (not rec0 or rec0.get("grid_key") != key):
        from .f3_live import prepare_path
        lv = prepare_path(state, P)
        ids = sorted(int(i) for i in lv["frames"])
        rec0 = {"grid_key": key, "round": 0, "engine": "live", "n_submissions": 1,
                "submitted_utc": datetime.now(timezone.utc).isoformat(), "part_size": part_size,
                "book": {"parts": J.plan_parts(ids, part_size)}, "live": lv, "replay": None}
        rec0_path.write_text(json.dumps(rec0))
    if not rec0 or rec0.get("grid_key") != key:
        if grid.get("kind") == "six_component":       # BiFeO3 6D (nodes/f3_grid6): frames keyed by position
            from .f3_grid6 import match6
            replay = match6(state, P, float(over.get("tol_A", (cfg["run"].get("replay") or {}).get("tol_A", 1e-3))),
                            faults.get("hide_stored_ids", ()))
        elif grid.get("kind") == "path":              # straight-line path (nodes/f3_path): stored L<kk> points
            from .f3_path import match_path
            rp = cfg["run"].get("replay") or {}
            replay = match_path(state, P, float(over.get("tol_A", rp.get("tol_A", 1e-3))),
                                float(rp.get("tol_lattice_A", 1e-4)), faults.get("hide_stored_ids", ()))
        else:
            replay = _match(state, P, over.get("tol_frac", 1e-4), faults.get("hide_stored_ids", ()))
        ids = sorted(int(i) for i in replay["matched"])
        rec0 = {"grid_key": key, "round": 0, "engine": "replay", "n_submissions": 1,
                "submitted_utc": datetime.now(timezone.utc).isoformat(), "part_size": part_size,
                "book": {"parts": J.plan_parts(ids, part_size)}, "replay": replay}
        rec0_path.write_text(json.dumps(rec0))
    replay = rec0["replay"]
    if prev is None:
        rnd, book, events = 0, rec0["book"], []
        records = [str(rec0_path)]
    else:
        rnd, book, events, records = prev["round"], prev["book"], prev["events"], prev["submission_records"]
        failed = sorted(int(p) for p, v in book["parts"].items() if v["status"].startswith("failed"))
        rerun_all = bool(over.get("resubmit_all"))     # every part again (an INCAR change must apply to the whole path)
        if rerun_all:
            failed = sorted(int(p) for p in book["parts"])
        if failed and (over.get("resubmit_failed") or rerun_all):
            rnd += 1
            rp = P.out(jdir, f"submission_r{rnd}.json")
            if rp.is_file():                      # LangGraph re-ran f3 on resume: reuse, never resubmit
                rec = json.loads(rp.read_text())
            else:
                parts = {p: ({**v, "status": "queued", "previous": v["status"]} if int(p) in failed else v)
                         for p, v in book["parts"].items()}
                rec = {"grid_key": key, "round": rnd, "engine": "live" if live else "replay", "resubmitted_parts": failed,
                       "rerun_all": rerun_all, "incar_patch": over.get("incar", {}),
                       "submitted_utc": datetime.now(timezone.utc).isoformat(), "book": {"parts": parts}}
                rp.write_text(json.dumps(rec))
            book, records = rec["book"], records + [str(rp)]

    # ---- 2. wait for job-end events -------------------------------------------------------------
    if J.pending(book) and jcfg.get("wait", True):
        book = J.wait(book, interrupt, {"node": "f3", "thread_id": cfg["thread_id"], "round": rnd,
                                        "submission": records[-1]})
        events = events + book.pop("events", [])
    elif J.pending(book):
        book = {"parts": {p: {**v, "status": "finished"} if v["status"] == "queued" else v
                          for p, v in book["parts"].items()}}
        events = events + [{"event": "no wait (run.jobs.wait = false)", "accepted": True}]

    # ---- 3. collect -----------------------------------------------------------------------------
    if live:                                         # the executor has written result.json for every ended part
        from .f3_path import match_path
        rp = cfg["run"].get("replay") or {}
        replay = match_path(state, P, float(over.get("tol_A", rp.get("tol_A", 1e-3))),
                            float(rp.get("tol_lattice_A", 1e-4)))
    status_of = {str(f): v["status"] for v in book["parts"].values() for f in v["frames"]}
    part_of = {str(f): p for p, v in book["parts"].items() for f in v["frames"]}
    matched = {}
    for fid, m in replay["matched"].items():
        st = status_of.get(fid, "queued")
        matched[fid] = {**m, "part": part_of.get(fid), "status": st,
                        "energy_eV": m["energy_eV"] if st == "finished" else None}
    q = sum(1 for v in book["parts"].values() if v["status"] == "queued")
    jobs = {"engine": "live" if live else "replay", "grid_key": key, "round": rnd, "submission_records": records,
            "n_submissions": len(records), "part_size": part_size, "book": book, "parts": J.summary(book),
            "events": events, "n_frames": len(grid["frames"]),
            "n_matched": len(replay["matched"]), "unmatched": replay["unmatched"],
            "max_dev_frac": replay["max_dev_frac"], "tolerance_frac": replay["tolerance_frac"],
            "origin_dev_frac": replay["origin_dev_frac"], "label_scale": replay.get("label_scale", 1.0),
            **{k: replay[k] for k in ("max_dev_A", "max_dq_A", "max_outside_span_A", "max_lattice_dev_A") if k in replay},
            "modulo_translation": replay.get("modulo_translation", False), "max_rigid_shift_A": replay.get("max_rigid_shift_A", 0.0),
            "extra_references": replay.get("extra_references", {}),
            "queued": q, "running": 0,
            "cancelled": sum(1 for v in book["parts"].values() if v["status"] == "cancelled"),
            "stored_input_sets": replay["stored_input_sets"],
            "stored_input_sets_by_group": replay.get("stored_input_sets_by_group", {}), "reference_grid": replay["reference_grid"],
            "energies_csv": replay["energies_csv"], "faults_injected": faults, "matched": matched}
    return {"jobs": jobs, "last_node": "f3"}
