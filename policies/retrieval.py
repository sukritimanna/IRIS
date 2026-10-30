"""Experiment A (2): case retrieval. The nearest stored case decides.

Memory: the frozen cases (eval/subagent_cases/<id>.json + labels in eval/subagent_cases.yaml). For a decision:
  1. candidates = memory cases with the same gate and code, leaving out the case itself (case scoring) or every case
     made from the same fault (faulted runs) — leave-one-out;
  2. among them, the highest TF-IDF cosine similarity of the gate detail text (ties: lower case id);
  3. its reference action (its first `correct` label) if that option is on the current menu, else `stop`;
     no candidate -> `stop`.
Variants: `all` (memory = all 53 cases) and `seed` (memory = the 37 seed cases only: no held-out case is ever used as
memory, so the held-out score is a clean out-of-sample number).
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import yaml

EVAL = Path(__file__).resolve().parents[1] / "eval"
TOKEN = re.compile(r"[a-z][a-z0-9_+\-]*")


def tokens(text: str) -> list[str]:
    return TOKEN.findall((text or "").lower())


@lru_cache(maxsize=None)
def memory() -> tuple[dict, ...]:
    out = []
    for c in yaml.safe_load((EVAL / "subagent_cases.yaml").read_text())["cases"]:
        cap = json.loads((EVAL / "subagent_cases" / f"{c['id']}.json").read_text())
        out.append({"id": c["id"], "fault": c.get("fault"), "split": c.get("split", "seed"), "gate": cap["gate"],
                    "code": cap["code"], "detail": cap["prompt_values"].get("detail", ""),
                    "action": c["labels"]["correct"][0]})
    return tuple(out)


def _tfidf(docs: list[list[str]]) -> list[dict]:
    n = len(docs)
    df = Counter(t for d in docs for t in set(d))
    vecs = []
    for d in docs:
        tf = Counter(d)
        v = {t: (c / len(d)) * (math.log((1 + n) / (1 + df[t])) + 1) for t, c in tf.items()} if d else {}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({t: x / norm for t, x in v.items()})
    return vecs


def nearest(ctx: dict, variant: str = "all") -> dict | None:
    pool = [m for m in memory() if (variant == "all" or m["split"] == "seed")
            and m["id"] != ctx.get("case_id")
            and not (ctx.get("fault_id") and m["fault"] == ctx.get("fault_id"))
            and m["gate"] == ctx["gate"] and m["code"] == ctx["code"]]
    if not pool:
        return None
    vecs = _tfidf([tokens(ctx.get("detail", ""))] + [tokens(m["detail"]) for m in pool])
    q = vecs[0]
    sims = [sum(q.get(t, 0.0) * x for t, x in v.items()) for v in vecs[1:]]
    best = max(range(len(pool)), key=lambda i: (round(sims[i], 12), [-ord(ch) for ch in pool[i]["id"]]))
    return {**pool[best], "similarity": sims[best]}


def choose(ctx: dict, variant: str = "all") -> tuple[str, str]:
    m = nearest(ctx, variant)
    if m is None:
        return "stop", f"no {variant} memory case with {ctx['gate']} {ctx['code']}"
    if m["action"] not in ctx["options"]:
        return "stop", f"nearest {m['id']} (sim {m['similarity']:.3f}) -> {m['action']}, not on the menu"
    return m["action"], f"nearest {m['id']} (sim {m['similarity']:.3f})"


def choose_seed(ctx: dict) -> tuple[str, str]:
    return choose(ctx, "seed")
