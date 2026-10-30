"""Job-end hook: tell a waiting IRIS thread that job parts have ended, and resume it.

Stand-in for the Slurm job-end hook (in a live build this would run from an `afterany` dependency
job). In replay nothing is computed: it only delivers the event; f3 then links the stored energies of
the parts that finished.

  python -m iris_agent.jobend --config configs/cssni3.yaml                  # all pending parts finished
  python -m iris_agent.jobend --config configs/cssni3.yaml --parts 0-9,12   # some parts
  python -m iris_agent.jobend --config configs/cssni3.yaml --parts 3 --fail 3:WALLTIME
  python -m iris_agent.jobend --config configs/cssni3.yaml --cancel
"""
from __future__ import annotations

import argparse
import json
import sys

from .run import Session


def parse_parts(text: str | None):
    if not text or text == "all":
        return "all"
    out = set()
    for tok in text.split(","):
        a, _, b = tok.partition("-")
        out |= set(range(int(a), int(b or a) + 1))
    return sorted(out)


def parse_fail(text: str | None) -> dict:
    out = {}
    for tok in (text or "").split(","):
        if tok.strip():
            p, _, code = tok.partition(":")
            out[str(int(p))] = (code or "UNKNOWN").upper()
    return out


def event(parts=None, fail=None, cancel=False) -> dict:
    if cancel:
        return {"event": "cancel"}
    failed = parse_fail(fail)
    p = parse_parts(parts)
    if failed and p == "all" and parts is None:
        p = sorted(int(k) for k in failed)          # --fail alone ends only the failed parts
    return {"event": "job_end", "parts": p, "failed": failed}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--thread", default=None)
    ap.add_argument("--parts", default=None, help="e.g. 0-9,12 (default: all pending parts)")
    ap.add_argument("--fail", default=None, help="e.g. 3:WALLTIME,5:NELM")
    ap.add_argument("--cancel", action="store_true")
    a = ap.parse_args(argv)
    ev = event(a.parts, a.fail, a.cancel)
    with Session(a.config, a.thread) as s:
        st = s.status()
        waiting = [i for i in st["interrupts"] if isinstance(i, dict) and i.get("kind") == "job_wait"]
        if not waiting:
            sys.exit(f"thread {s.thread_id!r} is not waiting on jobs (next: {st['next']})")
        res = s.resume(ev)
    if res.get("status") == "waiting_on_jobs":
        res = {k: v for k, v in res.items() if k != "interrupt"}
    print(json.dumps({"sent": ev, **res}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
