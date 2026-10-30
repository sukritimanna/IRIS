"""recover: the only place a gate failure is handled.

Order: rule table (recovery.yaml) -> the failing gate's sub-agent (LLM picks one listed option)
-> human via interrupt(). The retry budget per node lives in state["attempts"]; once it is used up,
recover goes straight to the human. The LLM never routes: the route comes from the chosen fix
("goto") or defaults to re-running the failing node.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml
from langgraph.types import interrupt

from .state import GATE_OF, NODES


class RecoveryTable:
    def __init__(self, path: str | Path):
        data = yaml.safe_load(Path(path).read_text())
        self.rules = data.get("rules", [])
        self.options = data.get("options", {})
        ids = [r["id"] for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule ids in recovery.yaml")

    def lookup(self, node: str, code: str) -> dict | None:
        return next((r for r in self.rules if r["node"] == node and r["code"] == code), None)

    def menu(self, node: str) -> list[dict]:
        return self.options.get(node, [])


def _rule_fix(rule: dict, times_used: int) -> dict | None:
    """The patch for this application of the rule, or None if the rule is used up."""
    if "ladder" in rule:
        (key, steps), = rule["ladder"].items()
        return {key: steps[times_used]} if times_used < len(steps) else None
    return dict(rule["fix"]) if times_used == 0 else None


def _merge(a: dict, b: dict) -> dict:
    out = deepcopy(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def make_recover(table: RecoveryTable, audit, subagent):
    """subagent(node, gate, options, state) -> {"id", "reason"} or {"status": why-not}."""

    def recover(state: dict) -> dict:
        node, gate = state["last_node"], state["gate"]
        code = gate.get("code")
        cfg = state["config"]
        max_retry = cfg["retry"]["max_per_node"]
        attempts = dict(state.get("attempts", {}))
        used = attempts.get(node, 0)
        applied = [a for a in state.get("history", []) if a.get("rule")]
        fix, level, meta = None, None, {}
        llm_meta = None
        abl = set((state.get("run_meta") or {}).get("ablation_flags") or [])

        fh = (state.get("run_meta") or {}).get("fork_human")       # Experiment C: one decision injected by hand
        forked_here = bool(fh) and fh.get("node") == node and fh.get("code") == code and used == fh.get("attempts") \
            and not any(h.get("fork_point") for h in state.get("history", []))
        if forked_here:
            meta = {"fork_point": True, "subagent": "not asked (Experiment C fork: the option is injected)"}
        elif used < max_retry:
            rule = None if "no-rules" in abl else table.lookup(node, code)
            if rule:
                missing = [r for r in rule.get("requires", []) if not cfg.get(r, {}).get("enabled")]
                times = sum(1 for a in applied if a["rule"] == rule["id"])
                if not missing:
                    fix = _rule_fix(rule, times)
                    if fix is not None:
                        level, meta = "rule", {"rule": rule["id"], "source": rule.get("source", "")}
                    else:
                        meta = {"rule_used_up": rule["id"]}
                else:
                    meta = {"rule_skipped": rule["id"], "missing": missing}
            if fix is None and "no-subagents" in abl:
                meta["subagent"] = "ablated (no-subagents)"
            elif fix is None and all(o["id"] == "stop" for o in table.menu(node)):
                meta["subagent"] = "not asked (the menu has only stop)"
            elif fix is None:
                menu = table.menu(node)
                choice = subagent(node, gate, menu, state) or {}
                meta["subagent"] = choice.get("status", "answered")
                if choice.get("llm"):
                    llm_meta = choice["llm"]
                if choice.get("invalid_id"):
                    meta["subagent_invalid"] = choice["invalid_id"]
                if choice.get("id"):
                    opt = next((o for o in menu if o["id"] == choice.get("id")), None)
                    if opt is None:      # an answer outside the menu is ignored, never applied
                        meta["subagent_invalid"] = choice.get("id")
                    else:
                        fix, level = dict(opt["patch"]), "subagent"
                        meta.update({"option": opt["id"], "reason": choice.get("reason", "")})
        else:
            meta = {"retry_budget_used": used}

        if fix is None:
            # Human. On resume LangGraph re-runs this node from the top and interrupt() returns the
            # human's answer; everything above is deterministic, so it reaches this point again.
            answer = interrupt({"kind": "human", "node": node, "gate": GATE_OF[node], "code": code,
                                "detail": gate.get("detail", ""), "options": table.menu(node),
                                "why_human": meta, "attempts": used})
            level = "human"
            if isinstance(answer, dict) and answer.get("option"):
                opt = next((o for o in table.menu(node) if o["id"] == answer["option"]), None)
                fix = dict(opt["patch"]) if opt else {"abort": True}
                if opt:
                    meta["option"] = opt["id"]                 # -> audit option_id for human choices too
            elif isinstance(answer, dict) and "fix" in answer:
                fix = dict(answer["fix"])
            else:
                fix = {"abort": True}
            meta.update({"human_answer": answer})

        attempts[node] = used + 1
        if fix.get("abort"):
            route = "END"
        else:
            route = fix.get("goto", node)
            if route not in NODES:
                route = "END"
        overrides = dict(state.get("overrides", {}))
        patch = {k: v for k, v in fix.items() if k not in ("goto", "abort")}
        target = route if route in NODES else node        # the patch configures the node that re-runs
        if patch:
            overrides[target] = _merge(overrides.get(target, {}), patch)
        entry = {"node": node, "code": code, "level": level, "fix": fix, "route": route, **meta}
        audit.write("fix", node, gate=GATE_OF[node], gate_code=code, code=code, level=level,
                    recovery_tier=level, rule_id=meta.get("rule"), option_id=meta.get("option"),
                    output_valid=(bool(llm_meta.get("valid")) if llm_meta is not None
                                  else None if level != "subagent" and "subagent_invalid" not in meta
                                  else "subagent_invalid" not in meta),
                    tokens_in=(llm_meta or {}).get("tokens_in"), tokens_out=(llm_meta or {}).get("tokens_out"),
                    cost_usd=(llm_meta or {}).get("cost_usd"),
                    llm=(None if llm_meta is None else {k: llm_meta.get(k) for k in (
                        "name", "provider", "model", "model_version", "mode", "temperature", "seed",
                        "constrained_decoding", "answered_id", "valid", "error", "tokens_reasoning", "latency_s",
                        "transport_retries", "option_order", "prompt_sha256", "system_fingerprint")}),
                    fix=fix, route=route, attempts=attempts[node], **meta)
        return {"overrides": overrides, "attempts": attempts, "route": route,
                "history": state.get("history", []) + [entry]}

    return recover
