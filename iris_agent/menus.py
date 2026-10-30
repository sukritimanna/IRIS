"""SI Table S3: the recovery menu of every gate, generated from recovery.yaml (never written by hand).

  python -m iris_agent.menus          # -> results/summary/SI_S3_menus.{csv,md}

Per gate: the rules tried first (rule table), whether a sub-agent is asked (not when the menu has only `stop`), and
each option with its text, its config patch and the node file that reads the patch.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

from .recover import RecoveryTable
from .state import GATE_OF, NODE_NAMES

AGENT_ROOT = Path(__file__).resolve().parents[1]


def readers(key: str) -> list[str]:
    pat = re.compile(r"""(?:\.get\(|\[)["']%s["']""" % re.escape(key))
    out = []
    for p in sorted((AGENT_ROOT / "iris_agent" / "nodes").glob("*.py")):
        if any(pat.search(line) for line in p.read_text().splitlines() if "over" in line):
            out.append(f"nodes/{p.name}")
    return out


def table(rec_path=AGENT_ROOT / "recovery.yaml") -> list[dict]:
    t = RecoveryTable(rec_path)
    rows = []
    for node, opts in t.options.items():
        rules = [f"{r['id']} ({r['code']})" for r in t.rules if r["node"] == node]
        asked = not all(o["id"] == "stop" for o in opts)
        for o in opts:
            keys = [k for k in o["patch"] if k not in ("goto", "abort")]
            route = "END (human)" if o["patch"].get("abort") else o["patch"].get("goto", node)
            rows.append({"gate": GATE_OF[node], "node": f"{node} {NODE_NAMES[node]}", "option": o["id"], "text": o["text"],
                         "patch": json.dumps({k: v for k, v in o["patch"].items() if k not in ("goto", "abort")}) if keys else "",
                         "next_node": route, "read_by": "; ".join(sorted({x for k in keys for x in readers(k)})),
                         "rules_before_subagent": "; ".join(rules), "subagent_asked": "yes" if asked else "no (stop only)"})
    return rows


def main(argv=None):
    out = AGENT_ROOT / "results" / "summary"
    out.mkdir(parents=True, exist_ok=True)
    rows = table()
    with open(out / "SI_S3_menus.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    L = ["# SI Table S3 — recovery menus per gate (generated from recovery.yaml)", "",
         "| gate | node | rules tried first | sub-agent asked | option | what it does | config patch | next node | read by |",
         "|---|---|---|---|---|---|---|---|---|"]
    prev = None
    for r in rows:
        first = r["gate"] != prev
        L.append(f"| {r['gate'] if first else ''} | {r['node'] if first else ''} | {r['rules_before_subagent'] if first else ''} | "
                 f"{r['subagent_asked'] if first else ''} | `{r['option']}` | {r['text']} | {('`' + r['patch'] + '`') if r['patch'] else ''} | "
                 f"{r['next_node']} | {r['read_by']} |")
        prev = r["gate"]
    (out / "SI_S3_menus.md").write_text("\n".join(L) + "\n")
    print(out / "SI_S3_menus.md")


if __name__ == "__main__":
    sys.exit(main())
