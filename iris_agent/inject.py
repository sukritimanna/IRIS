"""Fault injection driven by eval/faults.yaml (runbook E2 = gated, E4 = ungated baseline, later E3/E9/E10).

  python -m iris_agent.inject --faults eval/faults.yaml --llm off --tag E2
  python -m iris_agent.inject --faults eval/faults.yaml --llm off --no-gates --tag E4
  python -m iris_agent.inject --faults eval/faults.yaml --tag E2 --only F001,F005 [--ablate no-rules]

Each fault runs in its own thread <tag>_<id> on configs/<system>.yaml with the fault's config patch
(replay mode only; recorded by f0), fed with the fault's scripted job-end events and human answers.

Gated run (default): the fault must be handled as `expected` says (failures, handling, final status,
submissions, and — for completed runs — numbers identical to the stored fit).
Ungated run (--no-gates): gates run and are logged but never stop the run; the report classifies each
outcome: harmless (completed, numbers identical), silent corruption (completed, numbers differ),
crashed, or stopped.

Refuses to run if eval/ was frozen and has changed since (freeze_eval). Report:
test_runs/<tag>/inject_report.{md,json}; patched configs in test_runs/<tag>/configs/.
"""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

import yaml

from . import config as cfgmod
from . import freeze_eval
from .paths import from_config

AGENT_ROOT = Path(__file__).resolve().parents[1]


def load_faults(path: str | Path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text())
    faults = data["faults"]
    ids = [f["id"] for f in faults]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate fault ids")
    return faults


def patched(cfg: dict, patch: dict, thread: str) -> dict:
    c = deepcopy(cfg)
    c["thread_id"] = thread
    c["run"]["mode"] = "replay"
    for dotted, v in (patch or {}).items():
        cur, keys = c, dotted.split(".")
        for k in keys[:-1]:
            cur = cur.setdefault(k, {})
        cur[keys[-1]] = v
    return c


def _same(a, b, rel=1e-6, ab=1e-9) -> bool:
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return a == b
    return abs(a - b) <= max(ab, rel * max(abs(a), abs(b)))


def compare_to_baseline(st: dict, P, system: str) -> tuple[bool | None, str]:
    """Every reported number (the G6 table) against the clean E1 replay of the same config (test_runs/E1_<system>);
    relative tolerance 1e-6 (BLAS round-off between machines). None if there is no E1 baseline."""
    a = P.agent_root / "test_runs" / f"E1_{system}" / "audit.jsonl"
    if not a.is_file():
        return None, f"no baseline (run: python -m iris_agent.run_e1 --only {system})"
    end = [json.loads(x) for x in a.read_text().splitlines() if '"kind": "end"' in x]
    if not end or end[-1].get("status") != "completed":
        return None, "baseline run not completed"
    base = {r["quantity"]: r["reported"] for r in end[-1].get("g6_table") or []}
    mine = {r["name"]: r["value"] for r in (st.get("report") or {}).get("rows", [])}
    missing = sorted(set(base) - set(mine))
    diff = sorted(k for k in set(base) & set(mine) if not _same(mine[k], base[k]))
    if not missing and not diff:
        return True, f"identical to the clean replay ({len(base)} numbers)"
    return False, f"differs from the clean replay: {len(diff)} numbers differ (first {diff[:3]}), {len(missing)} missing"


def compare_to_stored(st: dict, P, system: str | None = None) -> tuple[bool | None, str]:
    """Do the run's numbers equal the stored 12 Sep fit and grid (CsSnI3 plane), or, for every other config, the
    clean E1 replay of the same config? (None if there is no reference)."""
    m, rep = st.get("model") or {}, st.get("report") or {}
    if not P.has("reference_fit") or (system and system != "cssni3"):
        return compare_to_baseline(st, P, system) if system else (None, "no reference")
    if not m.get("fitted"):
        return None, "no fit"
    ref = json.loads(P.repo("reference_fit").read_text())
    dif = {k: abs(m["coefficients"][k] - v) for k, v in ref["coefficients"].items()}
    bad = [k for k, d in dif.items() if d > 1e-9]
    if abs(m["rms_meV"] - ref["rms_meV"]) > 1e-9:
        bad.append("RMS")
    if m.get("n_fit") != 545:
        bad.append(f"n_fit {m.get('n_fit')}")
    sg = (rep.get("summary") or {}).get("grid", {}).get("sg_count_grid")
    if sg is not None and sg != {"127": 30, "221": 1, "62": 900, "74": 30}:
        bad.append("frames by SG")
    if not bad:
        return True, "identical to the stored fit"
    return False, f"differs: {bad} (max |Δcoef| {max(dif.values()):.2e})"


