"""Experiment A: rules only — the rule table (recovery.yaml) as a policy on the case prompts. The rule for
(node, code), if any and not yet applied in this run (history), is mapped to the menu option with the same patch;
otherwise `stop` (the human). This is what IRIS does with the sub-agent tier switched off."""
from __future__ import annotations

from pathlib import Path

import yaml

REC = yaml.safe_load((Path(__file__).resolve().parents[1] / "recovery.yaml").read_text())
NODE = {f"G{i}": f"f{i}" for i in range(7)}
RULE_TO_OPTION = {"f1_no_basis_dmax_ladder": "widen_basis_search", "f2_translation": "remove_translation",
                  "f2_single_mode_sg_fixed_lattice": "rebuild_fixed_lattice", "f4_walltime_resubmit": "resubmit",
                  "f4_nelm_robust_mixing": "robust_mixing", "f5_thin_grid_densify": "densify"}


def choose(ctx: dict) -> tuple[str, str]:
    node = NODE[ctx["gate"]]
    rule = next((r for r in REC["rules"] if r["node"] == node and r["code"] == ctx["code"]), None)
    hist = ctx.get("history") if isinstance(ctx.get("history"), list) else []
    if rule is None:
        return "stop", "no rule for this failure"
    used = sum(1 for h in hist if h.get("rule") == rule["id"])
    allowed = len(next(iter(rule["ladder"].values()))) if "ladder" in rule else 1
    if used >= allowed:
        return "stop", f"rule {rule['id']} used up ({used} of {allowed})"
    opt = RULE_TO_OPTION.get(rule["id"])
    if opt not in ctx["options"]:
        return "stop", f"rule {rule['id']} has no menu option"
    return opt, f"rule {rule['id']}"
