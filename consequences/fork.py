"""Experiment C (2)-(4): fork every frozen case at its failed gate, one new thread per menu option.

  python -m consequences.fork                    # C1: all gates on          -> results/C/C_options.csv
  python -m consequences.fork --c2               # C2: gates off after fork  -> results/C/C2_options.csv
  python -m consequences.fork --only C01,C10     # a subset (resumable: finished branches are skipped)

Protocol (eval/consequences.yaml, frozen with eval/):
  * source thread: test_runs/E2_<fault> for fault cases, test_runs/E1_cssni3_d4 (C10) / E1_inmno3 (C11) for D4 / R5;
  * fork point: the checkpoint whose next node is `recover`, with last_node / gate code / attempts[node] equal to the
    captured case; its state is copied into a new thread (paths rewritten to the new run directory, files of the source
    thread written before the fork copied, nothing later);
  * the option is injected through Command(resume={"option": ...}) at a one-shot human interrupt at the fork point
    (run_meta.fork_human); everything else as in E2: all gates on, rules on, no sub-agent, same retry budget, the
    fault's remaining scripted job events, then "all"; later human questions get the published decision (R5 / D4) or
    `stop` (then human_needed = true);
  * numbers are compared with the clean E1 replay, quantity by quantity, with the frozen tolerances.
Nothing is computed: replay links stored energies; a frame without one ends at G3 UNMATCHED.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from iris_agent import config as cfgmod, freeze_eval  # noqa: E402
from iris_agent.inject import DEFAULT_HUMAN, NATURAL, load_faults, submitted_runs  # noqa: E402

RUNS = ROOT / "test_runs"
OUT = ROOT / "results" / "C"
CFG_DIR = Path("/tmp/claude-0/cfgs")                      # the build workspace; elsewhere the repo configs/ are used
if not CFG_DIR.is_dir():
    CFG_DIR = ROOT / "configs"
NATURAL_SOURCE = {"C10": ("E1_cssni3_d4", "cssni3_d4"), "C11": ("E1_inmno3", "inmno3")}
SKIP_FILES = {"audit.jsonl", "iris.sqlite", "llm_calls.jsonl", "inject_report.json"}


def _ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _cases():
    y = yaml.safe_load((ROOT / "eval" / "subagent_cases.yaml").read_text())["cases"]
    out = []
    for c in y:
        cap = json.loads((ROOT / "eval" / "subagent_cases" / f"{c['id']}.json").read_text())
        pv = cap["prompt_values"]
        out.append({**c, "node": cap["node"], "code": cap["code"], "attempts": int(pv.get("attempts", 0)),
                    "menu": [m["id"] for m in cap["menu"]]})
    return out


def _saver(thread):
    from langgraph.checkpoint.sqlite import SqliteSaver
    return SqliteSaver(sqlite3.connect(str(RUNS / thread / "iris.sqlite")))


def find_fork(thread, node, code, attempts):
    """The (earliest) checkpoint where recover is next, for this node / code / retries used."""
    hits = []
    for ck in _saver(thread).list({"configurable": {"thread_id": thread}}):
        cv = ck.checkpoint["channel_values"]
        if "branch:to:recover" not in cv:
            continue
        if cv.get("last_node") == node and (cv.get("gate") or {}).get("code") == code \
                and (cv.get("attempts") or {}).get(node, 0) == attempts:
            hits.append((ck.checkpoint["ts"], {k: v for k, v in cv.items() if not k.startswith("branch:")}))
    return min(hits, key=lambda h: h[0]) if hits else (None, None)


def _rewrite(o, old, new):
    if isinstance(o, dict):
        return {k: _rewrite(v, old, new) for k, v in o.items()}
    if isinstance(o, list):
        return [_rewrite(v, old, new) for v in o]
    if isinstance(o, str):
        return o.replace(old, new)
    return o


def _consumed(thread, t_fork):
    """Scripted answers the source thread had used before the fork: (job events, human answers)."""
    log = [json.loads(x) for x in (RUNS / thread / "audit.jsonl").read_text().splitlines()]
    res = [r for r in log if r["kind"] == "resume" and _ts(r["ts"]) <= t_fork and isinstance(r.get("answer"), dict)]
    jobs = sum(1 for r in res if r["answer"].get("event") == "job_end")
    hum = sum(1 for r in res if "option" in r["answer"] or "fix" in r["answer"])
    return jobs, hum


def baseline(system):
    cv = _saver(f"E1_{system}").get({"configurable": {"thread_id": f"E1_{system}"}})["channel_values"]
    return {"rows": {r["name"]: r["value"] for r in cv["report"]["rows"]},
            "active": sorted((cv.get("selection") or {}).get("active") or []),
            "n_energies": (cv.get("energies") or {}).get("n"),
            "runs": sum(n for _, n in submitted_runs(RUNS / f"E1_{system}"))}


def compare(st, base, tol):
    mine = {r["name"]: r["value"] for r in (st.get("report") or {}).get("rows", [])}
    scope = []
    if set(mine) != set(base["rows"]):
        scope.append(f"quantities {len(mine)} vs {len(base['rows'])}")
    if sorted((st.get("selection") or {}).get("active") or []) != base["active"]:
        scope.append("active set")
    if (st.get("energies") or {}).get("n") != base["n_energies"]:
        scope.append(f"energies {(st.get('energies') or {}).get('n')} vs {base['n_energies']}")
    worst, worst_rel, n_diff, n_tol, first = 0.0, 0.0, 0, 0, ""
    for k in set(mine) & set(base["rows"]):
        a, b, t = mine[k], base["rows"][k], tol.get(k)
        num = isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool)
        if not num:
            if a != b:
                n_diff += 1
                first = first or k
            continue
        d = abs(a - b)
        worst = max(worst, d)
        if d <= 1e-12:
            continue
        if t is not None and d <= t:
            n_tol += 1
            worst_rel = max(worst_rel, d / t if t else 0)
        else:
            n_diff += 1
            first = first or k
            if t:
                worst_rel = max(worst_rel, d / t)
    numbers = "different" if n_diff else "within tolerance" if n_tol else "identical"
    return {"numbers": numbers, "max_abs_dev": worst, "max_dev_over_tol": round(worst_rel, 4),
            "n_quantities_differ": n_diff, "n_within_tol_not_identical": n_tol, "first_differing": first,
            "scope_change": "; ".join(scope)}


def run_branch(case, option, src_thread, cfg_path, ck_ts, values, consumed, fault, gates_off=False):
    from iris_agent.run import Session
    tag = "C2" if gates_off else "C"
    thread = f"{tag}_{case['id']}_{option}"
    d = RUNS / thread
    if d.exists():
        k = 2
        while (RUNS / f"{thread}_r{k}").exists():
            k += 1
        thread = f"{thread}_r{k}"
    src_dir = RUNS / src_thread
    t_fork = _ts(ck_ts)
    with Session(cfg_path, thread, tag=tag, fault_id=case.get("fault")) as s:
        new_dir = s.run_dir
        n_copied = 0
        for f in src_dir.rglob("*"):         # the source thread's files as they were at the fork
            if f.is_file() and f.name not in SKIP_FILES and f.stat().st_mtime <= t_fork:
                dst = new_dir / f.relative_to(src_dir)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                n_copied += 1
        v = _rewrite(values, str(src_dir), str(new_dir))
        meta = dict(v.get("run_meta") or {})
        meta.update({"run_id": s.meta["run_id"], "tag": tag, "fork_of": src_thread, "fork_ts": ck_ts,
                     "case": case["id"], "option": option,
                     "fork_human": {"node": case["node"], "code": case["code"], "attempts": case["attempts"]},
                     "gates_off_after_fork": bool(gates_off)})
        v.update({"thread_id": thread, "run_meta": meta, "config": {**v["config"], "thread_id": thread}})
        s.meta = meta
        s.audit.set_context(**meta)
        s.audit.write("run", None, event="fork", source_thread=src_thread, checkpoint_ts=ck_ts, option=option,
                      files_copied=n_copied, gates_off_after_fork=bool(gates_off))
        s.graph.update_state(s.cfg, v, as_node=case["node"])
        res = s.cont()
        steps, human_needed = [], False
        if res["status"] != "interrupted" or res["interrupt"][0].get("code") != case["code"]:
            raise RuntimeError(f"{thread}: no interrupt at the fork point ({res['status']})")
        jobs = list(((fault or {}).get("injection") or {}).get("jobs", []))[consumed[0]:]
        human = list(((fault or {}).get("injection") or {}).get("human", []))[consumed[1]:]
        res = s.resume({"option": option})
        n_default = 0
        while res["status"] in ("waiting_on_jobs", "interrupted"):
            if res["status"] == "waiting_on_jobs":
                if jobs:
                    ev = jobs.pop(0)
                else:
                    ev, n_default = "all", n_default + 1
                    if n_default > 5:
                        steps.append("still waiting after 5 default job-end events")
                        break
                ev = {"event": "job_end", "parts": "all"} if ev == "all" else ev
                steps.append(f"jobs: {ev}")
            else:
                code = res["interrupt"][0].get("code")
                if human:
                    ev = human.pop(0)
                elif code in DEFAULT_HUMAN:
                    ev = DEFAULT_HUMAN[code]
                else:
                    ev, human_needed = {"option": "stop"}, True
                steps.append(f"human ({code}): {ev}")
            res = s.resume(ev)
        st = s.graph.get_state(s.cfg).values
        log = s.audit.read()
    return thread, res, st, log, steps, human_needed, t_fork


def classify(r):
    if r["option"] == "stop":
        return "stopped"
    if r["final"] != "completed":
        return "not-evaluable" if "UNMATCHED" in r["gates_after_fork"] else "rejected"
    if r["scope_change"]:
        return "scope-change"
    if r["numbers"] == "different":
        return "accepted-wrong"
    return "accepted-?"          # correct vs wasted: decided per case below


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--c2", action="store_true", help="gates off after the fork, non-reference options only")
    ap.add_argument("--csv-only", action="store_true", help="only rewrite the CSV from the branches file")
    a = ap.parse_args(argv)
    if a.csv_only:
        return write_csv("C2" if a.c2 else "C", yaml.safe_load((ROOT / "eval" / "consequences.yaml").read_text()))
    ok, probs = freeze_eval.verify(ROOT / "eval")
    if ok is not True:
        raise SystemExit(f"eval/ not frozen / changed: {probs}")
    cons = yaml.safe_load((ROOT / "eval" / "consequences.yaml").read_text())
    faults = {f["id"]: f for f in load_faults(ROOT / "eval" / "faults.yaml")}
    cases = _cases()
    if a.only:
        cases = [c for c in cases if c["id"] in a.only.split(",")]
    OUT.mkdir(parents=True, exist_ok=True)
    name = "C2" if a.c2 else "C"
    jl = OUT / f"{name}_branches.jsonl"
    done = {(r["case"], r["option"]) for r in map(json.loads, jl.read_text().splitlines())} if jl.is_file() else set()
    for c in cases:
        if c["id"] in NATURAL_SOURCE:
            src, system = NATURAL_SOURCE[c["id"]]
            fault = None
            cfg_path = CFG_DIR / f"{system}.yaml"
        else:
            fault = faults[c["fault"]]
            src, system = f"E2_{c['fault']}", fault["system"]
            cfg_path = RUNS / "E2" / "configs" / f"{c['fault']}.yaml"
        ck_ts, values = find_fork(src, c["node"], c["code"], c["attempts"])
        labels = {o: lab for lab, opts in c["labels"].items() for o in opts}
        opts = c["menu"]
        if a.c2:
            opts = [o for o in opts if labels.get(o) != "correct" and o != "stop"]
        for opt in opts:
            if (c["id"], opt) in done:
                continue
            row = {"case": c["id"], "split": c["split"], "class": c["class"], "system": system, "fault": c.get("fault"),
                   "gate": f"G{c['node'][1]}", "code": c["code"], "option": opt, "label": labels.get(opt, "unlabelled"),
                   "source_thread": src, "fork_checkpoint": ck_ts}
            if ck_ts is None:
                row.update({"final": "no fork point", "consequence": "not-evaluable",
                            "note": "the source thread has no checkpoint with this node / code / attempts"})
            else:
                consumed = _consumed(src, _ts(ck_ts))
                try:
                    thread, res, st, log, steps, human_needed, t_fork = run_branch(
                        c, opt, src, cfg_path, ck_ts, values, consumed, fault, gates_off=a.c2)
                except Exception as exc:          # recorded, never hidden
                    row.update({"final": f"error: {type(exc).__name__}: {exc}"[:300], "consequence": "not-evaluable"})
                    with open(jl, "a") as fh:
                        fh.write(json.dumps(row) + "\n")
                    print(c["id"], opt, row["final"])
                    continue
                k0 = next(i for i, r in enumerate(log) if r["kind"] == "fix" and r.get("fork_point"))
                after = log[k0 + 1:]
                gates = [r for r in after if r["kind"] == "gate"]
                fails = [f"{r['gate']} {r.get('gate_code')}" for r in gates if r.get("outcome") in ("fail", "fail_ignored")]
                nxt = gates[0] if gates else None
                subs = submitted_runs(RUNS / thread)
                total = sum(n for _, n in subs)
                post = sum(n for t, n in subs if _ts(t) > t_fork)
                base = baseline(system)
                cmpd = compare(st, base, cons["tolerances"].get(system, {})) if res["status"] == "completed" else {}
                row.update({"thread": thread, "final": res["status"],
                            "next_gate": "" if not nxt else f"{nxt['gate']} {nxt.get('gate_code')} {nxt.get('outcome')}",
                            "gates_after_fork": "; ".join(fails), **cmpd,
                            "runs_submitted": total, "baseline_runs": base["runs"],
                            "extra_runs": max(0, total - base["runs"]), "runs_after_fork": post,
                            "attempts_after_fork": sum(1 for r in log[k0:] if r["kind"] == "fix"),
                            "human_needed": human_needed, "replay_assumed": post > 0,
                            "steps": " | ".join(steps)[:500]})
                if a.c2:
                    row["silent_wrong"] = res["status"] == "completed" and bool(
                        cmpd.get("scope_change") or cmpd.get("numbers") == "different")
                    row["gates_would_fail"] = row["gates_after_fork"]
                row["consequence"] = classify(row)
            with open(jl, "a") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
            print(c["id"], opt, row.get("final"), row.get("consequence"), row.get("numbers", ""), row.get("gates_after_fork", ""))
    write_csv(name, cons)


def write_csv(name, cons):
    """consequence_v1 / contradicts_label_v1: the frozen rules of eval/consequences.yaml. consequence /
    contradicts_label: the same plus consequences/adjustments.yaml (accepted_equivalent_settings). replay_oracle: the
    branch was caught at G6 only through rows that read the stored campaign files (consequences/g6_oracle.py)."""
    from consequences.g6_oracle import catches
    from consequences.replay_tags import CODE_TAG, failures
    adj = yaml.safe_load((ROOT / "consequences" / "adjustments.yaml").read_text())
    rows = [json.loads(x) for x in (OUT / f"{name}_branches.jsonl").read_text().splitlines()]
    best = {}
    for r in rows:                              # the cheapest branch per case that completes correctly
        if r.get("consequence") == "accepted-?":
            best[r["case"]] = min(best.get(r["case"], 10 ** 9), r["runs_submitted"])
    for r in rows:
        if r.get("consequence") == "accepted-?":
            r["consequence"] = "accepted-wasted" if r["runs_submitted"] > best[r["case"]] else "accepted-correct"
        lab = r.get("label")
        comp = cons["compatible_with_label"]
        r["consequence_v1"] = r["consequence"]
        r["contradicts_label_v1"] = (r["consequence"] not in comp.get(lab, [])) if lab in comp else None
        r["scf_only_option"] = r["option"] in adj["scf_only_options"]
        r["mixing_caveat_system"] = adj["mixing_caveat_systems"].get(r["system"], "")
        if r["scf_only_option"] and r.get("final") == "completed" and r.get("numbers") == "identical" \
                and not r.get("scope_change"):
            r["consequence"] = "accepted_equivalent_settings"
        fixes_after = []
        if r.get("thread"):
            lg = [json.loads(x) for x in (RUNS / r["thread"] / "audit.jsonl").read_text().splitlines()]
            k0 = next((i for i, x in enumerate(lg) if x["kind"] == "fix" and x.get("fork_point")), None)
            fixes_after = [x for x in lg[k0 + 1:] if x["kind"] == "fix"] if k0 is not None else []
        rep = fixes_after[0] if fixes_after else {}
        repaired = rep.get("level") == "rule" or (rep.get("level") == "human" and rep.get("gate_code") in NATURAL)
        r["gate_refused_option"] = bool(r["option"] != "stop" and r.get("final") == "completed"
                                        and str(r.get("next_gate", "")).endswith(" fail") and repaired)
        r["repair"] = ((f"rule {rep.get('rule_id')}" if rep.get("level") == "rule" else
                        f"published decision {rep.get('option_id')}") if r["gate_refused_option"] else "")
        # replay supplied the outcome of the resubmitted jobs: after the fork every job event was the default
        # "all finish" (the fault's scripted failures were used up before the fork)
        st = [x for x in str(r.get("steps", "")).split(" | ") if x.startswith("jobs:")]
        r["scripted_failures_ran_out"] = bool(r.get("final") == "completed" and r["code"] in ("WALLTIME", "NELM")
                                              and st and all("'parts': 'all'" in x and "failed" not in x for x in st))
        if r["gate_refused_option"]:
            r["consequence"] = "gate_refused_option"
        comp2 = {k: comp.get(k, []) + adj["compatible_with_label"].get(k, []) + adj.get("compatible_with_label_v3", {}).get(k, [])
                 for k in comp}
        r["contradicts_label"] = (r["consequence"] not in comp2.get(lab, [])) if lab in comp2 else None
        c = catches(r["thread"]) if r.get("thread") else []
        r["g6_caught"] = bool(c)
        r["replay_oracle"] = any(x["replay_oracle"] for x in c) if c else False
        r["g6_oracle_rows"] = "; ".join(sorted({x["oracle_rows_failing"] for x in c if x["oracle_rows_failing"]}))
        fl = failures(r["thread"], after_fork=True) if r.get("thread") else []
        r["post_fork_catch_tags"] = "; ".join(f"{g} {cd}: {t}" for g, cd, t in fl if t != "none")
        r["replay_oracle"] = r["replay_oracle"] or any(t == "replay_oracle" for _, _, t in fl)
        r["stored_reference"] = any(t == "stored_reference" for _, _, t in fl)
        r["fork_gate_tag"] = CODE_TAG.get((r["gate"], r["code"]), "none")   # the case's own failed gate
    rows.sort(key=lambda r: (r["case"], r["option"]))
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(OUT / f"{name}_options.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(OUT / f"{name}_options.csv", len(rows), "branches;", sum(bool(r["contradicts_label"]) for r in rows),
          "contradict their label (v1 rules:", sum(bool(r["contradicts_label_v1"]) for r in rows), ")")

if __name__ == "__main__":
    main()
