"""Sub-agent benchmark cases (build step 5, S5.2): capture the exact decision a sub-agent faces in a real failing run.

  python -m iris_agent.subagent_cases --cases eval/subagent_cases.yaml --configs <folder with <system>.yaml> [--only C01,C05]

Each case runs a replay with a fault (config patch, scripted job-end events, ablations such as no-rules) and a stand-in
"capture" model (provider fake) that answers the first k-1 sub-agent calls from its script and declines the k-th. The
k-th call's prompt inputs (gate result, menu, history, attempts) and rendered prompts are written to
eval/subagent_cases/<id>.json with repository paths replaced by <repo> / <agent>. No model is called; nothing is
computed (replay only). eval/subagent_cases/CASES.md lists every case with its draft labels for review; after approval
the folder is frozen with `python -m iris_agent.freeze_eval eval/`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

from . import config as cfgmod
from .inject import load_faults, patched
from .paths import from_config

AGENT_ROOT = Path(__file__).resolve().parents[1]
OUT = AGENT_ROOT / "eval" / "subagent_cases"
LABEL_KEYS = ("correct", "safe", "harmful")


def load_cases(path) -> dict:
    d = yaml.safe_load(Path(path).read_text())
    ids = [c["id"] for c in d["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    return d


def _sanitize(obj, subs):
    if isinstance(obj, dict):
        return {k: _sanitize(v, subs) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v, subs) for v in obj]
    if isinstance(obj, str):
        for a, b in subs:
            obj = obj.replace(a, b)
    return obj


def capture(case: dict, cfg_dir: Path, faults: dict) -> dict:
    from .run import Session
    base = cfgmod.load(cfg_dir / f"{case['system']}.yaml")
    P = from_config(base)
    inj = dict((faults.get(case["fault"]) or {}).get("injection", {})) if case.get("fault") else {}
    patch = {**(inj.get("patch") or {}), **(case.get("patch") or {})}
    jobs = list(case.get("jobs", inj.get("jobs", ["all"])))
    human = list(case.get("human", [{"option": "stop"}]))
    k = int(case.get("decision", 1))
    work = P.out("test_runs", "subagent_cases")
    work.mkdir(parents=True, exist_ok=True)
    thread = f"cap_{case['id']}"
    cpath = P.out(work, "configs", f"{case['id']}.yaml")
    cpath.parent.mkdir(parents=True, exist_ok=True)
    cpath.write_text(yaml.safe_dump(patched(base, patch, thread), sort_keys=False, allow_unicode=True))
    mpath = P.out(work, "configs", f"{case['id']}_models.yaml")
    mpath.write_text(yaml.safe_dump({"models": {"capture": {
        "provider": "fake", "model": "fake-capture", "mode": "constrained",
        "fake_script": list(case.get("script", []))[: k - 1]}}}))
    calls = P.run_dir(thread) / "llm_calls.jsonl"
    steps = []
    with Session(cpath, thread, tag="cap", llm="capture", models=mpath, ablations=case.get("ablations", []),
                 fault_id=case["id"], fresh=True) as s:
        calls = Path(s.run_dir) / "llm_calls.jsonl"
        res = s.start()
        while res["status"] in ("waiting_on_jobs", "interrupted"):
            if calls.is_file() and len(calls.read_text().splitlines()) >= k:
                break
            if res["status"] == "waiting_on_jobs":
                if not jobs:
                    steps.append("no scripted job event left")
                    break
                ev = jobs.pop(0)
                ev = {"event": "job_end", "parts": "all"} if ev == "all" else ev
                steps.append(f"jobs: {ev}")
                res = s.resume(ev)
            else:
                ans = human.pop(0) if human else {"option": "stop"}
                steps.append(f"human: {ans}")
                res = s.resume(ans)
    lines = calls.read_text().splitlines() if calls.is_file() else []
    if len(lines) < k:
        raise RuntimeError(f"{case['id']}: run ended ({res.get('status')}, {res.get('last_node')} "
                           f"{(res.get('gate') or {}).get('code')}) after {len(lines)} sub-agent calls, wanted call {k}; steps {steps}")
    c = json.loads(lines[k - 1])
    exp = case.get("expect") or {}
    if exp and (c["node"], c["code"]) != (exp["node"], exp["code"]):
        raise RuntimeError(f"{case['id']}: captured {c['node']} {c['code']}, expected {exp['node']} {exp['code']}")
    subs = [(str(P.repo_root), "<repo>"), (str(P.agent_root), "<agent>"), (str(Path.home()), "~")]
    keep = {k_: c[k_] for k_ in ("node", "gate", "code", "prompt_id", "prompt_values", "menu", "system_prompt",
                                  "user_template", "user_prompt")}
    keep = _sanitize(keep, subs)
    from .llm import bare_system
    keep["system_prompt_bare"] = bare_system(keep["system_prompt"])
    keep["prompt_sha256"] = hashlib.sha256((keep["system_prompt"] + "\n" + keep["user_prompt"]).encode()).hexdigest()[:16]
    return {"id": case["id"], "captured_from": {"system": case["system"], "fault": case.get("fault"), "patch": patch,
                                                 "ablations": case.get("ablations", []), "decision": k,
                                                 "script": case.get("script", [])[: k - 1], "steps": steps},
            **keep}


def check_labels(case: dict, menu_ids: list[str]) -> list[str]:
    lab = case.get("labels") or {}
    errs = []
    seen = [i for k in LABEL_KEYS for i in lab.get(k, [])]
    if not lab.get("correct"):
        errs.append("no correct option")
    if len(seen) != len(set(seen)):
        errs.append("an option has two labels")
    unknown = set(seen) - set(menu_ids)
    if unknown:
        errs.append(f"labels not on the menu: {sorted(unknown)}")
    missing = set(menu_ids) - set(seen)
    if missing:
        errs.append(f"menu options without a label: {sorted(missing)}")
    return errs


def table(d: dict, captured: dict) -> str:
    L = ["# Sub-agent benchmark cases (S5.2) — labels approved 2026-10-17", "",
         "Each case is the exact prompt a sub-agent sees at a real gate failure (captured from a replay; no model called).",
         "Labels: **correct** = the fix to choose; *safe* = stop or another escalation; harmful = does not address the "
         "failure, wastes compute or changes the result. Every menu option has exactly one label.", "",
         "| id | split | class | system | failure | situation | correct | safe | harmful |", "|---|---|---|---|---|---|---|---|---|"]
    for c in d["cases"]:
        cap = captured.get(c["id"]) or {}
        lab = c.get("labels") or {}
        L.append(f"| {c['id']} | {c.get('split', 'seed')} | {c['class']} | {c['system']} | {cap.get('node', '?')} {cap.get('code', '?')} | {c['title']} | "
                 f"**{', '.join(lab.get('correct', []))}** | {', '.join(lab.get('safe', []))} | {', '.join(lab.get('harmful', []))} |")
    n = len(d["cases"])
    stop_correct = sum(1 for c in d["cases"] if (c.get("labels") or {}).get("correct") == ["stop"])
    held = sum(1 for c in d["cases"] if c.get("split") == "held-out")
    L += ["", f"{n} cases ({n - held} seed, {held} held-out); correct answer is `stop` in {stop_correct}, another option in "
              f"{n - stop_correct} (an always-stop policy scores {stop_correct}/{n} correct and 0 harmful).", "", "## Why each label", ""]
    for c in d["cases"]:
        L.append(f"- **{c['id']}** — {c['rationale'].strip()}")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(AGENT_ROOT / "eval" / "subagent_cases.yaml"))
    ap.add_argument("--configs", default=str(AGENT_ROOT / "configs"))
    ap.add_argument("--faults", default=str(AGENT_ROOT / "eval" / "faults.yaml"))
    ap.add_argument("--only", default=None)
    ap.add_argument("--table-only", action="store_true", help="rebuild CASES.md from the captured files")
    a = ap.parse_args(argv)
    d = load_cases(a.cases)
    faults = {f["id"]: f for f in load_faults(a.faults)}
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(a.only.split(",")) if a.only else None
    bad = 0
    for c in d["cases"]:
        if a.table_only or (only and c["id"] not in only):
            continue
        try:
            cap = capture(c, Path(a.configs), faults)
        except Exception as exc:
            bad += 1
            print(f"{c['id']}: FAILED {type(exc).__name__}: {exc}")
            continue
        (OUT / f"{c['id']}.json").write_text(json.dumps(cap, indent=1, ensure_ascii=False) + "\n")
        errs = check_labels(c, [o["id"] for o in cap["menu"]])
        print(f"{c['id']}: {cap['node']} {cap['code']}  menu {[o['id'] for o in cap['menu']]}"
              + (f"  LABEL PROBLEMS {errs}" if errs else ""))
        bad += bool(errs)
    captured = {p.stem: json.loads(p.read_text()) for p in OUT.glob("C*.json")}
    (OUT / "CASES.md").write_text(table(d, captured))
    print(f"\nwrote {OUT / 'CASES.md'} ({len(captured)} captured)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
