"""Graph state. One thread_id per system; the SqliteSaver checkpoints this dict after every node."""
from __future__ import annotations

from typing import Any, TypedDict

NODES = ["f0", "f1", "f2", "f3", "f4", "f5", "f6"]
NODE_NAMES = {"f0": "Intake", "f1": "Crystallographer", "f2": "Path Planner", "f3": "Runner",
              "f4": "Reviewer", "f5": "Analyst", "f6": "Skeptic"}
GATE_OF = {n: f"G{n[1]}" for n in NODES}


class IrisState(TypedDict, total=False):
    request: str          # plain-language request (input to f0)
    run_meta: dict        # run_id, tag, system, fault_id, ablation_flags, model fields (audit context)
    thread_id: str        # the run's thread (overrides config.thread_id; all files go to test_runs/<thread_id>/)
    config_path: str      # f0 reads this file (LLM intake comes in step 6)
    config: dict          # validated config (paths resolved, policy, budget, mode)
    overrides: dict       # node -> config patch applied by recover (rule / sub-agent / human)
    intent: str
    inputs: dict          # f0: cif paths, sha256, detected space groups
    decomposition: dict   # f1
    selection: dict       # f2: per-irrep role + rule (R1-R5)
    grid: dict            # f2
    jobs: dict            # f3
    energies: Any         # f4
    model: dict           # f5
    report: dict          # f6
    last_node: str
    gate: dict            # {"ok": bool, "code": str, "detail": str, "tests": [...]}; set by the node's gate
    route: str            # recover -> next node ("f0".."f6") or "END"
    attempts: dict        # node -> retries used
    history: list         # compact trail of (node, gate code) for the report
