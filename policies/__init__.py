"""Experiment A: non-LLM sub-agent policies (deterministic tree from the Guidance lines; leave-one-out case
retrieval; rules-only). Each policy: choose(ctx) -> (option_id, reason). ctx holds the sub-agent's prompt inputs
(gate, code, detail, tests, history, attempts, max_retry), the option ids shown and, where known, the case / fault id."""
