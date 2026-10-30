"""Keyword / template baseline for the intake, built from the tables only (intake/library.py): system names and
formulas, space-group numbers and symbols, transition ids. No request phrasing, no analysis / strain / profile
keywords: every other field is left to the policy default.

  system      the system ids and the formulas / names in SYSTEMS (case-insensitive, exactly one must occur)
  structures  space groups named in the text (#N or a Hermann-Mauguin symbol of the transition table), in order of
              mention: first = parent, second = child
  transition  a transition id in the text, else the SG pair, else the only stored transition of the system
  ask         no / several systems, or a system with several transitions and no SG pair or id
  refuse      an SG pair (or id) that is not in the transition table
"""
from __future__ import annotations

import re

from .library import SYSTEMS, TRANSITIONS


def _names() -> dict:
    out = {}
    for sid, text in SYSTEMS.items():
        head = text.split(",")[0]                         # "CsSnI3" / "HfO2 (hafnia)"
        toks = {sid} | {t for t in re.split(r"[\s()]+", head) if t}
        out[sid] = sorted(toks, key=len, reverse=True)
    return out


def _hm_symbols() -> dict:
    """Hermann-Mauguin symbols of the transition labels -> space-group number."""
    sym = {}
    for v in TRANSITIONS.values():
        a, b = v["label"].split(",")[0].split("->")
        for name, sg in ((a, v["parent_sg"]), (b, v["child_sg"])):
            sym[name.split("(")[0].strip()] = sg
    return sym


NAMES, HM = _names(), _hm_symbols()


def _norm(s: str) -> str:
    return s.lower().replace("₂", "2").replace("₁", "1").replace("₃", "3").replace("_", "")


def draft(text: str, attachments: list[str] | None = None) -> dict:
    d = {k: None for k in ("system", "parent_sg", "child_sg", "transition", "analysis", "strain_policy",
                           "system_profile", "budget", "clarify_field", "question", "out_of_scope_reason")}
    d.update({"outputs": [], "out_of_scope": False})
    ids = [k for k in TRANSITIONS if k in text]
    if ids:                                               # a transition id names the system and the structures
        v = TRANSITIONS[ids[0]]
        return {**d, "system": v["system"], "transition": ids[0]}
    t = _norm(text)
    hits = [sid for sid, toks in NAMES.items() if any(re.search(rf"(?<![a-z0-9]){re.escape(_norm(x))}(?![a-z0-9])", t)
                                                       for x in toks)]
    if len(hits) != 1:
        return {**d, "clarify_field": "system", "question": "Which system?"}
    s = d["system"] = hits[0]
    pos = []                                              # (position, space group) of every SG mention
    for m in re.finditer(r"#\s*(\d{1,3})\b", t):
        pos.append((m.start(), int(m.group(1))))
    for name, sg in HM.items():
        for m in re.finditer(rf"(?<![a-z0-9/]){re.escape(_norm(name))}(?![a-z0-9/])", t):
            pos.append((m.start(), sg))
    sgs = list(dict.fromkeys(sg for _, sg in sorted(pos)))
    mine = [k for k, v in TRANSITIONS.items() if v["system"] == s]
    if len(sgs) >= 2:
        d["parent_sg"], d["child_sg"] = sgs[0], sgs[1]
        tr = [k for k in mine if (TRANSITIONS[k]["parent_sg"], TRANSITIONS[k]["child_sg"]) == (sgs[0], sgs[1])]
        if not tr:
            return {**d, "out_of_scope": True, "out_of_scope_reason": f"no stored transition #{sgs[0]} -> #{sgs[1]}"}
        d["transition"] = tr[0]
    elif len(mine) == 1:
        d["transition"] = mine[0]
    else:
        return {**d, "clarify_field": "transition", "question": "Which transition?"}
    return d
