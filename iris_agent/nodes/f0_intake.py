"""f0 Intake. This build reads the run config file (the LLM request -> config step is build step 6).

Output: config (as read), inputs (resolved CIF paths, sha256, spglib space groups, schema errors).
G0 then checks schema, CIF files, space groups, budget and the write location.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .. import config as cfgmod


def _sg(path: Path) -> int:
    from pymatgen.core import Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    return SpacegroupAnalyzer(Structure.from_file(str(path)), symprec=1e-3).get_space_group_number()


def f0_intake(state: dict) -> dict:
    cfg = cfgmod.load(state["config_path"])
    over = state.get("overrides", {}).get("f0", {})
    if over.get("config_patch"):             # a human-supplied correction from recover
        from ..recover import _merge
        cfg = _merge(cfg, over["config_patch"])
    if isinstance(cfg, dict) and state.get("thread_id"):
        cfg["thread_id"] = state["thread_id"]       # files of this run go to test_runs/<thread_id>/
    mode = (state.get("run_meta") or {}).get("mode")
    if isinstance(cfg, dict) and mode:
        cfg.setdefault("run", {})["mode"] = mode     # --mode on the command line
    if isinstance(cfg, dict) and (cfg.get("run") or {}).get("mode") == "live" and ((cfg.get("policy") or {}).get("path") or (cfg.get("policy") or {}).get("plane2")):
        _resolve_run_token(cfg)                      # policy.path.stored/collected: "{run}" -> this run's folder
    errs = cfgmod.validate(cfg)
    inputs = {"schema_errors": errs, "config_path": str(state["config_path"]),
              "faults_injected": (cfg.get("faults") or {}) if isinstance(cfg, dict) else {}}
    p = cfg.get("paths", {}) if isinstance(cfg, dict) else {}
    root = Path(str(p.get("repo_root", ""))).expanduser()
    for role in ("parent", "child"):
        rel = p.get(f"{role}_cif")
        if not rel:
            continue
        f = Path(rel).expanduser()
        f = f if f.is_absolute() else root / f
        inputs[f"{role}_cif"] = str(f)
        if f.is_file():
            inputs[f"{role}_sha256"] = hashlib.sha256(f.read_bytes()).hexdigest()
            try:
                inputs[f"{role}_sg"] = _sg(f)
            except Exception as exc:
                inputs[f"{role}_read_error"] = f"{type(exc).__name__}: {exc}"
    return {"config": cfg, "inputs": inputs,
            "intent": state.get("request") or cfg.get("request", ""), "last_node": "f0"}


def _resolve_run_token(cfg: dict) -> None:
    """Live runs write their computed points inside this run's folder; "{run}" in policy.path.stored / collected
    becomes test_runs/<thread_id> relative to repo_root (the path nodes resolve these against repo_root)."""
    from ..paths import from_config
    P = from_config(cfg)
    rel = str(P.run_dir(cfg["thread_id"]).relative_to(P.repo_root))
    pp = cfg["policy"].get("path") or cfg["policy"]["plane2"]
    for k in ("stored", "collected"):
        if isinstance(pp.get(k), str):
            pp[k] = pp[k].replace("{run}", rel)
