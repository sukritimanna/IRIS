"""Cost of the language-model layer: tokens, dollars (where list prices were recorded) and latency per experiment.

Reads the call logs written by the benchmark and intake runs (one JSON line per call) and, for the live BaTiO3
campaign, the audit logs of its run directories (intake calls are logged by f0 with tokens and latency).

  python -m eval_extra.cost_summary                       # results/S5_3, results/E (v1 + v2), results/LOSO, A_loso_llm
  python -m eval_extra.cost_summary --live <run_dir> ...  # add the live run directories (test_runs/<thread>/audit.jsonl)

Output: results/COST/cost_summary.csv (one row per experiment x model) and cost_by_experiment.csv (one row per
experiment, all models pooled), and the same printed. Prices come from eval/models.yaml (price_usd_per_mtok); a model
without a recorded price has an empty cost cell, never an estimate.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "results" / "COST"

SOURCES = {  # experiment -> (calls.jsonl path, model-name field, filter)
    "benchmark (53 cases x 10 repeats, guided + bare)": (ROOT / "results" / "S5_3" / "calls.jsonl", "model_name", None),
    "intake v1 (50 requests x 5 repeats)": (ROOT / "results" / "E" / "calls.jsonl", "model", lambda r: r.get("model") != "baseline"),
    "intake v2 (50 requests x 5 repeats)": (ROOT / "results" / "E_v2" / "calls.jsonl", "model", lambda r: r.get("model") != "baseline"),
    "transfer, guidance sentence removed (7 cases x 10 repeats)": (ROOT / "results" / "LOSO" / "A_loso_llm" / "calls.jsonl", "model_name", None),
}


def prices() -> dict:
    y = yaml.safe_load((ROOT / "eval" / "models.yaml").read_text())
    return {k: v.get("price_usd_per_mtok") for k, v in y["models"].items()}


def field(r: dict, *names):
    for n in names:
        if n in r and r[n] not in (None, ""):
            return r[n]
    return None


def rows_of(path: Path):
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def summarise(name: str, recs: list, model_key: str, price: dict):
    by = defaultdict(list)
    for r in recs:
        by[r.get(model_key)].append(r)
    out = []
    for m, rr in sorted(by.items()):
        tin = [field(r, "tokens_in", "llm_tokens_in") or 0 for r in rr]
        tout = [field(r, "tokens_out", "llm_tokens_out") or 0 for r in rr]
        trs = [field(r, "tokens_reasoning", "llm_tokens_reasoning") or 0 for r in rr]
        lat = [field(r, "latency_s", "llm_latency_s") for r in rr]
        lat = [float(x) for x in lat if x is not None]
        p = price.get(m)
        cost = None
        if p:
            cost = (sum(tin) * p["in"] + (sum(tout) + sum(trs)) * p["out"]) / 1e6
        out.append({"experiment": name, "model": m, "calls": len(rr), "tokens_in": sum(tin), "tokens_out": sum(tout),
                    "tokens_reasoning": sum(trs), "tokens_in_per_call": round(sum(tin) / len(rr), 1),
                    "tokens_out_per_call": round((sum(tout) + sum(trs)) / len(rr), 1),
                    "cost_usd": round(cost, 4) if cost is not None else "",
                    "cost_usd_per_call": round(cost / len(rr), 6) if cost is not None else "",
                    "latency_s_p50": round(statistics.median(lat), 2) if lat else "",
                    "latency_s_p95": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 2) if lat else "",
                    "latency_s_total": round(sum(lat), 1) if lat else ""})
    return out


def live_rows(run_dirs: list[Path]):
    """f0 intake calls in the audit logs of live runs: lines with kind node f0 carrying llm meta, or fix lines."""
    recs = []
    for d in run_dirs:
        a = d / "audit.jsonl"
        if not a.is_file():
            continue
        for line in a.read_text().splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            meta = e.get("llm") or e.get("llm_meta") or {}
            if e.get("tokens_in") or meta.get("tokens_in"):
                recs.append({"model_name": e.get("model_version") or meta.get("model") or "intake model",
                             "tokens_in": e.get("tokens_in") or meta.get("tokens_in"),
                             "tokens_out": e.get("tokens_out") or meta.get("tokens_out"),
                             "tokens_reasoning": meta.get("tokens_reasoning"),
                             "latency_s": e.get("latency_s") or meta.get("latency_s"), "run": d.name})
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", nargs="*", default=[])
    a = ap.parse_args()
    price = prices()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, (path, key, flt) in SOURCES.items():
        recs = rows_of(path)
        if flt:
            recs = [r for r in recs if flt(r)]
        if not recs:
            print(f"(no calls found for {name}: {path})")
            continue
        rows += summarise(name, recs, key, price)
    live = live_rows([Path(p) for p in a.live])
    if live:
        rows += summarise("live BaTiO3 campaign (intake calls, 4 runs)", live, "model_name", price)
    if not rows:
        raise SystemExit("no call logs found; run this on the machine that holds results/S5_3, results/E and results/LOSO")
    with (OUT / "cost_summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    # pooled per experiment
    pooled = []
    for name in dict.fromkeys(r["experiment"] for r in rows):
        rr = [r for r in rows if r["experiment"] == name]
        priced = [r for r in rr if r["cost_usd"] != ""]
        pooled.append({"experiment": name, "models": len(rr), "calls": sum(r["calls"] for r in rr),
                       "tokens_in": sum(r["tokens_in"] for r in rr), "tokens_out_incl_reasoning": sum(r["tokens_out"] + r["tokens_reasoning"] for r in rr),
                       "cost_usd_priced_models": round(sum(r["cost_usd"] for r in priced), 2) if priced else "",
                       "priced_models": ";".join(r["model"] for r in priced),
                       "latency_s_p50_range": f"{min(r['latency_s_p50'] for r in rr if r['latency_s_p50'] != '')}-{max(r['latency_s_p50'] for r in rr if r['latency_s_p50'] != '')}" if any(r['latency_s_p50'] != '' for r in rr) else "",
                       "latency_s_total_all_models": round(sum(r["latency_s_total"] for r in rr if r["latency_s_total"] != ""), 1)})
    with (OUT / "cost_by_experiment.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pooled[0]))
        w.writeheader()
        w.writerows(pooled)
    for r in rows:
        print(f"{r['experiment'][:48]:48s} {r['model']:18s} {r['calls']:5d}  in {r['tokens_in']:8d}  out {r['tokens_out'] + r['tokens_reasoning']:7d}  "
              f"${r['cost_usd'] if r['cost_usd'] != '' else '   n/a':>8}  p50 {r['latency_s_p50']}s  p95 {r['latency_s_p95']}s")
    print(f"written: {OUT / 'cost_summary.csv'}, {OUT / 'cost_by_experiment.csv'}")


if __name__ == "__main__":
    main()
