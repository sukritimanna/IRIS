"""Shared stub used by f1-f6 until each node is wired in build step 2 (f3 interrupt: step 3).

A stub never invents results: it returns {"stub": True, ...} and its gate tests are SKIP, which only
pass in run.mode == "skeleton". In replay mode the gate fails with NOT_IMPLEMENTED.
"""
from __future__ import annotations


def stub(node: str, key: str, wraps: list[str], state: dict) -> dict:
    return {key: {"stub": True, "node": node, "wraps": wraps,
                  "overrides_seen": state.get("overrides", {}).get(node, {})},
            "last_node": node}
