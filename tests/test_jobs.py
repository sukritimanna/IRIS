"""Job book, job-end events, and the f3 wait loop inside a real LangGraph with a SQLite checkpoint."""
import json
import sqlite3

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from iris_agent.engines import jobs as J
from iris_agent.gates import run_gate
from iris_agent.jobend import event


def test_plan_parts_matches_campaign_layout():
    parts = J.plan_parts(list(range(962)), 40)
    assert len(parts) == 25 and len(parts["24"]["frames"]) == 2
    assert all(v["status"] == "queued" for v in parts.values())


def test_events():
    book = {"parts": J.plan_parts(list(range(100)), 40)}          # 3 parts
    b, ok, _ = J.apply_event(book, {"event": "job_end", "parts": [0]})
    assert ok and J.pending(b) == [1, 2] and J.pending(book) == [0, 1, 2]   # input not mutated
    b, ok, _ = J.apply_event(b, {"event": "job_end", "parts": [0]})         # repeated end: harmless
    assert ok and J.pending(b) == [1, 2]
    b, ok, _ = J.apply_event(b, {"event": "job_end", "parts": [1], "failed": {"2": "walltime"}})
    assert ok and J.pending(b) == [] and b["parts"]["2"]["status"] == "failed:WALLTIME"
    for bad in ({"option": "stop"}, "go", {"event": "job_end", "parts": [7]},
                {"event": "job_end", "failed": {"1": "BOGUS"}}):
        _, ok, _ = J.apply_event(book, bad)
        assert not ok
    b, ok, _ = J.apply_event(book, {"event": "cancel"})
    assert ok and J.summary(b) == {"cancelled": 3}


def test_jobend_cli_event_builder():
    assert event() == {"event": "job_end", "parts": "all", "failed": {}}
    assert event("0-2,5")["parts"] == [0, 1, 2, 5]
    assert event(None, "3:walltime") == {"event": "job_end", "parts": [3], "failed": {"3": "WALLTIME"}}
    assert event(cancel=True) == {"event": "cancel"}


def _graph(tmp_path, calls):
    """One node that submits once (record on disk) and waits, like f3."""
    rec = tmp_path / "submission.json"

    def runner(state):
        if not rec.exists():
            calls.append("submit")
            rec.write_text(json.dumps({"parts": J.plan_parts(list(range(10)), 4)}))
        book = J.wait(json.loads(rec.read_text()), interrupt, {"node": "f3"})
        return {"result": J.summary(book), "events": len(book["events"])}

    g = StateGraph(dict)
    g.add_node("f3", runner)
    g.add_edge(START, "f3")
    g.add_edge("f3", END)
    return g


def test_wait_resume_across_sessions(tmp_path):
    calls, db, cfg = [], tmp_path / "cp.sqlite", {"configurable": {"thread_id": "t"}}

    def session():
        return _graph(tmp_path, calls).compile(checkpointer=SqliteSaver(sqlite3.connect(str(db), check_same_thread=False)))

    out = session().invoke({}, cfg)
    assert out["__interrupt__"][0].value["parts_pending"] == [0, 1, 2]
    out = session().invoke(Command(resume={"event": "job_end", "parts": [0]}), cfg)     # new connection
    assert out["__interrupt__"][0].value["parts_pending"] == [1, 2]
    out = session().invoke(Command(resume={"option": "stop"}), cfg)                     # not a job event
    assert out["__interrupt__"][0].value["parts_pending"] == [1, 2]
    out = session().invoke(Command(resume={"event": "job_end", "parts": "all", "failed": {"2": "NELM"}}), cfg)
    assert "__interrupt__" not in out
    assert out["result"] == {"finished": 2, "failed:NELM": 1} and out["events"] == 3
    assert calls == ["submit"]                                   # submitted exactly once


def test_g3_g4_codes_for_cancel_and_failures():
    st = {"config": {"run": {"mode": "replay"}, "policy": {}}}
    j = {"queued": 0, "running": 0, "cancelled": 2, "unmatched": [], "n_matched": 5, "n_frames": 5}
    assert run_gate("G3", {**st, "jobs": j})["code"] == "JOBS_CANCELLED"
    assert run_gate("G3", {**st, "jobs": {**j, "cancelled": 0, "queued": 1}})["code"] == "JOBS_PENDING"
    e = {"n": 4, "flagged": [{"id": 9, "code": "WALLTIME", "accepted": False}], "E0_eV": -1.0,
         "range_meV_per_fu": 20.0, "sanity": {"min_range_meV": 1, "max_range_meV": 1e4}, "stored_input_sets": {}}
    g = run_gate("G4", {**st, "energies": e, "grid": {"n_frames": 5}})
    assert g["code"] == "WALLTIME"
    e["flagged"][0]["accepted"] = True                           # flag_and_continue: a smaller grid needs the human
    assert run_gate("G4", {**st, "energies": e, "grid": {"n_frames": 5}})["code"] == "MISSING_FRAMES"
    st2 = {**st, "config": {"run": {"mode": "replay"}, "policy": {"fit": {"allow_missing_frames": True}}}}
    assert run_gate("G4", {**st2, "energies": e, "grid": {"n_frames": 5}})["ok"]


@pytest.mark.parametrize("payload", [None, {"event": "job_end", "parts": []}])
def test_empty_or_missing_events_keep_waiting(payload):
    book = {"parts": J.plan_parts([1, 2], 1)}
    b, _, _ = J.apply_event(book, payload)
    assert J.pending(b) == [0, 1]
