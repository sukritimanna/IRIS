"""f0 language-model step, code half: draft intent (from the model or the keyword baseline) -> config.yaml + intent.json.

The model fills only the intent fields (intake/schema.py). Code fills everything else from the policy template the
intent selects (an E1 config), records the source of every field (request / model / default), and writes the intake
verdict into config['intake'] for G0:
  status ok            every required field decided, the (transition, analysis) has a policy template
  status ambiguous     a required field is undecidable, or the model asked -> G0 AMBIGUOUS with ONE listed question
  status out_of_scope  no stored group-subgroup route / unsupported engine or analysis / model refused -> G0 OUT_OF_SCOPE
  checks               field-consistency errors G0 reports as SCHEMA (profile of another system, SG pair != transition,
                       strain policy not valid for the analysis, ...)
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

import yaml

from .library import (ANALYSES, MP_IDS, OUTPUTS, PAPER_TO_CODE, STRAIN_OK, STRAIN_POLICIES,
                      SYSTEMS, TEMPLATES, TRANSITIONS, load_config, profiles)

INTENT_FIELDS = ["system", "formula", "parent_sg", "child_sg", "transition", "analysis", "strain_policy", "system_profile",
                 "budget", "outputs"]
QUESTIONS = {      # the listed questions G0 AMBIGUOUS may ask (one per undecidable field)
    "system": "Which system: " + ", ".join(SYSTEMS) + "?",
    "transition": "Which transition (parent -> child)?",
    "analysis": "Which analysis: " + ", ".join(ANALYSES) + "?",
    "strain_policy": "Fixed lattice (P1), stated cell (P2) or strain interpolated along the path (P3)?",
    "system_profile": "Which system profile (functional / magnetic order)?",
    "budget": "What is the run budget (DFT runs)?",
    "outputs": "Which outputs do you need?",
}
DEFAULT_ANALYSIS = {"cssni3": "plane", "ca3ti2o7": "plane", "inmno3": "plane", "ermno3": "plane", "bifeo3": "grid6d",
                    "hfo2": "path"}


def _transitions_of(system):
    return [t for t, v in TRANSITIONS.items() if v["system"] == system]


def attachments(att: list[str]) -> dict:
    """Code reads the attachments (MP ids, CIF names): system and space groups, source = request."""
    out = {}
    for a in att or []:
        if a in MP_IDS:
            s, sg = MP_IDS[a]
            out.setdefault("system", s)
            out.setdefault("sgs", []).append(sg)
    return out


def resolve(draft: dict, att: list[str] | None = None) -> dict:
    """draft (model or baseline output) -> intent with sources, verdict, the template it selects."""
    prof = profiles()
    d = {k: draft.get(k) for k in INTENT_FIELDS}
    d["outputs"] = [o for o in (draft.get("outputs") or []) if o in OUTPUTS]
    src = {k: ("model" if d[k] not in (None, []) else None) for k in INTENT_FIELDS}
    fromreq = attachments(att or [])
    if d["system"] is None and fromreq.get("system"):
        d["system"], src["system"] = fromreq["system"], "request"
    checks, status, question, reason = [], "ok", None, None
    asked = draft.get("clarify_field")
    if draft.get("out_of_scope"):
        status, reason = "out_of_scope", draft.get("out_of_scope_reason") or "the model refused the request"
    elif asked:
        status, question = "ambiguous", QUESTIONS.get(asked, QUESTIONS["analysis"])
    # a material named as new but stored under its formula is the stored system
    if d["system"] == "new" and d.get("formula"):
        f = re.sub(r"\s+", "", d["formula"]).lower()
        hit = [s_ for s_ in SYSTEMS if s_ == f]
        if hit:
            d["system"], src["system"] = hit[0], "default"
    if status == "ok" and d["system"] == "new":
        return _new_material(d, src, prof)
    # transition: from the SG pair, or the only stored transition of the system
    if status == "ok":
        if d["system"] is None and d["transition"]:
            d["system"], src["system"] = TRANSITIONS[d["transition"]]["system"], "default"
        if d["system"] is None:
            status, question = "ambiguous", QUESTIONS["system"]
    if status == "ok":
        pair = (d["parent_sg"], d["child_sg"])
        if None not in pair and d["transition"] is None:
            hit = [t for t in _transitions_of(d["system"]) if (TRANSITIONS[t]["parent_sg"], TRANSITIONS[t]["child_sg"]) == pair]
            if hit:
                d["transition"], src["transition"] = hit[0], "default"
            else:
                status, reason = "out_of_scope", f"no stored group-subgroup route {pair[0]} -> {pair[1]} for {d['system']}"
        if status == "ok" and d["transition"] is None:
            tt = _transitions_of(d["system"])
            if len(tt) == 1:
                d["transition"], src["transition"] = tt[0], "default"
            else:
                status, question = "ambiguous", "Which transition: " + ", ".join(
                    f"#{TRANSITIONS[t]['parent_sg']} -> #{TRANSITIONS[t]['child_sg']}" for t in tt) + "?"
    if status == "ok":
        tr = TRANSITIONS[d["transition"]]
        if tr["system"] != d["system"]:
            checks.append(f"transition {d['transition']} is not a {d['system']} transition")
        for k in ("parent_sg", "child_sg"):
            if d[k] is None:
                d[k], src[k] = tr[k], "default"
            elif d[k] != tr[k]:
                checks.append(f"{k} {d[k]} != {tr[k]} of transition {d['transition']}")
        if d["analysis"] is None:
            d["analysis"], src["analysis"] = DEFAULT_ANALYSIS[d["system"]], "default"
        want_d4 = "d4_secondary_check" in d["outputs"]
        tpl = TEMPLATES.get((d["transition"], d["analysis"], want_d4))
        if tpl is None:
            status, reason = "out_of_scope", (f"no policy template for {d['analysis']}"
                                              f"{' + D4' if want_d4 else ''} on {d['transition']} in this build")
    tpl_cfg = None
    if status == "ok":
        tpl_cfg = load_config(tpl)
        dflt = {"strain_policy": {"P2": "P1", "P5": "P3"}[tpl_cfg["policy"]["strain_policy"]], "system_profile": Path(tpl_cfg["paths"]["system_json"]).stem,
                "budget": tpl_cfg["run"]["budget_runs"]}
        for k, v in dflt.items():
            if d[k] is None:
                d[k], src[k] = v, "default"
        if not d["outputs"]:
            src["outputs"] = "default"
        if "not implemented" in STRAIN_POLICIES.get(d["strain_policy"], ""):
            status, reason = "out_of_scope", f"strain policy {d['strain_policy']} is not implemented in this build"
        elif d["strain_policy"] not in STRAIN_OK[d["analysis"]]:
            checks.append(f"strain policy {d['strain_policy']} is not valid for analysis {d['analysis']}")
        p = prof.get(d["system_profile"])
        if p is None:
            checks.append(f"unknown system profile {d['system_profile']}")
        elif p["system"] != d["system"]:
            checks.append(f"profile {d['system_profile']} is for {p['system']}, not {d['system']}")
        if not isinstance(d["budget"], int) or isinstance(d["budget"], bool):
            checks.append(f"budget {d['budget']!r} is not an integer")
    return {"intent": d, "sources": src, "status": status, "question": question, "reason": reason, "checks": checks,
            "template": tpl if status == "ok" else None,
            "model_question": draft.get("question"), "model_clarify_field": asked}


def _new_material(d: dict, src: dict, prof: dict) -> dict:
    """A material with no stored campaign: a complete intent is valid (status needs_new_dft, G0 NEEDS_NEW_DFT, nothing
    runs in replay); no template, no profile of another material."""
    checks, missing = [], [k for k in ("formula", "parent_sg", "child_sg", "analysis") if d.get(k) in (None, "")]
    status, question, reason = "needs_new_dft", None, f"no stored data for {d.get('formula')}: the campaign needs new DFT"
    if missing:
        status, question, reason = "ambiguous", QUESTIONS.get(missing[0] if missing[0] != "formula" else "system",
                                                              "Which structures (parent and child)?"), None
    if d.get("strain_policy") is None and d.get("analysis"):
        d["strain_policy"], src["strain_policy"] = ("P3" if d["analysis"] == "path" else "P1"), "default"
    if d.get("strain_policy") and d.get("analysis") and d["strain_policy"] not in STRAIN_OK[d["analysis"]]:
        checks.append(f"strain policy {d['strain_policy']} is not valid for analysis {d['analysis']}")
    p = prof.get(d.get("system_profile")) if d.get("system_profile") else None
    if d.get("system_profile") and p is None:
        checks.append(f"unknown system profile {d['system_profile']}")
    elif p is not None and re.sub(r"\s+", "", p["formula"]).lower() != re.sub(r"\s+", "", d.get("formula") or "").lower():
        checks.append(f"profile {d['system_profile']} is for {p['formula']}, not {d.get('formula')} (borrowed profile)")
    if d.get("transition"):
        checks.append(f"transition {d['transition']} is a stored transition of another system")
    return {"intent": d, "sources": src, "status": status, "question": question, "reason": reason, "checks": checks,
            "template": None, "model_question": None, "model_clarify_field": None}


def build_config(res: dict, request: str, thread: str) -> dict:
    """The run config: the template, the intent fields applied, the verdict in config['intake']."""
    if res["template"]:
        cfg = deepcopy(load_config(res["template"]))
        it = res["intent"]
        cfg["policy"]["strain_policy"] = PAPER_TO_CODE[it["strain_policy"]]     # the code label (G0 schema)
        cfg["run"]["budget_runs"] = it["budget"]
        cfg["paths"]["system_json"] = str(Path(cfg["paths"]["system_json"]).with_name(f"{it['system_profile']}.json"))
    else:                      # nothing to run: a minimal config G0 can read (the intake verdict fails first)
        base = load_config("cssni3")
        cfg = {"system": res["intent"].get("system") or "unknown", "run": {**base["run"]}, "paths": dict(base["paths"]),
               "policy": {}, "retry": base["retry"], "llm": base["llm"]}
        for k in ("parent_cif", "child_cif", "system_json"):
            cfg["paths"][k] = ""
    cfg["thread_id"] = thread
    cfg["request"] = request
    cfg["run"]["mode"] = "replay"
    cfg["intake"] = {k: res[k] for k in ("status", "question", "reason", "checks", "template", "model_question",
                                         "model_clarify_field")}
    cfg["intake"]["intent"] = res["intent"]
    cfg["intake"]["sources"] = res["sources"]
    return cfg


def write(res: dict, request: str, thread: str, out_dir: Path) -> tuple[Path, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = build_config(res, request, thread)
    body = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=140)
    (out_dir / "config.yaml").write_text(body)
    (out_dir / "intent.json").write_text(json.dumps({"request": request, **res}, indent=1, default=str))
    # the hash of what would run: the config without the per-call bookkeeping
    run_part = {k: v for k, v in cfg.items() if k not in ("thread_id", "request", "intake")}
    run_part["paths"] = {k: v for k, v in run_part.get("paths", {}).items() if k not in ("repo_root", "agent_root")}
    h = hashlib.sha256(json.dumps(run_part, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return out_dir / "config.yaml", h


# ---- G0 tests (gates.py calls these on state['config']['intake']) ------------------------------------------------
def g0_in_scope(cfg: dict):
    it = cfg.get("intake") if isinstance(cfg, dict) else None
    if it and it.get("status") == "out_of_scope":
        return ("OUT_OF_SCOPE", it.get("reason") or "out of scope")
    return None


def g0_decidable(cfg: dict):
    it = cfg.get("intake") if isinstance(cfg, dict) else None
    if it and it.get("status") == "ambiguous":
        return ("AMBIGUOUS", it.get("question") or QUESTIONS["analysis"])
    return None


def g0_stored_data(cfg: dict):
    it = cfg.get("intake") if isinstance(cfg, dict) else None
    if it and it.get("status") == "needs_new_dft":
        return ("NEEDS_NEW_DFT", it.get("reason") or "no stored data: new DFT needed")
    return None


def g0_consistent(cfg: dict):
    it = cfg.get("intake") if isinstance(cfg, dict) else None
    if it and it.get("checks"):
        return ("SCHEMA", "intake: " + "; ".join(it["checks"]))
    return None


_ = re  # noqa
