"""Job book and the wait loop for f3.

Frames are grouped into parts (one part = one Slurm array task on Perlmutter, 40 frames each in the
CsSnI3 campaign). A part is queued -> finished | failed:<CODE> | cancelled. f3 waits with
LangGraph interrupt() until no part is queued; each resume value is one job-end event:

  {"event": "job_end", "parts": [0, 1, 2] | "all", "failed": {"3": "WALLTIME"}}
  {"event": "cancel"}

Anything else is rejected (recorded, and f3 keeps waiting). Events are applied in order; on resume
LangGraph re-runs f3 and replays the earlier events, so applying them must be deterministic.
"""
from __future__ import annotations

from copy import deepcopy

FAILURE_CODES = ("WALLTIME", "NELM", "NODE_FAIL", "OOM", "UNKNOWN")


def plan_parts(frame_ids: list[int], part_size: int) -> dict:
    parts = {}
    for k in range(0, len(frame_ids), part_size):
        parts[str(k // part_size)] = {"frames": frame_ids[k:k + part_size], "status": "queued"}
    return parts


def pending(book: dict) -> list[int]:
    return sorted(int(p) for p, v in book["parts"].items() if v["status"] == "queued")


def apply_event(book: dict, event) -> tuple[dict, bool, str]:
    """Return (new book, accepted, message). Never mutates the input."""
    b = deepcopy(book)
    if not isinstance(event, dict) or event.get("event") not in ("job_end", "cancel"):
        return b, False, f"not a job event: {str(event)[:200]}"
    if event["event"] == "cancel":
        for p in pending(b):
            b["parts"][str(p)]["status"] = "cancelled"
        return b, True, "remaining parts cancelled"
    parts = event.get("parts", "all")
    failed = {str(k): str(v).upper() for k, v in (event.get("failed") or {}).items()}
    want = pending(b) if parts == "all" else sorted({int(p) for p in parts} | {int(p) for p in failed})
    unknown = [p for p in want if str(p) not in b["parts"]]
    bad_codes = [c for c in failed.values() if c not in FAILURE_CODES]
    if unknown or bad_codes:
        return b, False, f"unknown parts {unknown} or failure codes {bad_codes}"
    done = []
    for p in want:
        part = b["parts"][str(p)]
        if part["status"] != "queued":
            continue                                   # a repeated end signal is harmless
        part["status"] = f"failed:{failed[str(p)]}" if str(p) in failed else "finished"
        done.append(p)
    return b, True, f"{len(done)} parts ended"


def wait(book: dict, interrupt_fn, payload: dict) -> dict:
    """Interrupt until no part is queued. `interrupt_fn` is langgraph.types.interrupt."""
    book = deepcopy(book)
    book.setdefault("events", [])
    while pending(book):
        ev = interrupt_fn({**payload, "kind": "job_wait", "parts_pending": pending(book),
                           "n_parts": len(book["parts"])})
        book, ok, msg = apply_event(book, ev)
        book["events"].append({"event": ev, "accepted": ok, "message": msg})
    return book


def summary(book: dict) -> dict:
    s = {}
    for v in book["parts"].values():
        s[v["status"]] = s.get(v["status"], 0) + 1
    return s
