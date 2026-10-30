"""Retry the calls of a finished Experiment E run that failed at the API (e.g. HTTP 402, credits depleted).

Not part of the frozen intake: it only re-sends the same frozen prompt through the frozen code (run_e.one_call) for
the (model, request, repeat) rows whose call errored, and writes a NEW folder; the original run is left untouched.

  python -m intake.retry --src results/E/v2 --dst results/E/v2_retry [--models gemini-argon]
  python -m intake.run_e --score --out results/E/v2_retry

dst/calls.jsonl = every successful row of src (unchanged) + the retried rows; dst/retry_log.jsonl lists each retried
call with the original error and the new outcome. Refuses to run unless intake/ verifies against FROZEN.sha256.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import intake.run_e as E  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--models", default=None, help="comma list; default every model with errors")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    bad = E.verify()
    if bad:
        raise SystemExit("refusing: " + "; ".join(bad))
    src, dst = ROOT / a.src, ROOT / a.dst
    if (dst / "calls.jsonl").exists():
        raise SystemExit(f"{dst}/calls.jsonl exists: choose a new --dst")
    rows = [json.loads(x) for x in (src / "calls.jsonl").read_text().splitlines()]
    want = set(a.models.split(",")) if a.models else None
    failed = [r for r in rows if r.get("llm_error") and (want is None or r["model"] in want)]
    keep = [r for r in rows if r not in failed]
    print(f"{len(failed)} failed calls to retry; {len(keep)} kept as they are")
    from iris_agent.llm import load_models
    mods = load_models(ROOT / "eval" / "models.yaml")
    reqs = {r["id"]: r for r in E.requests()}
    E.OUT = dst
    dst.mkdir(parents=True, exist_ok=True)

    def job(r):
        return r, E.one_call(r["model"], mods[r["model"]], reqs[r["request"]], r["repeat"])
    out = list(keep)
    with ThreadPoolExecutor(max_workers=a.workers) as ex, open(dst / "retry_log.jsonl", "w") as log:
        for old, new in ex.map(job, failed):
            out.append(new)
            log.write(json.dumps({"model": old["model"], "request": old["request"], "repeat": old["repeat"],
                                  "original_error": old.get("llm_error"), "retry_error": new.get("llm_error"),
                                  "retry_outcome": new["resolved"]["status"]}) + "\n")
            print(old["model"], old["request"], old["repeat"], "->", new["resolved"]["status"], new.get("llm_error") or "")
    with open(dst / "calls.jsonl", "w") as fh:
        for r in out:
            fh.write(json.dumps(r, default=str) + "\n")
    left = sum(1 for r in out if r.get("llm_error"))
    print(f"wrote {dst / 'calls.jsonl'} ({len(out)} rows; {left} still failed)")


if __name__ == "__main__":
    main()