DEFAULT_HUMAN = {"R5_BORDERLINE": {"option": "include_borderline"},       # the published decisions
                 "SECONDARY_COUPLED": {"option": "accept_secondary_hold"}}


def submitted_runs(run_dir: Path) -> list[tuple[str, int]]:
    """(UTC time, frames) of every f3 submission of the thread: round 0 = all matched frames, a resubmission = the
    frames of the resubmitted parts. In replay these are the DFT runs the campaign would have spent."""
    out = []
    d = Path(run_dir) / "f3_jobs"
    for f in sorted(d.glob("submission*.json")) if d.is_dir() else []:
        r = json.loads(f.read_text())
        parts = r["book"]["parts"]
        if r.get("round", 0) == 0:
            n = sum(len(v["frames"]) for v in parts.values())
        else:
            n = sum(len(parts[str(p)]["frames"]) for p in r.get("resubmitted_parts", []))
        out.append((r["submitted_utc"], n))
    return out


NATURAL = set(DEFAULT_HUMAN)       # decisions of the clean run (InMnO3 R5, CsSnI3 D4): not a fault's detection


def detection(log: list[dict], run_dir: Path) -> dict:
    """First gate that stopped the run because of the fault (outcome fail; the clean run's own decision points R5 /
    D4 are skipped) and the DFT runs submitted before it."""
    first = next((r for r in log if r["kind"] == "gate" and r.get("outcome") == "fail"
                  and r.get("gate_code") not in NATURAL), None)
    subs = submitted_runs(run_dir)
    total = sum(n for _, n in subs)
    if first is None:
        return {"detected_by": None, "runs_submitted_total": total, "runs_before_detection": total}
    t = first["ts"].replace("+00:00", "")
    before = sum(n for ts, n in subs if ts.replace("+00:00", "")[:23] <= t[:23])
    return {"detected_by": f"{first['gate']} {first.get('gate_code')}", "detected_at_node": first["node"],
            "runs_submitted_total": total, "runs_before_detection": before}


def run_fault(f: dict, cfg_dir: Path, tag: str, out_dir: Path, ablations=(), llm="off", models=None) -> dict:
    from .run import Session
    base_path = cfg_dir / f"{f['system']}.yaml"
    base = cfgmod.load(base_path)
    P = from_config(base)
    thread = f"{tag}_{f['id']}"
    cpath = P.out(out_dir, "configs", f"{f['id']}.yaml")
    cpath.parent.mkdir(parents=True, exist_ok=True)
    cpath.write_text(yaml.safe_dump(patched(base, f["injection"].get("patch"), thread), sort_keys=False,
                                    allow_unicode=True))
    jobs, human, steps = list(f["injection"].get("jobs", [])), list(f["injection"].get("human", [])), []
    n_default = 0
    ungated = "no-gates" in ablations
    with Session(cpath, thread, tag=tag, llm=llm, ablations=ablations, fault_id=f["id"], fresh=True,
                 models=models) as s:
        res = s.start()
        while res["status"] in ("waiting_on_jobs", "interrupted"):
            if res["status"] == "waiting_on_jobs":
                if jobs:
                    ev = jobs.pop(0)
                else:                       # the scripted events are used up: the remaining jobs finish normally
                    ev = "all"
                    n_default += 1
                    if n_default > 5:
                        steps.append("still waiting after 5 default job-end events")
                        break
                ev = {"event": "job_end", "parts": "all"} if ev == "all" else ev
                steps.append(f"jobs: {ev}")
            else:
                code = res["interrupt"][0].get("code")
                if human:
                    ev = human.pop(0)
                else:                       # no scripted answer: the paper's decision where there is one, else stop
                    ev = DEFAULT_HUMAN.get(code, {"option": "stop"})
                steps.append(f"human ({code}): {ev}")
            res = s.resume(ev)
        st = s.graph.get_state(s.cfg).values
        log = s.audit.read()
    failures = [[r["node"], r["code"]] for r in log if r["kind"] == "gate" and r.get("outcome") in ("fail", "fail_ignored")]
    det = detection(log, s.run_dir)
    fixes = [[r["level"], r.get("rule_id"), r["route"]] for r in log if r["kind"] == "fix"]
    same, msg = compare_to_stored(st, P, f["system"]) if res["status"] == "completed" else (None, "—")
    out = {"id": f["id"], "name": f["name"], "class": f["class"], "system": f["system"], "split": f["split"],
           "fault": f["description"], "thread": thread, "final": res["status"], "failures": failures,
           "fixes": fixes, "n_submissions": (st.get("jobs") or {}).get("n_submissions"),
           "resumes": sum(r["kind"] == "resume" for r in log), "steps": steps, "vs_stored": msg,
           "numbers_identical": same, "ablation_flags": sorted(ablations), "llm": llm, **det,
           "rule_fixes": sum(1 for r in log if r["kind"] == "fix" and r["level"] == "rule"),
           "subagent_fixes": sum(1 for r in log if r["kind"] == "fix" and r["level"] == "subagent"),
           "human_interventions": sum(1 for r in log if r["kind"] == "fix" and r["level"] == "human"),
           "subagent_calls": sum(1 for r in log if r["kind"] == "fix" and r.get("subagent") not in (None,)
                                 and not str(r.get("subagent", "")).startswith(("not asked", "ablated", "off")))}
    if ungated:
        detected = [c for n, c in failures]
        out["would_detect"] = detected[0] if detected else None
        out["verdict"] = ("harmless" if res["status"] == "completed" and same else
                          "silent corruption" if res["status"] == "completed" else res["status"])
        out["passed"] = None
    elif any(a.startswith("no-g") or a in ("no-rules", "no-subagents") for a in ablations) or llm != "off":
        out["passed"] = None                  # ablation / model runs are measured, not checked against E2 expectations
        out["verdict"] = ("harmless" if res["status"] == "completed" and same else
                          "silent corruption" if res["status"] == "completed" else res["status"])
    else:
        exp = f["expected"]
        checks = {}
        if "detect" in exp:                  # derived faults: the expected gate must catch it first
            ff = [x for x in failures if x[1] not in NATURAL]
            checks["detected"] = bool(ff) and ff[0] == list(exp["detect"])
        if "failures" in exp:
            checks["failures"] = failures == exp["failures"]
        if "fixes" in exp:
            checks["fixes"] = fixes == exp["fixes"]
        if "final" in exp:
            checks["final"] = res["status"] == exp["final"]
        if "n_submissions" in exp:
            checks["n_submissions"] = out["n_submissions"] == exp["n_submissions"]
        if exp.get("baseline"):
            checks["numbers"] = bool(same)
        out["checks"], out["passed"] = checks, all(checks.values())
    return out


