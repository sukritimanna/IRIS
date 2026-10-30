"""Runbook interface: run options, audit fields, ablations, freeze_eval, check_env, resume_test."""
import json
import shutil

import pytest

from iris_agent import freeze_eval
from iris_agent.audit import CONTEXT_FIELDS
from iris_agent.run import Session

from .test_regression_cssni3 import CFG, _available


def test_tag_names_thread_and_audit_carries_run_context(make_config, sandbox):
    cfg = make_config("x")
    with Session(cfg, tag="E1", fault_id="F000") as s:
        assert s.thread_id == "E1_cssni3"
        res = s.start()
        log = s.audit.read()
    assert res["status"] == "completed"
    for r in log:
        assert set(CONTEXT_FIELDS) <= set(r) and r["tag"] == "E1" and r["fault_id"] == "F000"
        assert r["run_id"].startswith("E1_cssni3-") and r["system"] == "cssni3"
    gates = [r for r in log if r["kind"] == "gate"]
    assert all({"gate_code", "outcome", "attempts"} <= set(r) for r in gates)
    assert all("wall_time_s" in r for r in log if r["kind"] == "node" and r.get("event") == "done")
    end = log[-1]
    assert end["kind"] == "end" and end["status"] == "completed" and "g6_table" in end


def test_llm_names_come_from_the_models_file(make_config):
    with pytest.raises(SystemExit):                       # not in eval/models.yaml
        Session(make_config("y"), llm="gpt-unknown")
    s = Session(make_config("y"), llm="claude-sonnet")    # step 5: a pinned model is accepted
    assert s.meta["provider"] == "anthropic" and s.meta["llm_spec"]["model"] == "claude-sonnet-5-5"
    with pytest.raises(SystemExit):
        Session(make_config("y"), ablations=["no-thinking"])


def test_no_gates_logs_failures_but_continues(make_config):
    cfg = make_config("ng", paths__child_cif="demo/cssni3/structures/NOPE.cif")
    with Session(cfg, ablations=["no-gates"]) as s:
        res = s.start()
        log = s.audit.read()
    assert res["status"] == "completed"                     # skeleton stubs downstream
    g0 = next(r for r in log if r["kind"] == "gate" and r["node"] == "f0")
    assert g0["outcome"] == "fail_ignored" and g0["gate_code"] == "CIF_MISSING"


def test_no_gates_crash_ends_run(make_config):
    cfg = make_config("ngc", run__mode="replay")            # stored ISODISTORT files absent -> f1 crashes
    with Session(cfg, ablations=["no-gates"]) as s:
        res = s.start()
    assert res["status"] == "crashed" and res["last_node"] == "f1"


def test_no_rules_skips_the_rule_table(tmp_path):
    from iris_agent.audit import AuditLog
    from iris_agent.recover import RecoveryTable, make_recover
    from .conftest import AGENT
    rec = make_recover(RecoveryTable(AGENT / "recovery.yaml"), AuditLog(tmp_path / "a.jsonl", "t"),
                       lambda *a: {"id": "robust_mixing", "reason": "x"})   # the admissible fix for NELM
    st = {"last_node": "f4", "gate": {"ok": False, "code": "NELM"}, "attempts": {}, "overrides": {},
          "history": [], "config": {"retry": {"max_per_node": 3}, "llm": {"enabled": True}},
          "run_meta": {"ablation_flags": ["no-rules"]}}
    out = rec(st)
    assert out["history"][-1]["level"] == "subagent"        # the rule was not used


def test_freeze_eval(tmp_path, monkeypatch):
    from .conftest import AGENT
    d = AGENT / "test_runs" / "pytest_freeze"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "faults.yaml").write_text("faults: []\n")
    assert freeze_eval.verify(d) == (None, [])
    freeze_eval.freeze(d)
    assert freeze_eval.verify(d) == (True, [])
    (d / "faults.yaml").write_text("faults: [x]\n")
    ok, probs = freeze_eval.verify(d)
    assert ok is False and probs == ["changed: faults.yaml"]
    with pytest.raises(SystemExit):
        freeze_eval.freeze(d)                                # refuses without --refreeze
    freeze_eval.freeze(d, refreeze=True, reason="test: intended change")
    assert freeze_eval.verify(d)[0] is True
    with pytest.raises(SystemExit):
        freeze_eval.freeze(tmp_path)                         # never writes outside IRIS_AGENT
    shutil.rmtree(d)


def test_check_env_reports_sandbox(make_config, sandbox, capsys):
    from iris_agent import check_env
    make_config("cssni3")
    repo, agent = sandbox
    r = check_env.check(agent / "configs")
    c = r["configs"]["cssni3"]
    assert c["schema_errors"] == [] and c["replay"]["complete"] is False   # sandbox has no grid data
    assert set(r["keys"]) == set(check_env.KEYS) and all(v in ("set", "not set") for v in r["keys"].values())


@pytest.mark.skipif(not _available(), reason="CsSnI3 reference data not present")
def test_resume_after_kill_E7():
    from iris_agent.resume_test import run
    out = run(str(CFG), "f3", "pytest_E7")
    assert out["passed"], json.dumps(out["checks"])
