"""Experiment A (1): a deterministic decision tree for the gate sub-agents.

Inputs: gate, code, detail, the menu shown and the history of this run (whether a fix was already tried for the same
code). Nothing else: no case labels, no model answers. Every branch is a transcription of one sentence of the Guidance
line of that gate's prompt (prompts/subagent_G*.md, as frozen in the case files); a code the Guidance does not name,
or a Guidance sentence that lists options without choosing one, gives `stop`. A chosen option that is not on the menu
gives `stop`. Frozen with policies/FROZEN.sha256 before any scoring.
"""
from __future__ import annotations

# (gate, code) -> (option, Guidance sentence it comes from). "*" = any code of that gate.
TREE = {
    ("G0", "*"): ("stop", "G0: A config problem is for the human to correct."),
    ("G1", "NO_BASIS"): ("widen_basis_search", "G1: If no basis was found, widening the atom-matching search is the usual fix."),
    ("G1", "*"): ("stop", "G1: A pair that is not group-subgroup, or space groups that disagree, cannot be fixed here."),
    ("G2", "SINGLE_MODE_SG"): ("rebuild_fixed_lattice", "G2: A strict single-mode space-group mismatch ...: rebuild on the fixed parent lattice."),
    ("G2", "TRANSLATION"): ("remove_translation", "G2: A rigid translation left in a polar vector is removed by subtracting the mean displacement."),
    ("G2", "R5_BORDERLINE"): ("stop", "G2: R5_BORDERLINE ... is a modelling choice: include, exclude or anchor (no choice given -> stop)."),
    ("G2", "OVER_BUDGET"): ("stop", "G2: Over budget cannot be fixed here."),
    ("G3", "*"): ("stop", "G3: unmatched frames are flagged and a human decides."),
    ("G4", "WALLTIME"): ("resubmit", "G4: Walltime: resubmit unchanged."),
    ("G4", "NELM"): ("robust_mixing", "G4: SCF step limit: resubmit with robust mixing."),
    ("G4", "*"): ("stop", "G4: Inconsistent settings, magnetism or configuration values are for the human."),
    ("G5", "THIN_GRID"): ("densify", "G5: A coverage failure means the grid is too thin ...: go back to f2 and densify."),
    ("G5", "COVERAGE"): ("densify", "G5: A coverage failure means the grid is too thin ...: go back to f2 and densify."),
    ("G5", "*"): ("stop", "G5: Failures that concern the model or the stored data are not fixed by densifying."),
    ("G6", "*"): ("rerun_analysis", "G6: A number that does not re-derive is never edited by hand: re-run f5 or stop."),
}
# "If a fix was already tried for the same failure": G4 -> "choose between flagging and stopping" (no choice given ->
# stop); G6 -> "re-run f5 or stop" (re-run once, then stop). Any other gate: the same fix again is not offered -> stop.
TRIED_AGAIN = ("stop", "a fix was already tried for this failure (G4: flag or stop, no choice given; G6: re-run once)")


def _tried(ctx) -> bool:
    hist = ctx.get("history")
    if not isinstance(hist, list):
        return False
    return any(h.get("code") == ctx["code"] and h.get("level") in ("rule", "subagent") for h in hist)


def choose(ctx: dict) -> tuple[str, str]:
    gate, code, menu = ctx["gate"], ctx["code"], ctx["options"]
    if _tried(ctx):
        opt, why = TRIED_AGAIN
    else:
        opt, why = TREE.get((gate, code)) or TREE.get((gate, "*")) or ("stop", "no Guidance for this gate")
    if opt not in menu:
        return "stop", f"{opt} not on the menu -> stop ({why})"
    return opt, why