def report_md(results: list[dict], tag: str, frozen) -> str:
    ungated = any("no-gates" in r["ablation_flags"] for r in results)
    L = [f"# Fault injection — tag {tag}" + (" (ungated: --no-gates)" if ungated else ""), "",
         f"eval inputs frozen: {frozen}", ""]
    if ungated:
        L += [f"{sum(r['verdict'] == 'silent corruption' for r in results)} silent corruption, "
              f"{sum(r['verdict'] == 'harmless' for r in results)} harmless, "
              f"{sum(r['verdict'] in ('crashed', 'stopped') for r in results)} crashed/stopped, of {len(results)}.", "",
              "| id | fault | gate that would have caught it | final | numbers vs stored fit | verdict |",
              "|---|---|---|---|---|---|"]
        for r in results:
            L.append(f"| {r['id']} {r['name']} | {r['fault']} | {r['would_detect'] or '—'} | {r['final']} "
                     f"| {r['vs_stored']} | {r['verdict']} |")
    else:
        L += [f"{sum(bool(r['passed']) for r in results)}/{sum(r['passed'] is not None for r in results)} faults handled as expected.", "",
              "| id | fault | gate failure(s) | handled by → next | resumes | final | numbers vs stored fit | ok |",
              "|---|---|---|---|---|---|---|---|"]
        for r in results:
            fl = ", ".join(f"{n} {c}" for n, c in r["failures"]) or "—"
            fx = ", ".join(f"{t}{' ' + rid if rid else ''} → {nx}" for t, rid, nx in r["fixes"]) or "—"
            ok = ("— " + str(r.get("verdict", "")) if r["passed"] is None else "✓" if r["passed"]
                  else "✗ " + str([k for k, v in r["checks"].items() if not v]))
            L.append(f"| {r['id']} {r['name']} | {r['fault']} | {fl} | {fx} | {r['resumes']} "
                     f"| {r['final']} (submissions {r['n_submissions']}) | {r['vs_stored']} | {ok} |")
    L += ["", "Full trails: `test_runs/<tag>_<id>/audit.jsonl`; patched configs: `test_runs/<tag>/configs/`."]
    return "\n".join(L) + "\n"


