"""Experiment E with an extra model that is not in the frozen panel (eval/models.yaml), e.g. Qwen served by vLLM.

Not part of the frozen intake. Same frozen prompt, schema, requests and code (run_e.one_call); the model spec comes
from a separate models file (eval_extra/). Writes a NEW folder: the rows of an existing run (--with) are copied
unchanged so one scoring pass gives the whole table; the original folders are never touched.

  python -m intake.run_extra --models-file eval_extra/models_qwen.yaml --model qwen-27b --repeats 5 \
         --with results/E/v2_retry --dst results/E/v2_qwen
  python -m intake.run_e --score --out results/E/v2_qwen

Resumable: rerun the same command; finished (model, request, repeat) rows are skipped, failed ones retried.
Refuses to run unless intake/ verifies against FROZEN.sha256.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import intake.run_e as E  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-file", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--with", dest="with_", default=None, help="existing run folder whose rows are copied in")
    ap.add_argument("--dst", default=None)
    ap.add_argument("--ping", action="store_true", help="one call on request E01 only, printed, nothing written")
    a = ap.parse_args(argv)
    bad = E.verify()
    if bad:
        raise SystemExit("refusing: " + "; ".join(bad))
    from iris_agent.llm import load_models
    spec = load_models(ROOT / a.models_file)[a.model]
    reqs = E.requests()
    if a.ping:
        from intake.llm_json import llm_json
        from intake import schema as S
        r = llm_json(spec, S.system_prompt(), S.user_prompt(reqs[0]["text"], reqs[0].get("attachments") or []))
        print(json.dumps({k: r.get(k) for k in ("valid", "error", "model_version", "tokens_in", "tokens_out",
                                                "tokens_reasoning", "latency_s")}, indent=1))
        print(json.dumps(r.get("obj"), indent=1))
        return
    if not a.dst:
        raise SystemExit("--dst is required")
    dst = ROOT / a.dst
    dst.mkdir(parents=True, exist_ok=True)
    jl = dst / "calls.jsonl"
    if not jl.is_file() and a.with_:
        rows = [x for x in (ROOT / a.with_ / "calls.jsonl").read_text().splitlines() if x.strip()]
        rows = [x for x in rows if json.loads(x)["model"] != a.model]
        jl.write_text("\n".join(rows) + "\n")
        print(f"copied {len(rows)} rows from {a.with_}")
    have = [json.loads(x) for x in jl.read_text().splitlines()] if jl.is_file() else []
    done = {(r["model"], r["request"], r["repeat"]) for r in have if not r.get("llm_error")}
    failed = {(r["model"], r["request"], r["repeat"]) for r in have if r.get("llm_error")}
    if failed & {(a.model, q["id"], k) for q in reqs for k in range(a.repeats)}:
        keep = [r for r in have if (r["model"], r["request"], r["repeat"]) not in failed or r["model"] != a.model]
        (dst / "failed_attempts.jsonl").open("a").write(
            "".join(json.dumps(r, default=str) + "\n" for r in have if r not in keep))
        jl.write_text("".join(json.dumps(r, default=str) + "\n" for r in keep))
        print(f"{len(have) - len(keep)} failed rows moved to failed_attempts.jsonl and retried")
    todo = [(q, k) for q in reqs for k in range(a.repeats) if (a.model, q["id"], k) not in done]
    print(f"{len(todo)} calls to make for {a.model} ({spec['model']} at {spec.get('base_url')})")
    E.OUT = dst

    def job(t):
        q, k = t
        return E.one_call(a.model, spec, q, k)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(job, todo):
            with open(jl, "a") as fh:
                fh.write(json.dumps(r, default=str) + "\n")
            print(r["model"], r["request"], r["repeat"], r["resolved"]["status"], r["g0"]["code"], r.get("llm_error") or "")


if __name__ == "__main__":
    main()
