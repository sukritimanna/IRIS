"""End-to-end wrapper (not part of the frozen intake; written after the v1 calls): run_e.endtoend expects a policy
template for every config with all critical fields right, but a new-material request that is answered correctly has
none (status needs_new_dft). Those configs are recorded as "would need new DFT" (stop code NO_STORED_DATA) without
running, then the frozen endtoend() does the rest unchanged.

  python -m intake.e2e [--out results/E/v2]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import intake.run_e as E  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.out:
        E.OUT = ROOT / a.out
    runs_f = E.OUT / "endtoend_runs.jsonl"
    have = {r["config_hash"] for r in map(json.loads, runs_f.read_text().splitlines())} if runs_f.is_file() else set()
    for c in map(json.loads, (E.OUT / "calls.jsonl").read_text().splitlines()):
        h = c["config_hash"]
        if c["resolved"]["status"] == "needs_new_dft" and h not in have:
            with open(runs_f, "a") as fh:
                fh.write(json.dumps({"config_hash": h, "template": None, "thread": None, "final": "would need new DFT",
                                     "stop_code": "NO_STORED_DATA", "numbers_identical": None,
                                     "note": c["resolved"]["reason"]}) + "\n")
            have.add(h)
    # a replay interrupted earlier leaves its thread folder behind: run it again under a new thread name (the old
    # folder is kept, never deleted)
    import iris_agent.run as R
    base = R.Session

    class Fresh(base):
        def __init__(self, config_path, thread_id=None, **kw):
            t, k = thread_id, 2
            while t and (ROOT / "test_runs" / t).exists():
                t, k = f"{thread_id}_r{k}", k + 1
            super().__init__(config_path, t, **kw)
    R.Session = Fresh
    E.endtoend()


if __name__ == "__main__":
    main()