def run_all(faults_path, cfg_dir=None, tag="E2", only=None, ablations=(), llm="off", system=None, models=None):
    faults_path = Path(faults_path)
    frozen, probs = freeze_eval.verify(faults_path.parent)
    if frozen is False:
        raise SystemExit("eval inputs changed since the freeze — refusing:\n  " + "\n  ".join(probs))
    cfg_dir = Path(cfg_dir or AGENT_ROOT / "configs")
    faults = [f for f in load_faults(faults_path)
              if (not only or f["id"] in only or f["name"] in only) and (not system or f["system"] == system)]
    P = from_config(cfgmod.load(cfg_dir / f"{faults[0]['system']}.yaml"))
    out_dir = P.out(P.agent_root, "test_runs", tag)
    out_dir.mkdir(parents=True, exist_ok=True)
    part = out_dir / "results.jsonl"                   # one line per finished fault: a crash or a restart resumes
    results = [json.loads(x) for x in part.read_text().splitlines()] if part.is_file() else []
    have = {r["id"] for r in results}
    for f in faults:
        if f["id"] in have:
            continue
        r = run_fault(f, cfg_dir, tag, out_dir, ablations, llm, models)
        results.append(r)
        with open(part, "a") as fh:
            fh.write(json.dumps(r, default=str, ensure_ascii=False) + "\n")
    order = {f["id"]: i for i, f in enumerate(faults)}
    results = sorted((r for r in results if r["id"] in order), key=lambda r: order[r["id"]])
    fz = {None: "no (eval/FROZEN.sha256 missing)", True: "yes, unchanged"}[frozen]
    P.out(out_dir, "inject_report.json").write_text(json.dumps({"tag": tag, "frozen": fz, "results": results},
                                                               indent=1, default=str, ensure_ascii=False))
    P.out(out_dir, "inject_report.md").write_text(report_md(results, tag, fz))
    return results, out_dir


def rescore(tag: str, faults_path) -> list[dict]:
    """Recompute detection and the E2 checks of a finished tag from its saved audit logs (no rerun)."""
    fby = {f["id"]: f for f in load_faults(faults_path)}
    out_dir = AGENT_ROOT / "test_runs" / tag
    res = [json.loads(x) for x in (out_dir / "results.jsonl").read_text().splitlines()]
    for r in res:
        rd = AGENT_ROOT / "test_runs" / r["thread"]
        log = [json.loads(x) for x in (rd / "audit.jsonl").read_text().splitlines()]
        r.update(detection(log, rd))
        exp = fby[r["id"]]["expected"]
        if r.get("passed") is not None and "detect" in exp:
            ff = [x for x in r["failures"] if x[1] not in NATURAL]
            r["checks"]["detected"] = bool(ff) and ff[0] == list(exp["detect"])
            r["passed"] = all(r["checks"].values())
    (out_dir / "results.jsonl").write_text("".join(json.dumps(r, default=str, ensure_ascii=False) + "\n" for r in res))
    from . import freeze_eval
    ok, _ = freeze_eval.verify(Path(faults_path).parent)
    fz = {None: "no (eval/FROZEN.sha256 missing)", True: "yes, unchanged", False: "CHANGED"}[ok]
    (out_dir / "inject_report.json").write_text(json.dumps({"tag": tag, "frozen": fz, "results": res}, indent=1,
                                                           default=str, ensure_ascii=False))
    (out_dir / "inject_report.md").write_text(report_md(res, tag, fz))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--faults", default=str(AGENT_ROOT / "eval" / "faults.yaml"))
    ap.add_argument("--configs", default=None, help="folder with <system>.yaml (default IRIS_AGENT/configs)")
    ap.add_argument("--tag", default="E2")
    ap.add_argument("--llm", default="off", help="'off' or a model name from the models file")
    ap.add_argument("--models", default=None, help="models file (default eval/models.yaml)")
    ap.add_argument("--only", default=None, help="comma list of fault ids or names")
    ap.add_argument("--rescore", action="store_true", help="recompute detection / checks of --tag from its logs")
    ap.add_argument("--system", default=None)
    ap.add_argument("--ablate", default="")
    ap.add_argument("--no-gates", action="store_true")
    a = ap.parse_args(argv)
    abl = [x for x in a.ablate.split(",") if x] + (["no-gates"] if a.no_gates else [])
    if a.rescore:
        res = rescore(a.tag, a.faults)
        print(f"{a.tag}: {sum(bool(r['passed']) for r in res)}/{sum(r['passed'] is not None for r in res)} as expected")
        return 0
    results, out = run_all(a.faults, a.configs, a.tag, set(a.only.split(",")) if a.only else None,
                           abl, a.llm, a.system, a.models)
    print((out / "inject_report.md").read_text())
    if "no-gates" in abl:
        return 0
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
