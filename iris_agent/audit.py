"""Audit log: one JSON line per run / node / gate / fix / interrupt / resume / end event.

Write-only and separate from the data flow. Every line carries the run context (the runbook's
audit fields): run_id, tag, system, fault_id, ablation_flags and the model fields (provider,
model_version, temperature, seed, constrained_decoding — null while the LLM is off). Event-specific
fields are added by the writer: gate_code + outcome on gate lines, recovery_tier / rule_id /
option_id / output_valid / tokens on fix lines, wall_time_s on node lines, the G6 table on the end line.

Values that look like secrets are never written: the API key is read from the environment by the LLM
client only and never enters state or logs.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

KINDS = {"run", "node", "gate", "fix", "subagent", "decision", "interrupt", "resume", "end", "kill"}
CONTEXT_FIELDS = ("run_id", "tag", "system", "fault_id", "task_id", "task_level", "ablation_flags",
                  "provider", "model_version", "temperature", "seed", "constrained_decoding",
                  "prompt_variant_id", "option_order_seed")
_SECRET_KEY = re.compile(r"(api[_-]?key|token(?!s_)|secret|password)", re.I)
_KEY_ENVS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "OPENAI_COMPAT_API_KEY", "DEEPSEEK_API_KEY")


def _scrub(obj):
    if isinstance(obj, dict):
        return {k: ("<redacted>" if _SECRET_KEY.search(str(k)) and k not in ("tokens_in", "tokens_out")
                    else _scrub(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_scrub(v) for v in obj]
    if isinstance(obj, str):
        for env in _KEY_ENVS:
            key = os.environ.get(env)
            if key and key in obj:
                obj = obj.replace(key, "<redacted>")
    return obj


class AuditLog:
    def __init__(self, path: Path, thread_id: str, context: dict | None = None):
        self.path = Path(path)
        self.thread_id = thread_id
        self.context = dict.fromkeys(CONTEXT_FIELDS)
        self.context.update(context or {})
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def set_context(self, **ctx):
        self.context.update({k: v for k, v in ctx.items() if k in CONTEXT_FIELDS})

    def write(self, kind: str, node: str | None = None, **payload) -> dict:
        if kind not in KINDS:
            raise ValueError(f"unknown audit kind {kind!r}")
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
               "thread_id": self.thread_id, **self.context, "kind": kind, "node": node, **_scrub(payload)}
        with self.path.open("a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
        return rec

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
