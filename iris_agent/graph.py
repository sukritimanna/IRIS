"""IRIS as one LangGraph StateGraph:

START -> f0 -G0-> f1 -G1-> f2 -G2-> f3 -G3-> f4 -G4-> f5 -G5-> f6 -G6-> END

Each node runs its engine wrapper, then its gate (plain Python) on the output. Gate pass -> next
node; gate fail -> `recover` (rule table -> sub-agent -> human interrupt), which routes back to the
failing node, to a node named by the fix (e.g. G5 coverage -> f2), or to END on abort.

Ablations (state["run_meta"]["ablation_flags"], for the evaluation):
  no-gates  gates still run and are logged (outcome "fail_ignored") but never stop the run; a node
            that crashes (NODE_ERROR) ends it ("crashed") — an ungated pipeline has no recovery
  no-g6     G6 is not evaluated (outcome "skipped")
  no-g0 .. no-g5  that one gate still runs and is logged ("fail_ignored") but never stops the run (E9)
  no-rules / no-subagents  handled in recover.py
"""
from __future__ import annotations

import os
import time

from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph

from .gates import run_gate
from .nodes import FUNCS
from .nodes._stub import stub
from .recover import RecoveryTable, make_recover
from .state import GATE_OF, NODE_NAMES, NODES, IrisState

STUB_KEY = {"f1": "decomposition", "f2": "grid", "f3": "jobs", "f4": "energies", "f5": "model", "f6": "report"}
KILL_ENV = "IRIS_KILL_BEFORE"          # test hook for resume_test: hard-exit before this node runs


def _plain(obj):
    """Node outputs go into the SQLite checkpoint: convert numpy scalars/arrays to plain Python."""
    import json

    import numpy as np

    def conv(x):
        if isinstance(x, np.generic):
            return x.item()
        if isinstance(x, np.ndarray):
            return x.tolist()
        raise TypeError(f"not serializable: {type(x).__name__}")
    return json.loads(json.dumps(obj, default=conv))


def _summary(out: dict) -> dict:
    """Short, log-safe view of what a node produced (keys and sizes, not the data)."""
    s = {}
    for k, v in out.items():
        if k in ("last_node",):
            continue
        if isinstance(v, dict):
            s[k] = {"keys": sorted(v)[:20], "stub": bool(v.get("stub"))}
        elif isinstance(v, (list, tuple)):
            s[k] = {"len": len(v)}
        else:
            s[k] = str(v)[:200]
    return s


def ablations(state: dict) -> set:
    rm = state.get("run_meta") or {}
    flags = set(rm.get("ablation_flags") or [])
    if rm.get("gates_off_after_fork") and any(h.get("fork_point") for h in state.get("history", [])):
        flags.add("no-gates")                    # Experiment C2: the downstream gates are off after the fork
    return flags


def _wrap(name: str, fn, audit):
    gate_name = GATE_OF[name]

    def node(state: dict) -> dict:
        if os.environ.get(KILL_ENV) == name:
            audit.write("kill", name, event="test hook: process killed before this node")
            os._exit(137)
        abl = ablations(state)
        attempt = state.get("attempts", {}).get(name, 0)
        audit.write("node", name, event="start", title=NODE_NAMES[name], attempts=attempt)
        t0 = time.monotonic()
        if state.get("config", {}).get("run", {}).get("mode") == "skeleton" and name != "f0":
            out = stub(name, STUB_KEY[name], ["(skeleton mode)"], state)
        else:
            try:
                out = _plain(fn(state))
            except GraphBubbleUp:                    # interrupt(): LangGraph pauses the thread here
                raise
            except Exception as exc:                 # a crashing node is a failing gate, not a crash
                import traceback
                out = {STUB_KEY.get(name, "inputs"): {"error": f"{type(exc).__name__}: {exc}"}}
                gate = {"ok": False, "gate": gate_name, "code": "NODE_ERROR",
                        "detail": f"{type(exc).__name__}: {exc}",
                        "tests": [{"test": "node_ran", "status": "fail",
                                   "trace": traceback.format_exc()[-1500:]}]}
                audit.write("node", name, event="error", detail=gate["detail"],
                            wall_time_s=round(time.monotonic() - t0, 3))
                audit.write("gate", name, gate=gate_name, gate_code="NODE_ERROR", outcome="fail", ok=False,
                            code="NODE_ERROR", detail=gate["detail"], tests=gate["tests"], attempts=attempt)
                return {**out, "last_node": name, "gate": gate,
                        "history": state.get("history", []) + [{"node": name, "gate": gate_name,
                                                                "code": "NODE_ERROR"}]}
        wall = round(time.monotonic() - t0, 3)
        if name == "f6" and "no-g6" in abl:
            gate = {"ok": True, "gate": gate_name, "code": "SKIPPED", "detail": "ablation no-g6", "tests": []}
            outcome = "skipped"
        else:
            gate = run_gate(gate_name, {**state, **out})
            outcome = "pass" if gate["ok"] else "fail"
            if not gate["ok"] and ("no-gates" in abl or f"no-{gate_name.lower()}" in abl):
                gate = {**gate, "ok": True, "ignored": True}
                outcome = "fail_ignored"
        audit.write("node", name, event="done", output=_summary(out), wall_time_s=wall)
        audit.write("gate", name, gate=gate_name, gate_code=gate["code"], outcome=outcome, ok=gate["ok"],
                    code=gate["code"], detail=gate["detail"], tests=gate["tests"], attempts=attempt)
        return {**out, "last_node": name, "gate": gate,
                "history": state.get("history", []) + [{"node": name, "gate": gate_name, "code": gate["code"],
                                                        "outcome": outcome}]}

    return node


def build(audit, recovery_path, subagent):
    table = RecoveryTable(recovery_path)
    g = StateGraph(IrisState)
    for n in NODES:
        g.add_node(n, _wrap(n, FUNCS[n], audit))
    g.add_node("recover", make_recover(table, audit, subagent))
    g.add_edge(START, "f0")
    for i, n in enumerate(NODES):
        nxt = NODES[i + 1] if i + 1 < len(NODES) else END

        def route(s, nxt=nxt, n=n):
            if s["gate"]["ok"]:
                if nxt != END and s.get("config", {}).get("run", {}).get("stop_after") == n:
                    return END                       # staged replay: this stage ends after its gate
                return nxt
            return END if "no-gates" in ablations(s) else "recover"       # ungated: a crash ends the run
        g.add_conditional_edges(n, route, {nxt: nxt, "recover": "recover", END: END} if nxt != END
                                else {END: END, "recover": "recover"})
    g.add_conditional_edges("recover", lambda s: s["route"], {**{n: n for n in NODES}, "END": END})
    return g
