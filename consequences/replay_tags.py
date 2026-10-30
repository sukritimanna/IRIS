"""Replay dependence of every gate catch (E9 and Experiment C).

Tags of one catch (gate + code [+ G6 rows]):
  replay_oracle      the gate fires only because replay compares the run with stored campaign outputs, or cannot go on
                     without them; production would have computed or would not have the file:
                       G3 UNMATCHED   a frame with no stored computed structure (production: the frame is computed)
                       G3 RIGID_SHIFT replay matching tolerance
                       G6 MISMATCH    when an oracle row fails (consequences/g6_oracle.py)
  stored_reference   the gate reads stored campaign energies of OTHER paths (G5 CLOSURE, G5 CROSS_SETTING:
                     policy.path.network is read-only on the other stored paths); valid in production only if those
                     paths are computed in the same campaign or available from an earlier run
  ablation_artifact  the catch is caused by the ablation, not by the fault (E9: removing G2 also removes the InMnO3
                     R5 decision point, f2 then returns no frames and f3 fails with NODE_ERROR KeyError 'frames')
  none               the gate tests the run's own data (job status, its own energies / fit, inputs)
Missing energies at G5 (THIN_GRID / CV_ERROR / NODE_ERROR) were checked: every flagged frame at those catches is a
frame of an injected failed job part; no frame is flagged for lacking a stored energy, so these are tagged none.

  python -m consequences.replay_tags    # -> results/C/E9_gate_ablation_tagged.csv, results/C/replay_catches.csv
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from consequences.g6_oracle import catches  # noqa: E402

RUNS = ROOT / "test_runs"
OUT = ROOT / "results" / "C"
CODE_TAG = {("G3", "UNMATCHED"): "replay_oracle", ("G3", "RIGID_SHIFT"): "replay_oracle",
            ("G5", "CLOSURE"): "stored_reference", ("G5", "CROSS_SETTING"): "stored_reference"}
NATURAL = ("R5_BORDERLINE", "SECONDARY_COUPLED")


def tag_of(thread: str, gate: str, code: str) -> str:
    if (gate, code) == ("G6", "MISMATCH"):
        return "replay_oracle" if any(x["replay_oracle"] for x in catches(thread)) else "none"
    if (gate, code) == ("G3", "NODE_ERROR"):
        log = [json.loads(x) for x in (RUNS / thread / "audit.jsonl").read_text().splitlines()]
        g = next((r for r in log if r["kind"] == "gate" and r.get("gate_code") == "NODE_ERROR" and r["node"] == "f3"), {})
        ignored_r5 = any(r["kind"] == "gate" and r.get("gate_code") == "R5_BORDERLINE" and r.get("outcome") == "fail_ignored"
                         for r in log)
        return "ablation_artifact" if ignored_r5 and "'frames'" in g.get("detail", "") else "none"
    return CODE_TAG.get((gate, code), "none")


def failures(thread: str, after_fork: bool = False) -> list[tuple[str, str, str]]:
    log = [json.loads(x) for x in (RUNS / thread / "audit.jsonl").read_text().splitlines()]
    if after_fork:
        k = next((i for i, r in enumerate(log) if r["kind"] == "fix" and r.get("fork_point")), None)
        log = log[k + 1:] if k is not None else []
    return [(r["gate"], r["gate_code"], tag_of(thread, r["gate"], r["gate_code"])) for r in log
            if r["kind"] == "gate" and r.get("outcome") in ("fail", "fail_ignored") and r.get("gate_code") not in NATURAL]


def e9():
    f = ROOT / "results" / "summary" / "E9_gate_ablation.csv"
    rows = list(csv.DictReader(open(f)))
    for r in rows:
        det = (r["detected_by"] or "none").split(" ")
        r["detection_tag"] = "" if det[0] == "none" else tag_of(r["thread"], det[0], det[1])
        c = catches(r["thread"])
        r["g6_caught"] = bool(c)
        r["g6_oracle_rows"] = "; ".join(sorted({x["oracle_rows_failing"] for x in c if x["oracle_rows_failing"]}))
        r["replay_oracle"] = r["detection_tag"] == "replay_oracle"
        r["production_valid_detection"] = (r["detection_tag"] == "none") if det[0] != "none" else ""
    with open(OUT / "E9_gate_ablation_tagged.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


def main():
    rows = e9()
    det = [r for r in rows if r["is_detecting_gate"] == "True" and r["detection_tag"] != ""]
    for t in ("none", "replay_oracle", "stored_reference", "ablation_artifact"):
        x = [r for r in det if r["detection_tag"] == t]
        print(f"E9 detecting-gate ablations caught later, tag {t}: {len(x)}",
              ", ".join(f"{r['fault']}(-{r['ablated_gate']}->{r['detected_by']})" for r in x))
    print(OUT / "E9_gate_ablation_tagged.csv")


if __name__ == "__main__":
    main()
