"""Which G6 catches rest on a replay oracle.

G6 (gates.g6_every_number_rederived) fails when any f6 row has |value - rederived| > tol. f6 re-derives each reported
number by a second route from the run's own inputs (stored ISODISTORT, the grid, the linked energies) -- valid in
production -- but in replay the energies for that second route are re-read from the stored campaign CSV for EVERY
matched frame, including frames whose jobs the faulted run lost or flagged. Rows of two kinds:
  oracle   compares the run with the stored campaign files themselves ("linked energies equal to the CSV",
           "energies differing from the collected CSV", "frames matched to stored structures / POSCARs",
           "<point> E0 / dE / converged (CSV)", "... vs energies_summary.json"); production has no such file
  rederive a second-route recomputation (fit, ring, surface, barrier ...); it fails here only when it reads campaign
           energies the run never had (flagged / dropped frames)
A G6 catch is tagged replay_oracle when any oracle row fails, or when a failing rederive row used CSV energies for
frames the run had flagged (energies.flagged non-empty or fewer linked energies than matched frames).

  python -m consequences.g6_oracle     # -> results/C/G6_catches.csv, results/C/E9_gate_ablation_tagged.csv
"""
from __future__ import annotations

import csv
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNS = ROOT / "test_runs"
OUT = ROOT / "results" / "C"
ORACLE = re.compile(r"equal to the CSV|collected CSV|matched to stored|\(CSV\)|energies_summary\.json")


def catches(thread: str) -> list[dict]:
    from langgraph.checkpoint.sqlite import SqliteSaver
    db = RUNS / thread / "iris.sqlite"
    if not db.is_file():
        return []
    out, seen = [], set()
    sv = SqliteSaver(sqlite3.connect(str(db)))
    for ck in sv.list({"configurable": {"thread_id": thread}}):
        cv = ck.checkpoint["channel_values"]
        g = cv.get("gate") or {}
        if cv.get("last_node") != "f6" or g.get("code") != "MISMATCH" or g.get("ok") and not g.get("ignored"):
            continue
        bad = [r for r in (cv.get("report") or {}).get("rows", []) if not r["ok"]]
        key = tuple(r["name"] for r in bad)
        if key in seen:
            continue
        seen.add(key)
        orc = [r["name"] for r in bad if ORACLE.search(r["name"])]
        red = [r["name"] for r in bad if not ORACLE.search(r["name"])]
        en = cv.get("energies") or {}
        n_lnk = len(en.get("eV_per_cell") or en.get("meV_per_fu") or {})
        n_mat = (cv.get("jobs") or {}).get("n_matched")
        flagged = len(en.get("flagged") or []) or (n_mat is not None and n_lnk and n_lnk < n_mat)
        out.append({"thread": thread, "checkpoint": ck.checkpoint["ts"], "n_rows_failing": len(bad),
                    "oracle_rows_failing": "; ".join(orc), "rederive_rows_failing": "; ".join(red[:12]),
                    "frames_flagged_or_unlinked": bool(flagged),
                    "replay_oracle": bool(orc) or (bool(red) and bool(flagged))})
    return out


def main():
    rows = []
    for d in sorted(RUNS.iterdir()):
        if d.name.startswith(("C_", "C2_", "E9_", "E2_F")):
            rows += catches(d.name)
    OUT.mkdir(parents=True, exist_ok=True)
    keys = ["thread", "checkpoint", "n_rows_failing", "oracle_rows_failing", "rederive_rows_failing",
            "frames_flagged_or_unlinked", "replay_oracle"]
    with open(OUT / "G6_catches.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    by = {}
    for r in rows:
        by.setdefault(r["thread"], []).append(r)
    e9 = ROOT / "results" / "summary" / "E9_gate_ablation.csv"
    if e9.is_file():
        er = list(csv.DictReader(open(e9)))
        for r in er:
            c = by.get(r["thread"], [])
            r["g6_caught"] = bool(c)
            r["replay_oracle"] = any(x["replay_oracle"] for x in c) if c else ""
            r["g6_oracle_rows"] = "; ".join(sorted({x["oracle_rows_failing"] for x in c if x["oracle_rows_failing"]}))
        with open(OUT / "E9_gate_ablation_tagged.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(er[0]))
            w.writeheader()
            w.writerows(er)
    print(OUT / "G6_catches.csv", len(rows), "G6 catches;", sum(r["replay_oracle"] for r in rows), "replay_oracle")
    return by


if __name__ == "__main__":
    main()
