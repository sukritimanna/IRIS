"""Run or resume one IRIS thread.

  python -m iris_agent.run --config configs/cssni3.yaml                     # thread from the config
  python -m iris_agent.run --config configs/cssni3.yaml --mode replay --llm off --tag E1   # thread E1_cssni3
  python -m iris_agent.run --config configs/cssni3.yaml --tag E4 --ablate no-gates
  python -m iris_agent.run --config configs/cssni3.yaml --resume '{"option": "stop"}'
  python -m iris_agent.run --config configs/cssni3.yaml --continue          # after a crash/kill
  python -m iris_agent.run --config configs/cssni3.yaml --status

--fresh deletes an existing thread folder (inside IRIS_AGENT/test_runs only) before starting.
--llm off | <name in eval/models.yaml> (build step 5: sub-agents; --models to use another models file).

Checkpoints: <agent_root>/<test_runs>/<thread_id>/iris.sqlite (SqliteSaver, one thread per system).
Audit log:   <agent_root>/<test_runs>/<thread_id>/audit.jsonl
Nothing is written outside agent_root (paths.Paths.out refuses).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import time
import uuid
from importlib import metadata
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from . import config as cfgmod
from .audit import AuditLog
from .graph import build
from .llm import make_subagent
from .paths import Paths

RECURSION_LIMIT = 200
DURABILITY = "sync"     # write each checkpoint before the next node starts: a crash never loses a finished node
ABLATIONS = ("no-gates", "no-g0", "no-g1", "no-g2", "no-g3", "no-g4", "no-g5", "no-g6", "no-rules", "no-subagents")


def _versions() -> dict:
    out = {"python": sys.version.split()[0]}
    for pkg in ("langgraph", "langgraph-checkpoint-sqlite", "pymatgen", "spglib"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = None
    return out


class Session:
    """Opens the checkpointer + audit log for one config/thread; use as a context manager."""

    def __init__(self, config_path: str | Path, thread_id: str | None = None, *, tag: str | None = None,
                 llm: str = "off", mode: str | None = None, ablations=(), fault_id: str | None = None,
                 fresh: bool = False, models: str | Path | None = None, llm_overrides: dict | None = None,
                 transport=None):
        self.config_path = Path(config_path).expanduser().resolve()
        raw = cfgmod.load(self.config_path)
        p = raw["paths"]
        self.paths = Paths(p["repo_root"], p["agent_root"],
                           {k: v for k, v in p.items() if k not in ("repo_root", "agent_root")})
        spec = None
        if llm != "off":
            from .llm import MODELS_YAML, load_models
            mods = load_models(models or MODELS_YAML)
            if llm not in mods:
                raise SystemExit(f"--llm {llm!r} not in {models or MODELS_YAML}; known: {sorted(mods)}")
            spec = {**mods[llm], **(llm_overrides or {})}
            if not spec.get("model"):
                raise SystemExit(f"--llm {llm!r}: no model id pinned in the models file")
        self._transport = transport
        bad = [a for a in ablations if a not in ABLATIONS]
        if bad:
            raise SystemExit(f"unknown ablation(s) {bad}; known: {ABLATIONS}")
        self.thread_id = thread_id or (f"{tag}_{raw['system']}" if tag else raw["thread_id"])
        if fresh:
            d = self.paths.out(p.get("test_runs", "test_runs"), self.thread_id)
            if d.exists():
                shutil.rmtree(d)
        self.run_dir = self.paths.run_dir(self.thread_id)
        self.meta = {"run_id": f"{self.thread_id}-{uuid.uuid4().hex[:8]}", "tag": tag, "system": raw.get("system"),
                     "fault_id": fault_id, "ablation_flags": sorted(ablations), "mode": mode,
                     "provider": None if not spec else spec["provider"],
                     "model_version": None if not spec else spec["model"],
                     "temperature": None if not spec else spec.get("temperature"),
                     "seed": None if not spec else spec.get("seed"),
                     "constrained_decoding": None if not spec else spec.get("mode", "constrained"),
                     "option_order_seed": None if not spec or not spec.get("shuffle_options") else spec.get("option_order_seed", 0),
                     "llm": llm, "llm_spec": spec}
        self.audit = AuditLog(self.paths.out(self.run_dir, "audit.jsonl"), self.thread_id)
        self.recovery = self.paths.agent_root / p.get("recovery", "recovery.yaml")
        self.raw = raw

    def __enter__(self):
        db = self.paths.out(self.run_dir, "iris.sqlite")
        self._conn = sqlite3.connect(str(db), check_same_thread=False)
        from .llm import http_json
        sub = make_subagent(transport=self._transport or http_json,
                            calls_log=self.paths.out(self.run_dir, "llm_calls.jsonl"))
        self.graph = build(self.audit, self.recovery, sub).compile(
            checkpointer=SqliteSaver(self._conn))
        self.cfg = {"configurable": {"thread_id": self.thread_id}, "recursion_limit": RECURSION_LIMIT}
        stored = self.graph.get_state(self.cfg).values.get("run_meta")
        if stored:                                   # resuming: the thread keeps its original run context
            self.meta = stored
        self.audit.set_context(**self.meta)
        return self

    def __exit__(self, *exc):
        self._conn.close()

    # ---------------------------------------------------------------------------------------
    def start(self) -> dict:
        st = self.graph.get_state(self.cfg)
        if st.next:
            raise SystemExit(f"thread {self.thread_id!r} is paused; use --resume/--continue (or --thread NEW)")
        if st.values:
            raise SystemExit(f"thread {self.thread_id!r} already ran (see {self.run_dir}); use --thread NEW or --fresh")
        self.audit.write("run", None, event="start", config=str(self.config_path),
                         config_sha256=hashlib.sha256(self.config_path.read_bytes()).hexdigest(),
                         mode=self.meta.get("mode") or self.raw.get("run", {}).get("mode"), versions=_versions())
        self._t0 = time.monotonic()
        out = self.graph.invoke({"request": self.raw.get("request", ""), "thread_id": self.thread_id,
                                 "config_path": str(self.config_path), "run_meta": self.meta,
                                 "overrides": {}, "attempts": {}, "history": []}, self.cfg,
                                durability=DURABILITY)
        return self._after(out)

    def resume(self, answer) -> dict:
        self.audit.write("resume", None, answer=answer)
        self._t0 = time.monotonic()
        out = self.graph.invoke(Command(resume=answer), self.cfg, durability=DURABILITY)
        return self._after(out)

    def cont(self) -> dict:
        """Continue a thread whose process died between nodes (no pending interrupt)."""
        st = self.graph.get_state(self.cfg)
        if not st.next:
            raise SystemExit(f"thread {self.thread_id!r} has nothing to continue")
        if st.interrupts:
            raise SystemExit(f"thread {self.thread_id!r} is paused for an answer; use --resume or jobend")
        self.audit.write("resume", None, answer="continue after interruption", next=list(st.next))
        self._t0 = time.monotonic()
        out = self.graph.invoke(None, self.cfg, durability=DURABILITY)
        return self._after(out)

    def status(self) -> dict:
        st = self.graph.get_state(self.cfg)
        return {"next": list(st.next), "interrupts": [i.value for i in st.interrupts],
                "last_node": st.values.get("last_node"), "gate": st.values.get("gate"),
                "attempts": st.values.get("attempts"), "run_meta": st.values.get("run_meta")}

    def _after(self, out: dict) -> dict:
        intr = out.get("__interrupt__")
        wall = round(time.monotonic() - getattr(self, "_t0", time.monotonic()), 3)
        if intr:
            payload = [i.value for i in intr]
            kind = payload[0].get("kind", "human")
            if kind == "job_wait":
                p0 = payload[0]
                self.audit.write("interrupt", p0.get("node"), waiting_on="jobs", wall_time_s=wall,
                                 parts_pending=len(p0["parts_pending"]), n_parts=p0["n_parts"])
                return {"status": "waiting_on_jobs", "parts_pending": p0["parts_pending"],
                        "n_parts": p0["n_parts"], "interrupt": payload}
            self.audit.write("interrupt", payload[0].get("node"), waiting_on="human", payload=payload,
                             wall_time_s=wall)
            return {"status": "interrupted", "interrupt": payload}
        gate = out.get("gate", {})
        if out.get("last_node") == "f6" and gate.get("ok"):
            status = "completed"
        elif gate.get("ok") and out.get("last_node") == ((out.get("config") or {}).get("run") or {}).get("stop_after"):
            status = "stage_completed"
        elif gate.get("code") == "NODE_ERROR" and "no-gates" in (self.meta.get("ablation_flags") or []):
            status = "crashed"
        else:
            status = "stopped"
        g6 = [{"quantity": r["name"], "reported": r["value"], "rederived": r["rederived"], "match": r["ok"]}
              for r in (out.get("report") or {}).get("rows", [])]
        self.audit.write("end", None, status=status, last_node=out.get("last_node"), gate_code=gate.get("code"),
                         outcome=status, route=out.get("route"), wall_time_s=wall, g6_table=g6,
                         attempts=out.get("attempts"))
        return {"status": status, "last_node": out.get("last_node"), "gate": gate}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--thread", default=None, help="override thread_id from the config")
    ap.add_argument("--resume", default=None, help="JSON answer for a pending human interrupt")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--continue", dest="cont", action="store_true", help="continue after a crash/kill")
    ap.add_argument("--tag", default=None, help="evaluation tag (E1, E4, ...); default thread <tag>_<system>")
    ap.add_argument("--llm", default="off", help="'off' or a model name from eval/models.yaml (sub-agents)")
    ap.add_argument("--models", default=None, help="models file (default eval/models.yaml)")
    ap.add_argument("--mode", default=None, choices=["skeleton", "replay", "live"], help="override run.mode")
    ap.add_argument("--ablate", default="", help=f"comma list of {','.join(ABLATIONS)}")
    ap.add_argument("--no-gates", action="store_true", help="same as --ablate no-gates")
    ap.add_argument("--fresh", action="store_true", help="delete this thread's folder first")
    a = ap.parse_args(argv)
    abl = [x for x in a.ablate.split(",") if x] + (["no-gates"] if a.no_gates else [])
    with Session(a.config, a.thread, tag=a.tag, llm=a.llm, mode=a.mode, ablations=abl, fresh=a.fresh,
                 models=a.models) as s:
        if a.status:
            res = s.status()
        elif a.resume is not None:
            res = s.resume(json.loads(a.resume))
        elif a.cont:
            res = s.cont()
        else:
            res = s.start()
    if res.get("status") == "waiting_on_jobs":
        res = {k: v for k, v in res.items() if k != "interrupt"}
    print(json.dumps(res, indent=1, default=str))
    if res.get("status") == "waiting_on_jobs":
        print(f"\nIRIS is waiting for {len(res['parts_pending'])} of {res['n_parts']} job parts (f3). When they end:\n"
              f"  python -m iris_agent.jobend --config {a.config} --thread {s.thread_id} [--parts 0-9] [--fail 3:WALLTIME]",
              file=sys.stderr)
    if res.get("status") == "interrupted":
        print("\n" + human_message(res["interrupt"][0], a.config, s.thread_id), file=sys.stderr)
    return 0


def human_message(payload: dict, config_path, thread_id: str) -> str:
    from .prompts import render
    from .state import NODE_NAMES
    opts = "\n".join(f"  {o['id']:24} {o['text']}" for o in payload.get("options", []))
    return render("human_interrupt", node=payload["node"], node_name=NODE_NAMES[payload["node"]],
                  gate=payload["gate"], code=payload["code"], detail=payload.get("detail", ""),
                  why_human=json.dumps(payload.get("why_human", {})), options=opts,
                  attempts=payload.get("attempts", 0), thread_id=thread_id,
                  config_path=config_path)["user"]


if __name__ == "__main__":
    raise SystemExit(main())
