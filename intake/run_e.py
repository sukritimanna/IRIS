"""Experiment E: plain-language intake (build step 6), replay only.

  python -m intake.run_e --freeze --reason "..."      # after the requests are approved: intake/FROZEN.sha256
  python -m intake.run_e --calls --models claude-sonnet,gpt-sol,gemini-argon,claude-opus --repeats 5   # (Mac: keys)
  python -m intake.run_e --calls --models baseline                      # keyword / template baseline (1 repeat)
  python -m intake.run_e --score                                        # -> results/E/E_calls.csv
  python -m intake.run_e --endtoend                                     # -> results/E/E_endtoend.csv

Model calls refuse to run unless every frozen intake file matches intake/FROZEN.sha256. Keys only from the
environment. Each call: request text (+ attachments) -> schema-constrained draft intent -> code builds config.yaml +
intent.json (results/E/configs/<model>/<request>_r<k>/) -> f0 + G0 on that config (no other node).
End to end: every distinct config with all critical fields right runs the full workflow in replay once; its result is
shared by the calls that produced the same config hash. A config whose system profile differs from the stored
campaign's is not run: replay would re-link the same stored energies, so it is recorded as "would need new DFT
(profile)", like a stop at G3 UNMATCHED.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intake import baseline as BL, build as B, schema as S  # noqa: E402
from intake.library import CONFIG_OF, TRANSITIONS  # noqa: E402

OUT = ROOT / "results" / "E"
FROZEN = ROOT / "intake" / "FROZEN.sha256"
FROZEN_FILES = ["requests.yaml", "make_requests.py", "library.py", "schema.py", "build.py", "baseline.py", "llm_json.py",
                "run_e.py", "system_prompt.txt", "json_schema.json", "BASELINE.sha256", "../iris_agent/gates.py",
                "../iris_agent/nodes/f0_intake.py", "../iris_agent/llm.py", "../eval/models.yaml"]
CRITICAL = ["structures", "transition", "analysis", "strain_policy", "system_profile", "budget"]


BLIND = ROOT / "intake" / "requests_blind.yaml"          # author-written, blind (added later, frozen on its own)
BLIND_FROZEN = ROOT / "intake" / "BLIND.sha256"


def requests() -> list[dict]:
    r = yaml.safe_load((ROOT / "intake" / "requests.yaml").read_text())["requests"]
    if BLIND.is_file():
        r += yaml.safe_load(BLIND.read_text())["requests"]
    return r


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def freeze(reason: str):
    d = ROOT / "intake"
    (d / "system_prompt.txt").write_text(S.system_prompt())
    (d / "json_schema.json").write_text(json.dumps(S.json_schema(), indent=1))
    lines = [f"# frozen {datetime.now(timezone.utc).isoformat(timespec='seconds')}: {reason}"]
    lines += [f"{_sha(d / f)}  {f}" for f in FROZEN_FILES]
    FROZEN.write_text("\n".join(lines) + "\n")
    print(FROZEN.read_text())
    print("FROZEN.sha256", _sha(FROZEN))


def verify() -> list[str]:
    if not FROZEN.is_file():
        return ["intake/ not frozen (python -m intake.run_e --freeze --reason ...)"]
    bad = []
    for line in FROZEN.read_text().splitlines():
        if line and not line.startswith("#"):
            h, f = line.split(None, 1)
            if _sha(ROOT / "intake" / f) != h:
                bad.append(f"changed: {f}")
    if BLIND.is_file():
        if not BLIND_FROZEN.is_file() or BLIND_FROZEN.read_text().split()[-2] != _sha(BLIND):
            bad.append("requests_blind.yaml not frozen / changed (intake/BLIND.sha256)")
    if (ROOT / "intake" / "system_prompt.txt").read_text() != S.system_prompt():
        bad.append("system prompt differs from intake/system_prompt.txt")
    return bad


# ---- calls ------------------------------------------------------------------------------------------------------
def one_call(model: str, spec: dict | None, req: dict, k: int, transport=None) -> dict:
    t0 = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if model == "baseline":
        draft = BL.draft(req["text"], req.get("attachments"))
        meta = {"valid": True, "error": None, "model_version": "keyword-baseline"}
    else:
        from intake.llm_json import llm_json
        r = llm_json({**spec, "name": model}, S.system_prompt(), S.user_prompt(req["text"], req.get("attachments") or []),
                     transport=transport)
        draft = r.pop("obj") or {}
        meta = r
    res = B.resolve(draft, req.get("attachments"))
    thread = f"E_{model}_{req['id']}_r{k}"
    cpath, h = B.write(res, req["text"], thread, OUT / "configs" / model / f"{req['id']}_r{k}")
    g0 = g0_of(cpath)
    return {"ts": t0, "model": model, "repeat": k, "request": req["id"], "draft": draft, "resolved": res,
            "config": str(cpath.relative_to(ROOT)) if cpath.is_relative_to(ROOT) else str(cpath), "config_hash": h, "g0": g0, **{f"llm_{a}": b for a, b in meta.items()
                                                                                    if a not in ("raw_text",)},
            "raw_text": meta.get("raw_text")}


def g0_of(cpath: Path) -> dict:
    from iris_agent.gates import run_gate
    from iris_agent.nodes.f0_intake import f0_intake
    st = {"config_path": str(cpath), "thread_id": "E_g0_check", "overrides": {}, "run_meta": {}}
    out = f0_intake(st)
    g = run_gate("G0", {**st, **out})
    return {"ok": g["ok"], "code": g["code"], "detail": g["detail"][:300],
            "failing": [t["code"] for t in g["tests"] if t["status"] == "fail"]}


def calls(models: list[str], repeats: int, workers: int = 4):
    from concurrent.futures import ThreadPoolExecutor
    if models != ["baseline"]:
        bad = verify()
        if bad:
            raise SystemExit("refusing model calls: " + "; ".join(bad))
    from iris_agent.llm import load_models
    mods = load_models(ROOT / "eval" / "models.yaml")
    OUT.mkdir(parents=True, exist_ok=True)
    jl = OUT / "calls.jsonl"
    done = {(r["model"], r["request"], r["repeat"]) for r in map(json.loads, jl.read_text().splitlines())} if jl.is_file() else set()
    todo = [(m, req, k) for m in models for req in requests() for k in range(1 if m == "baseline" else repeats)
            if (m, req["id"], k) not in done]
    print(f"{len(todo)} calls to make ({len(done)} done)")

    def job(t):
        m, req, k = t
        return one_call(m, None if m == "baseline" else mods[m], req, k)
    with ThreadPoolExecutor(max_workers=1 if models == ["baseline"] else workers) as ex:
        for r in ex.map(job, todo):
            with open(jl, "a") as fh:
                fh.write(json.dumps(r, default=str) + "\n")
            print(r["model"], r["request"], r["repeat"], r["resolved"]["status"], r["g0"]["code"],
                  r.get("llm_error") or "")


# ---- scoring ----------------------------------------------------------------------------------------------------
def field_values(it: dict) -> dict:
    return {"structures": (it.get("system"), it.get("parent_sg"), it.get("child_sg")), "transition": it.get("transition"),
            "analysis": it.get("analysis"), "strain_policy": it.get("strain_policy"),
            "system_profile": it.get("system_profile"), "budget": it.get("budget"),
            "outputs": tuple(sorted(it.get("outputs") or []))}


def score_row(c: dict, req: dict) -> dict:
    res = c["resolved"]
    out = {"model": c["model"], "repeat": c["repeat"], "request": c["request"], "kind": req["kind"], "style": req["style"],
           "valid": c.get("llm_valid", True), "error": c.get("llm_error"), "outcome": res["status"],
           "g0_ok": c["g0"]["ok"], "g0_code": c["g0"]["code"], "config_hash": c["config_hash"],
           "template": res.get("template"), "model_question": res.get("model_question"),
           "clarify_field": res.get("model_clarify_field"), "g0_question": res.get("question"),
           "out_of_scope_reason": res.get("reason")}
    it = res["intent"]
    vals = field_values(it)
    for f, v in vals.items():
        out[f] = json.dumps(v) if isinstance(v, tuple) else v
        out[f"source_{f}"] = (res["sources"].get("system") if f == "structures" else res["sources"].get(f))
    if req["kind"] == "paraphrase":
        ref = field_values(req["reference"])
        acc, dfn = req["acceptable"], req.get("defensible") or {}
        wrong, defensible = [], []

        def ok_field(f):
            v, a = it.get(f), acc[f]
            if v in [x for x in a if x is not None]:
                return True
            if None in a and res["sources"].get(f) == "default":     # unstated, left to the policy default
                return True
            if v in dfn.get(f, []):
                defensible.append(f"{f}={v}")
                return True
            return False
        for f in vals:
            if f == "outputs":     # not critical: the D4 / hat choice matters, the rest is reporting
                key = lambda o: tuple(x for x in o if x in ("d4_secondary_check", "hat_and_brim"))
                ok = (res["status"] != "ok" or key(vals[f] or ()) == key(ref[f]) or not vals[f]
                      or res.get("template") in req.get("accept_configs", []))
            elif res["status"] != "ok":
                ok = False
            elif f == "structures":
                ok = all(ok_field(k) for k in ("system", "parent_sg", "child_sg"))
            else:
                ok = ok_field(f)
            out[f"match_{f}"] = ok
            if not ok and f in CRITICAL:
                wrong.append(f)
        out["same_config_as_reference"] = res.get("template") == req["reference_config"]
        out["accepted_config"] = res.get("template") in req.get("accept_configs", [req["reference_config"]])
        if res["status"] == "ok" and not out["accepted_config"] and not wrong:
            wrong.append("config (D4 / hat choice)")      # every field right, but the outputs select another template
        out["critical_all_right"] = res["status"] == "ok" and not wrong
        out["wrong_critical_fields"] = ";".join(wrong)
        out["wrong_caught_by_g0"] = bool(wrong) and not c["g0"]["ok"]
        out["wrong_passed_g0"] = bool(wrong) and c["g0"]["ok"]
        out["clarification"] = "unnecessary question" if res["status"] == "ambiguous" else (
            "refused a clear request" if res["status"] == "out_of_scope" else "none")
        out["defensible_different"] = ";".join(defensible) or (
            f"config={res.get('template')}" if res.get("template") and res.get("template") != req["reference_config"]
            and res["status"] == "ok" and not wrong else "")
    elif req["kind"] == "underspecified":
        out["clarification"] = "asked" if res["status"] == "ambiguous" else (
            "refused" if res["status"] == "out_of_scope" else "guessed")
        out["critical_all_right"] = None
        out["accepted_config"] = res.get("template") in req.get("accept_configs", [])
        out["defensible_different"] = (res.get("template") in req.get("defensible_guesses", [])) if res["status"] == "ok" else ""
    elif req["kind"] == "new_material":
        a = req["acceptable"]
        fm = lambda x: (x or "").replace(" ", "").lower()
        okf = {"formula": fm(it.get("formula")) == fm(a["formula"][0]), "parent_sg": it.get("parent_sg") in a["parent_sg"],
               "child_sg": it.get("child_sg") in a["child_sg"], "analysis": it.get("analysis") in a["analysis"],
               "system_profile": it.get("system_profile") in a["system_profile"],
               "strain_policy": it.get("strain_policy") in [x for x in a["strain_policy"] if x] or res["sources"].get("strain_policy") == "default"}
        for k, v in okf.items():
            out[f"match_{k}"] = v
        out["borrowed_profile"] = any("borrowed" in c for c in res.get("checks") or [])
        out["clarification"] = {"needs_new_dft": "valid, needs new DFT", "ambiguous": "asked",
                                "out_of_scope": "refused"}.get(res["status"], "accepted with a stored config")
        out["critical_all_right"] = res["status"] == "needs_new_dft" and all(okf.values()) and not res.get("checks")
        out["defensible_different"] = ""
    else:
        out["clarification"] = {"out_of_scope": "refused", "ambiguous": "asked"}.get(res["status"], "accepted")
        out["critical_all_right"] = None
        out["defensible_different"] = ""
    out["correct_outcome"] = (out.get("critical_all_right") is True if req["kind"] in ("paraphrase", "new_material") else
                              (out["clarification"] == "asked" or out.get("accepted_config") is True)
                              if req["kind"] == "underspecified" else out["clarification"] in ("refused", "asked"))
    return out


def score():
    reqs = {r["id"]: r for r in requests()}
    rows = [score_row(c, reqs[c["request"]]) for c in map(json.loads, (OUT / "calls.jsonl").read_text().splitlines())]
    rows.sort(key=lambda r: (r["model"], r["request"], r["repeat"]))
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(OUT / "E_calls.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    summ = []
    for m in sorted({r["model"] for r in rows}):
        rr = [r for r in rows if r["model"] == m]
        par = [r for r in rr if r["kind"] == "paraphrase"]
        und = [r for r in rr if r["kind"] == "underspecified"]
        oos = [r for r in rr if r["kind"] == "out_of_scope"]
        s = {"model": m, "calls": len(rr), "invalid": sum(not r["valid"] for r in rr),
             "paraphrase_all_critical_right": f"{sum(bool(r['critical_all_right']) for r in par)}/{len(par)}",
             **{f"match_{f}": f"{sum(bool(r.get('match_' + f)) for r in par)}/{len(par)}" for f in CRITICAL + ['outputs']},
             "wrong_caught_by_g0": sum(bool(r["wrong_caught_by_g0"]) for r in par),
             "wrong_passed_g0": sum(bool(r["wrong_passed_g0"]) for r in par),
             "unnecessary_questions": sum(r["clarification"] == "unnecessary question" for r in par),
             "underspecified_asked": f"{sum(r['clarification'] == 'asked' for r in und)}/{len(und)}",
             "underspecified_guessed": sum(r["clarification"] == "guessed" for r in und),
             "underspecified_correct": f"{sum(bool(r['correct_outcome']) for r in und)}/{len(und)}",
             "out_of_scope_refused_or_asked": f"{sum(r['clarification'] in ('refused', 'asked') for r in oos)}/{len(oos)}",
             "new_material_correct": f"{sum(bool(r['correct_outcome']) for r in rr if r['kind'] == 'new_material')}/"
                                     f"{sum(r['kind'] == 'new_material' for r in rr)}",
             "new_material_borrowed_profile": sum(bool(r.get('borrowed_profile')) for r in rr if r['kind'] == 'new_material'),
             "blind_correct": f"{sum(bool(r['correct_outcome']) for r in rr if r['style'] == 'author_blind')}/"
                              f"{sum(r['style'] == 'author_blind' for r in rr)}"}
        for st in ("expert", "terse", "non-specialist"):
            p = [r for r in par if r["style"] == st]
            s[f"all_critical_right_{st}"] = f"{sum(bool(r['critical_all_right']) for r in p)}/{len(p)}"
        summ.append(s)
    with open(OUT / "E_summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summ[0]))
        w.writeheader()
        w.writerows(summ)
    for s in summ:
        print(s)
    return rows


# ---- end to end -------------------------------------------------------------------------------------------------
def endtoend():
    from iris_agent.inject import DEFAULT_HUMAN, compare_to_baseline
    from iris_agent.paths import from_config
    from iris_agent.run import Session
    reqs = {r["id"]: r for r in requests()}
    calls_ = [json.loads(x) for x in (OUT / "calls.jsonl").read_text().splitlines()]
    scored = {(r["model"], r["request"], r["repeat"]): r for r in (score_row(c, reqs[c["request"]]) for c in calls_)}
    runs_f = OUT / "endtoend_runs.jsonl"
    runs = {r["config_hash"]: r for r in map(json.loads, runs_f.read_text().splitlines())} if runs_f.is_file() else {}
    rows = []
    for c in calls_:
        s = scored[(c["model"], c["request"], c["repeat"])]
        if not s.get("critical_all_right"):
            continue
        h = c["config_hash"]
        tpl = c["resolved"]["template"]
        if h not in runs:
            cfg = B.build_config(c["resolved"], reqs[c["request"]]["text"], "E2E")   # rebuilt here (calls may come from the Mac)
            stored_profile = Path(B.load_config(tpl)["paths"]["system_json"]).stem
            if c["resolved"]["intent"]["system_profile"] != stored_profile:
                runs[h] = {"config_hash": h, "template": tpl, "thread": None, "final": "would need new DFT",
                           "stop_code": "PROFILE", "numbers_identical": None,
                           "note": f"profile {c['resolved']['intent']['system_profile']} != stored {stored_profile}"}
            else:
                thread = f"E2E_{h}"
                run_cfg = OUT / "endtoend_configs" / f"{h}.yaml"
                run_cfg.parent.mkdir(parents=True, exist_ok=True)
                cfg["thread_id"] = thread
                run_cfg.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=140))
                with Session(run_cfg, thread, tag="E2E", fresh=False) as ses:
                    res = ses.start()
                    n = 0
                    while res["status"] in ("waiting_on_jobs", "interrupted") and n < 20:
                        n += 1
                        if res["status"] == "waiting_on_jobs":
                            res = ses.resume({"event": "job_end", "parts": "all"})
                        else:
                            code = res["interrupt"][0].get("code")
                            res = ses.resume(DEFAULT_HUMAN.get(code, {"option": "stop"}))
                    st = ses.graph.get_state(ses.cfg).values
                    log = ses.audit.read()
                fails = [r for r in log if r["kind"] == "gate" and r.get("outcome") == "fail"
                         and r.get("gate_code") not in ("R5_BORDERLINE", "SECONDARY_COUPLED")]
                same, msg = (compare_to_baseline(st, from_config(cfg), tpl) if res["status"] == "completed"
                             else (None, "—"))
                stop = fails[-1]["gate_code"] if fails and res["status"] != "completed" else ""
                runs[h] = {"config_hash": h, "template": tpl, "thread": thread,
                           "final": "would need new DFT" if stop == "UNMATCHED" else res["status"], "stop_code": stop,
                           "numbers_identical": same, "note": msg}
            with open(runs_f, "a") as fh:
                fh.write(json.dumps(runs[h], default=str) + "\n")
            print(h, runs[h]["final"], runs[h]["stop_code"], runs[h]["numbers_identical"])
        r = runs[h]
        rows.append({"request": c["request"], "model": c["model"], "repeat": c["repeat"], "config_hash": h,
                     "template": tpl, "final_status": r["final"], "numbers_identical": r["numbers_identical"],
                     "stop_code": r["stop_code"], "thread": r["thread"], "note": r["note"]})
    with open(OUT / "E_endtoend.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["request"])
        w.writeheader()
        w.writerows(rows)
    print(OUT / "E_endtoend.csv", len(rows), "rows,", len({r["config_hash"] for r in rows}), "distinct configs")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--reason", default=None)
    ap.add_argument("--calls", action="store_true")
    ap.add_argument("--models", default="baseline")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--endtoend", action="store_true")
    ap.add_argument("--out", default=None, help="output folder (default results/E; the v2 rerun uses results/E/v2)")
    a = ap.parse_args(argv)
    global OUT
    if a.out:
        OUT = (ROOT / a.out) if not Path(a.out).is_absolute() else Path(a.out)
    if a.freeze:
        if not a.reason:
            raise SystemExit("--freeze needs --reason")
        freeze(a.reason)
    if a.calls:
        calls(a.models.split(","), a.repeats, a.workers)
    if a.score:
        score()
    if a.endtoend:
        endtoend()


_ = (CONFIG_OF, TRANSITIONS)

if __name__ == "__main__":
    main()
