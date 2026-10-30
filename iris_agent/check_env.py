"""Check the environment before evaluation runs: system configs, their data paths, replay index
status, API keys present (names only, never values), eval freeze, package versions. Read-only.

  python -m iris_agent.check_env [--configs configs/]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import sys
from pathlib import Path

from . import config as cfgmod
from . import freeze_eval
from .paths import from_config

AGENT_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK_SYSTEMS = ("cssni3", "ca3ti2o7", "inmno3", "ermno3", "bifeo3", "hfo2_paths")
KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY")


def replay_index(P, cfg) -> dict:
    out = {}
    try:
        from .engines.replay import reference_grid
        ref = reference_grid(P, cfg, with_energies=False)
        man = ref.manifest
        out["manifest_frames"] = len(man)
        out["poscars"] = sum(1 for m in man if m["id"] in ref._poscars)
        with open(P.repo("energies_csv")) as fh:
            ids = {int(r["id"]) for r in csv.DictReader(fh)}
        out["energies"] = len(ids)
        out["frames_without_energy"] = sum(1 for m in man if m["id"] not in ids)
        out["complete"] = out["poscars"] == out["manifest_frames"] and out["frames_without_energy"] == 0
    except Exception as exc:
        out = {"complete": False, "error": f"{type(exc).__name__}: {exc}"}
    iso = P.repo("isodistort_stored") if P.has("isodistort_stored") else None
    out["stored_isodistort"] = bool(iso and all((iso / f).is_file() for f in
                                                ("modes_details.txt", "tree.txt", "full_movie.cif")))
    return out


def check(cfg_dir: Path) -> dict:
    report = {"configs": {}, "keys": {k: ("set" if os.environ.get(k) else "not set") for k in KEYS}}
    cfgs = sorted(p for p in cfg_dir.glob("*.yaml") if not p.stem.endswith("_reference"))
    for p in cfgs:
        cfg = cfgmod.load(p)
        errs = cfgmod.validate(cfg)
        P = from_config(cfg)
        missing = []
        for k, v in cfg["paths"].items():
            if k in ("repo_root", "agent_root", "test_runs"):
                continue
            vals = v if isinstance(v, list) else [v]            # e.g. bifeo3 grid_packages: a list of folders
            for x in vals:
                q = pathlib.Path(str(x)).expanduser()
                q = q if q.is_absolute() else P.repo_root / q
                if not q.exists():
                    missing.append(f"{k}: {q}")
        report["configs"][p.stem] = {"schema_errors": errs, "missing_paths": missing, "replay": replay_index(P, cfg)}
    report["runbook_systems_missing"] = [s for s in RUNBOOK_SYSTEMS if s not in report["configs"]]
    ok, probs = freeze_eval.verify(AGENT_ROOT / "eval")
    report["eval_frozen"] = {None: "not frozen", True: "frozen, unchanged", False: f"CHANGED: {probs}"}[ok]
    from .run import _versions
    report["versions"] = _versions()
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--configs", default=str(AGENT_ROOT / "configs"))
    a = ap.parse_args(argv)
    r = check(Path(a.configs))
    for name, c in r["configs"].items():
        rp = c["replay"]
        state = "OK" if not c["schema_errors"] and not c["missing_paths"] and rp.get("complete") else "PROBLEM"
        print(f"{name:12} {state}  frames {rp.get('manifest_frames')}  POSCARs {rp.get('poscars')}  "
              f"energies {rp.get('energies')}  stored ISODISTORT {rp.get('stored_isodistort')}")
        for e in c["schema_errors"] + c["missing_paths"] + ([rp["error"]] if "error" in rp else []):
            print(f"             - {e}")
    print(f"systems still without a config: {', '.join(r['runbook_systems_missing']) or 'none'}")
    print("API keys: " + ", ".join(f"{k} {v}" for k, v in r["keys"].items()))
    print(f"eval inputs: {r['eval_frozen']}")
    print("versions: " + ", ".join(f"{k} {v}" for k, v in r["versions"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
