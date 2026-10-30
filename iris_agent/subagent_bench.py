"""S5.3: the sub-agent model comparison on the frozen cases (eval/subagent_cases/).

  python -m iris_agent.subagent_bench --tag S5_3                      # all models in eval/models.yaml, guided + bare, 10 repeats
  python -m iris_agent.subagent_bench --tag S5_3 --models-only claude-haiku,gpt-luna --repeats 2
  python -m iris_agent.subagent_bench --tag S5_3 --summarize          # rebuild results/summary/ from the calls

Protocol (identical for every model; no per-model prompt tuning):
  - each case's stored prompt (eval/subagent_cases/<id>.json): system prompt guided or bare, user prompt re-rendered
    from the stored template and values with the options in a shuffled order;
  - the order depends on (case, repeat) only, so all models and both variants see the same order in the same repeat
    (paired comparison); repeat r uses Random("<case>:<r>");
  - mode constrained (the menu ids enforced by every provider), temperature at the provider default, one call per
    (model, case, variant, repeat); an invalid answer is scored invalid, never retried; transport errors (HTTP / key /
    timeout) are kept apart and can be retried (--retry-errors).
Scoring: correct / safe / harmful from the approved labels; invalid; always-stop, first-option and uniform-random
baselines. Runs only when eval/ is frozen and unchanged.
Output: results/<tag>/calls.jsonl (one line per call, prompts included) and results/summary/S5_3_*.csv + .md.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import freeze_eval, prompts
from .llm import MODELS_YAML, llm_choose, load_models
from .subagent_cases import load_cases

AGENT_ROOT = Path(__file__).resolve().parents[1]
EVAL = AGENT_ROOT / "eval"
RESULTS = AGENT_ROOT / "results"
SUMMARY = RESULTS / "summary"
VARIANTS = ("guided", "bare")


# ---- cases ------------------------------------------------------------------------------------------------------
def load_bench_cases(cases_yaml=EVAL / "subagent_cases.yaml", case_dir=EVAL / "subagent_cases") -> list[dict]:
    out = []
    for c in load_cases(cases_yaml)["cases"]:
        cap = json.loads((Path(case_dir) / f"{c['id']}.json").read_text())
        lab = {i: k for k in ("correct", "safe", "harmful") for i in c["labels"].get(k, [])}
        out.append({"id": c["id"], "split": c.get("split", "seed"), "class": c["class"], "system": c["system"],
                    "node": cap["node"], "code": cap["code"], "menu": cap["menu"], "label_of": lab,
                    "system_guided": cap["system_prompt"], "system_bare": cap["system_prompt_bare"],
                    "user_template": cap["user_template"], "values": cap["prompt_values"]})
    return out


def order_for(case_id: str, repeat: int, menu: list[dict]) -> list[dict]:
    shown = list(menu)
    random.Random(f"{case_id}:{repeat}").shuffle(shown)
    return shown


def render(case: dict, variant: str, shown: list[dict]) -> tuple[str, str]:
    v = {**case["values"], "options": [{"id": o["id"], "text": o["text"]} for o in shown]}
    v = {k: (json.dumps(x, indent=1) if isinstance(x, (dict, list)) else x) for k, x in v.items()}
    return case["system_guided" if variant == "guided" else "system_bare"], prompts._fill(case["user_template"], v)


def is_transport_error(r: dict) -> bool:
    st = r.get("status", "")
    return st.startswith(("http ", "no ")) or r.get("error") in ("missing key",)


# ---- run --------------------------------------------------------------------------------------------------------
def run(tag: str, models: dict, cases: list[dict], variants, repeats: int, workers: int, retry_errors: bool,
        transport=None, out_root: Path = RESULTS) -> Path:
    out_dir = Path(out_root) / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    calls = out_dir / "calls.jsonl"
    done = {}
    if calls.is_file():
        for line in calls.read_text().splitlines():
            r = json.loads(line)
            done[(r["model_name"], r["case"], r["variant"], r["repeat"])] = r
    todo = defaultdict(list)
    for name, spec in models.items():
        for c in cases:
            for var in variants:
                for rep in range(repeats):
                    k = (name, c["id"], var, rep)
                    if k in done and not (retry_errors and is_transport_error(done[k])):
                        continue
                    todo[spec["provider"]].append((name, spec, c, var, rep))
    n = sum(len(v) for v in todo.values())
    print(f"{n} calls to make ({len(done)} already in {calls})")
    lock, counter = threading.Lock(), [0]

    def one(item):
        name, spec, c, var, rep = item
        shown = order_for(c["id"], rep, c["menu"])
        system, user = render(c, var, shown)
        ctx = {**{k: v for k, v in c["values"].items() if k != "options"}, "case_id": c["id"]}
        r = llm_choose({**spec, "mode": "constrained", "_case": c["id"]}, system, user, [o["id"] for o in shown],
                       transport=transport, context=ctx)
        ids = [o["id"] for o in shown]
        rec = {"model_name": name, "tier": spec.get("tier"), "case": c["id"], "split": c["split"], "class": c["class"],
               "variant": var, "repeat": rep, "option_order": ids,
               "chosen_position": ids.index(r["id"]) + 1 if r.get("id") in ids else None,
               "correct_positions": [ids.index(i) + 1 for i, k in c["label_of"].items() if k == "correct"],
               "label": ("error" if is_transport_error(r) else c["label_of"].get(r["id"], "invalid") if r.get("valid") else "invalid"),
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "system_prompt_variant": var,
               "user_prompt": user, **{k: v for k, v in r.items() if k != "name"}}
        with lock:
            with open(calls, "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
            counter[0] += 1
            if counter[0] % 50 == 0 or counter[0] == n:
                print(f"  {counter[0]}/{n}")
        return rec

    # one pool per provider, so a slow or rate-limited provider does not hold up the others
    pools = [ThreadPoolExecutor(max_workers=workers) for _ in todo]
    futs = [f for pool, items in zip(pools, todo.values()) for f in [pool.submit(one, it) for it in items]]
    for f in futs:
        f.result()
    for p in pools:
        p.shutdown()
    return calls


# ---- summary ----------------------------------------------------------------------------------------------------
def _wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 4), round(c + h, 4))


def _cluster_ci(rows, field, B=2000, seed=0):
    """Bootstrap over cases (repeats of one case stay together): 95 % CI of the rate of rows[field]."""
    by = defaultdict(list)
    for r in rows:
        by[r["case"]].append(1.0 if r["label"] == field else 0.0)
    cases = list(by)
    if not cases:
        return (None, None)
    rng = random.Random(seed)
    stats = []
    for _ in range(B):
        s = [x for c in (rng.choice(cases) for _ in cases) for x in by[c]]
        stats.append(sum(s) / len(s))
    stats.sort()
    return (round(stats[int(0.025 * B)], 4), round(stats[int(0.975 * B) - 1], 4))


def _mcnemar(pairs):
    """Exact two-sided McNemar on paired booleans (model correct, reference correct)."""
    b = sum(1 for a, r in pairs if a and not r)
    c = sum(1 for a, r in pairs if r and not a)
    n = b + c
    if n == 0:
        return b, c, 1.0
    k = min(b, c)
    p = 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return b, c, round(min(1.0, p), 6)


def _pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))], 3)


def pairwise(scored: list[dict], names: list[str], B=2000, seed=0) -> list[dict]:
    """Every model pair, per variant and split: paired over (case, repeat); exact McNemar on correct; Holm-adjusted
    p over all pairs of the same variant and split; bootstrap-over-cases 95 % CI of the difference in correct rate
    and in harmful rate (A - B)."""
    idx = {(r["model_name"], r["variant"], r["case"], r["repeat"]): r for r in scored}
    rows = []
    for var in VARIANTS:
        for sp in ("all", "seed", "held-out"):
            block = []
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    keys = [(c, rep) for (m, v, c, rep) in idx if m == a and v == var and (b, var, c, rep) in idx
                            and (sp == "all" or idx[(m, v, c, rep)]["split"] == sp)]
                    if not keys:
                        continue
                    pa = [idx[(a, var, c, rep)] for c, rep in keys]
                    pb = [idx[(b, var, c, rep)] for c, rep in keys]
                    nb, nc, p = _mcnemar([(x["label"] == "correct", y["label"] == "correct") for x, y in zip(pa, pb)])
                    by = defaultdict(list)
                    for (c, _), x, y in zip(keys, pa, pb):
                        by[c].append((x["label"], y["label"]))
                    cs = list(by)
                    rng = random.Random(seed)
                    dc, dh = [], []
                    for _ in range(B):
                        smp = [t for c in (rng.choice(cs) for _ in cs) for t in by[c]]
                        dc.append(sum((x == "correct") - (y == "correct") for x, y in smp) / len(smp))
                        dh.append(sum((x == "harmful") - (y == "harmful") for x, y in smp) / len(smp))
                    dc.sort(); dh.sort()
                    n = len(keys)
                    block.append({"variant": var, "split": sp, "model_a": a, "model_b": b, "n_paired": n,
                                  "correct_rate_a": round(sum(x["label"] == "correct" for x in pa) / n, 4),
                                  "correct_rate_b": round(sum(y["label"] == "correct" for y in pb) / n, 4),
                                  "diff_correct": round(sum((x["label"] == "correct") - (y["label"] == "correct") for x, y in zip(pa, pb)) / n, 4),
                                  "diff_correct_ci95": f"{round(dc[int(0.025 * B)], 4)}–{round(dc[int(0.975 * B) - 1], 4)}",
                                  "diff_harmful": round(sum((x["label"] == "harmful") - (y["label"] == "harmful") for x, y in zip(pa, pb)) / n, 4),
                                  "diff_harmful_ci95": f"{round(dh[int(0.025 * B)], 4)}–{round(dh[int(0.975 * B) - 1], 4)}",
                                  "a_only_correct": nb, "b_only_correct": nc, "mcnemar_p": p})
            m = len(block)                                     # Holm step-down over the pairs of this block
            order = sorted(range(m), key=lambda k: block[k]["mcnemar_p"])
            run_max = 0.0
            for rank, k in enumerate(order):
                adj = min(1.0, (m - rank) * block[k]["mcnemar_p"])
                run_max = max(run_max, adj)
                block[k]["mcnemar_p_holm"] = round(run_max, 6)
            rows += block
    return rows


def baselines(cases: list[dict], repeats: int) -> list[dict]:
    out = []
    for name, pick in (("baseline:always-stop", lambda c, shown: "stop"),
                       ("baseline:first-option", lambda c, shown: shown[0]["id"])):
        rows = []
        for c in cases:
            for rep in range(repeats):
                shown = order_for(c["id"], rep, c["menu"])
                rows.append({"case": c["id"], "split": c["split"], "class": c["class"],
                             "label": c["label_of"].get(pick(c, shown), "invalid")})
        out.append((name, rows))
    rows = []                                                  # uniform random: expected rates, per case
    for c in cases:
        cnt = Counter(c["label_of"].get(o["id"]) for o in c["menu"])
        m = len(c["menu"])
        rows.append({"case": c["id"], "split": c["split"], "class": c["class"],
                     "frac": {k: cnt.get(k, 0) / m for k in ("correct", "safe", "harmful")}})
    out.append(("baseline:uniform-random", rows))
    return out


def summarize(tag: str, models: dict, cases: list[dict], repeats: int, reference: str | None,
              out_root: Path = RESULTS, summary_dir: Path | None = None) -> Path:
    calls = [json.loads(x) for x in (Path(out_root) / tag / "calls.jsonl").read_text().splitlines()]
    SUMMARY = Path(summary_dir or Path(out_root) / "summary")
    SUMMARY.mkdir(parents=True, exist_ok=True)
    scored = [r for r in calls if r["label"] != "error"]
    splits = ("all", "seed", "held-out")
    model_rows, case_rows, class_rows = [], [], []
    ref_idx = {(r["case"], r["variant"], r["repeat"]): r["label"] == "correct" for r in scored if r["model_name"] == reference}
    for name in models:
        for var in VARIANTS:
            mine = [r for r in scored if r["model_name"] == name and r["variant"] == var]
            errs = [r for r in calls if r["model_name"] == name and r["variant"] == var and r["label"] == "error"]
            if not mine and not errs:
                continue
            for sp in splits:
                rows = [r for r in mine if sp == "all" or r["split"] == sp]
                n = len(rows)
                if n == 0 and sp != "all":
                    continue
                cnt = Counter(r["label"] for r in rows)
                by_case = defaultdict(list)
                for r in rows:
                    by_case[r["case"]].append(r.get("answered_id") or r.get("id"))
                consist = statistics.mean(Counter(v).most_common(1)[0][1] / len(v) for v in by_case.values()) if by_case else None
                first = [r for r in rows if r["correct_positions"] and 1 in r["correct_positions"]]
                last = [r for r in rows if r["correct_positions"] and len(r["option_order"]) in r["correct_positions"]]
                pairs = [(r["label"] == "correct", ref_idx[(r["case"], r["variant"], r["repeat"])]) for r in rows
                         if (r["case"], r["variant"], r["repeat"]) in ref_idx]
                b, c, p = _mcnemar(pairs) if name != reference else (None, None, None)
                cost = [r.get("cost_usd") for r in rows if r.get("cost_usd") is not None]
                spec = models[name]
                model_rows.append({
                    "model": name, "provider": spec["provider"], "model_id": spec["model"], "tier": spec.get("tier"),
                    "variant": var, "split": sp, "n_calls": n, "n_cases": len(by_case),
                    "transport_errors": len(errs) if sp == "all" else "",
                    "correct": cnt["correct"], "safe": cnt["safe"], "harmful": cnt["harmful"], "invalid": cnt["invalid"],
                    "correct_rate": round(cnt["correct"] / n, 4) if n else None,
                    "correct_ci95": "%s–%s" % _cluster_ci(rows, "correct"),
                    "safe_rate": round(cnt["safe"] / n, 4) if n else None,
                    "harmful_rate": round(cnt["harmful"] / n, 4) if n else None,
                    "harmful_ci95": "%s–%s" % _cluster_ci(rows, "harmful"),
                    "invalid_rate": round(cnt["invalid"] / n, 4) if n else None,
                    "consistency": round(consist, 4) if consist is not None else None,
                    "correct_rate_when_correct_shown_first": round(sum(r["label"] == "correct" for r in first) / len(first), 4) if first else None,
                    "correct_rate_when_correct_shown_last": round(sum(r["label"] == "correct" for r in last) / len(last), 4) if last else None,
                    "mcnemar_vs_reference_b_c_p": "" if b is None else f"{b}/{c}/{p}",
                    "tokens_in_mean": round(statistics.mean(r["tokens_in"] for r in rows if r.get("tokens_in") is not None), 1) if n else None,
                    "tokens_out_mean": round(statistics.mean(r["tokens_out"] for r in rows if r.get("tokens_out") is not None), 1) if n else None,
                    "tokens_reasoning_mean": round(statistics.mean(r.get("tokens_reasoning") or 0 for r in rows), 1) if n else None,
                    "cost_usd_total": round(sum(cost), 4) if cost else None,
                    "cost_usd_per_decision": round(sum(cost) / len(cost), 6) if cost else None,
                    "latency_s_p50": _pct([r.get("latency_s") for r in rows], 0.5),
                    "latency_s_p95": _pct([r.get("latency_s") for r in rows], 0.95),
                    "returned_versions": ";".join(sorted({str(r.get("model_version")) for r in rows})),
                })
            for cid in sorted({r["case"] for r in mine}):
                rows = [r for r in mine if r["case"] == cid]
                cnt = Counter(r["label"] for r in rows)
                choice = Counter(r.get("answered_id") for r in rows)
                case_rows.append({"model": name, "variant": var, "case": cid, "split": rows[0]["split"],
                                  "class": rows[0]["class"], "n": len(rows),
                                  "correct": cnt["correct"], "safe": cnt["safe"], "harmful": cnt["harmful"],
                                  "invalid": cnt["invalid"], "modal_choice": choice.most_common(1)[0][0],
                                  "choices": ";".join(f"{k}:{v}" for k, v in choice.most_common())})
            for cl in sorted({r["class"] for r in mine}):
                rows = [r for r in mine if r["class"] == cl]
                cnt = Counter(r["label"] for r in rows)
                class_rows.append({"model": name, "variant": var, "class": cl, "n": len(rows),
                                   **{f"{k}_rate": round(cnt[k] / len(rows), 4) for k in ("correct", "safe", "harmful", "invalid")}})
    base_rows = []
    for name, rows in baselines(cases, repeats):
        for sp in splits:
            rr = [r for r in rows if sp == "all" or r["split"] == sp]
            if not rr:
                continue
            if name.endswith("uniform-random"):
                fr = {k: round(statistics.mean(r["frac"][k] for r in rr), 4) for k in ("correct", "safe", "harmful")}
            else:
                cnt = Counter(r["label"] for r in rr)
                fr = {k: round(cnt[k] / len(rr), 4) for k in ("correct", "safe", "harmful")}
            base_rows.append({"model": name, "split": sp, "n_cases": len({r["case"] for r in rr}),
                              "correct_rate": fr["correct"], "safe_rate": fr["safe"], "harmful_rate": fr["harmful"]})
    flat = [{k: r.get(k) for k in ("model_name", "tier", "provider", "model", "model_version", "case", "split", "class",
                                    "variant", "repeat", "answered_id", "label", "valid", "status", "chosen_position",
                                    "correct_positions", "case_normalized", "tokens_in", "tokens_out", "tokens_reasoning",
                                    "cost_usd", "latency_s", "transport_retries", "ts")} for r in calls]
    pair_rows = pairwise(scored, [n for n in models if any(r["model_name"] == n for r in scored)])
    for fname, rows in (("S5_3_models.csv", model_rows), ("S5_3_baselines.csv", base_rows), ("S5_3_cases.csv", case_rows),
                        ("S5_3_pairwise.csv", pair_rows),
                        ("S5_3_by_class.csv", class_rows), ("S5_3_calls.csv", flat)):
        if not rows:
            continue
        with open(SUMMARY / fname, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    L = [f"# S5.3 sub-agent comparison — {tag}", "",
         f"{len(cases)} cases × {len(VARIANTS)} prompt variants × {repeats} repeats; {len(calls)} calls "
         f"({sum(1 for r in calls if r['label'] == 'error')} transport errors, excluded). Reference: {reference}.", "",
         "| model | variant | correct | 95 % CI | safe | harmful | invalid | consistency | cost / decision (USD) | p50 latency (s) |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in model_rows:
        if r["split"] == "all":
            L.append(f"| {r['model']} | {r['variant']} | {r['correct_rate']} | {r['correct_ci95']} | {r['safe_rate']} | "
                     f"{r['harmful_rate']} | {r['invalid_rate']} | {r['consistency']} | {r['cost_usd_per_decision']} | {r['latency_s_p50']} |")
    for r in base_rows:
        if r["split"] == "all":
            L.append(f"| {r['model']} | — | {r['correct_rate']} | | {r['safe_rate']} | {r['harmful_rate']} | | | | |")
    (SUMMARY / "S5_3_summary.md").write_text("\n".join(L) + "\n")
    return SUMMARY


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", default="S5_3")
    ap.add_argument("--models", default=str(MODELS_YAML))
    ap.add_argument("--models-only", default=None, help="comma list of model names")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4, help="concurrent calls per provider")
    ap.add_argument("--retry-errors", action="store_true", help="redo calls that ended in a transport error")
    ap.add_argument("--summarize", action="store_true", help="only rebuild results/summary/ from calls.jsonl")
    ap.add_argument("--allow-unfrozen", action="store_true", help="tests only: run although eval/ is not frozen")
    a = ap.parse_args(argv)
    ok, problems = freeze_eval.verify(EVAL)
    if ok is not True and not a.allow_unfrozen:
        raise SystemExit(f"eval/ must be frozen and unchanged before a model run: {problems or 'not frozen'}")
    models = load_models(a.models)
    if a.models_only:
        models = {k: v for k, v in models.items() if k in a.models_only.split(",")}
    import yaml
    reference = yaml.safe_load(Path(a.models).read_text()).get("reference")
    cases = load_bench_cases()
    if not a.summarize:
        run(a.tag, models, cases, a.variants.split(","), a.repeats, a.workers, a.retry_errors)
    print(f"summary: {summarize(a.tag, load_models(a.models), cases, a.repeats, reference)}")


if __name__ == "__main__":
    sys.exit(main())
