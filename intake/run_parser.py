"""Score the rule-based parser (intake/parser.py) on the 50 frozen requests with the scorer of intake/run_e.py.

  python -m intake.run_parser --freeze      # intake/PARSER.sha256 (before scoring)
  python -m intake.run_parser               # -> results/E/parser/calls.jsonl, E_parser_calls.csv, E_parser_summary.csv

The frozen intake files are verified first (run_e.verify); nothing in them is changed. The parser answers each request
once (deterministic) and goes through the same build (resolve, config, f0 + G0) as the models.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intake import build as B, parser as P, run_e as E  # noqa: E402

OUT = ROOT / "results" / "E" / ("parser" if os.environ.get("PARSER_V1") else "parser_v2")
FROZEN = ROOT / "intake" / "PARSER.sha256"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    a = ap.parse_args()
    files = [ROOT / "intake" / "parser.py", ROOT / "intake" / "run_parser.py"]
    if a.freeze:
        FROZEN.write_text(f"# rule-based intake parser frozen {datetime.now(timezone.utc).isoformat(timespec='seconds')}, "
                          "before any scoring; written from intake/library.py, intake/schema.py and the system prompt only.\n"
                          + "".join(f"{sha(f)}  {f.name}\n" for f in files))
        print(FROZEN.read_text())
        return
    bad = E.verify()
    # gates.py changed after the intake freeze (MISSING_FRAMES at G4/G5 and the R5 check at G2, 2026-10-29); the G0
    # tests the intake uses are unchanged. Any other frozen intake file changing is refused.
    tolerated = [b for b in bad if b.endswith("iris_agent/gates.py")]
    if [b for b in bad if b not in tolerated]:
        raise SystemExit(f"frozen intake files changed: {bad}")
    if tolerated:
        print("note: gates.py differs from the intake freeze (post-freeze G2/G4/G5 checks); G0 unchanged")
    if FROZEN.is_file():                 # each file must match one of its recorded hashes (v1 or v2)
        recorded = {}
        for line in FROZEN.read_text().splitlines():
            if line and not line.startswith("#"):
                h, name = line.split()[:2]
                recorded.setdefault(name, set()).add(h)
        for name, hs in recorded.items():
            if sha(ROOT / "intake" / name) not in hs:
                raise SystemExit(f"intake/{name} changed since the parser freeze")
    OUT.mkdir(parents=True, exist_ok=True)
    reqs = E.requests()
    rows = []
    with (OUT / "calls.jsonl").open("w") as f:
        for req in reqs:
            d = P.draft(req["text"], req.get("attachments"))
            res = B.resolve(d, req.get("attachments"))
            thread = f"E_{OUT.name}_{req['id']}_r0"
            cpath, h = B.write(res, req["text"], thread, OUT / "configs" / f"{req['id']}_r0")
            g0 = E.g0_of(cpath)
            c = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": "parser" if os.environ.get("PARSER_V1") else "parser_v2", "repeat": 0,
                 "request": req["id"], "draft": d, "resolved": res, "config": str(cpath), "config_hash": h, "g0": g0,
                 "llm_valid": True, "llm_error": None, "llm_model_version": "rule-parser"}
            f.write(json.dumps(c, default=str) + "\n")
            rows.append(E.score_row(c, req))
    with (OUT / "E_parser_calls.csv").open("w", newline="") as f:
        keys = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("model", "request", "kind", "style"), k))
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    par = [r for r in rows if r["kind"] == "paraphrase"]
    s = {"clear": f"{sum(bool(r['critical_all_right']) for r in par)}/{len(par)}"}
    for st in ("expert", "terse", "non-specialist"):
        p = [r for r in par if r["style"] == st]
        s[st] = f"{sum(bool(r['critical_all_right']) for r in p)}/{len(p)}"
    for kind, name in (("underspecified", "underspecified"), ("out_of_scope", "out of scope"), ("new_material", "new material")):
        p = [r for r in rows if r["kind"] == kind]
        s[name] = f"{sum(bool(r['correct_outcome']) for r in p)}/{len(p)}"
    s["wrong field passed G0"] = sum(bool(r.get("wrong_passed_g0")) for r in par)
    s["unnecessary questions"] = sum(r.get("clarification") == "unnecessary question" for r in par)
    s["refused a clear request"] = sum(r.get("clarification") == "refused a clear request" for r in par)
    with (OUT / "E_parser_summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(s))
        w.writeheader()
        w.writerow(s)
    print(json.dumps(s, indent=1))
    print("\nper request:")
    for r in rows:
        flag = "" if r["correct_outcome"] else "  <-- " + (r.get("wrong_critical_fields") or r.get("clarification") or r["outcome"])
        print(f"  {r['request']} {r['kind']:14s} {r['style']:14s} {r['outcome']:14s}{flag}")


if __name__ == "__main__":
    main()
