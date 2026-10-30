"""End-to-end graph behaviour in skeleton mode: order of nodes and gates, audit log, SQLite
checkpoint, human interrupt + resume from a fresh session, write location, no secrets."""
import os
import sqlite3

from iris_agent.run import Session
from iris_agent.state import NODES


def _files(root):
    return {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def test_skeleton_run_completes(make_config, sandbox):
    repo, agent = sandbox
    cfg = make_config("cssni3_221_62")
    before = {p: m for p, m in _files(repo).items() if not p.is_relative_to(agent)}
    with Session(cfg) as s:
        res = s.start()
        assert res["status"] == "completed" and res["last_node"] == "f6"
        log = s.audit.read()
    gates = [(r["node"], r["code"]) for r in log if r["kind"] == "gate"]
    assert gates == [(n, "OK") for n in NODES]
    assert [r["node"] for r in log if r["kind"] == "node" and r["event"] == "start"] == NODES
    assert log[0]["kind"] == "run" and log[-1]["kind"] == "end"
    g0 = next(r for r in log if r["kind"] == "gate" and r["node"] == "f0")
    assert all(t["status"] == "pass" for t in g0["tests"])          # G0 is real, nothing skipped
    run_dir = agent / "test_runs" / "cssni3_221_62"
    assert (run_dir / "iris.sqlite").is_file() and (run_dir / "audit.jsonl").is_file()
    after = {p: m for p, m in _files(repo).items() if not p.is_relative_to(agent)}
    assert before == after                                          # nothing outside IRIS_AGENT


def test_missing_cif_interrupts_then_human_fix_resumes(make_config, sandbox):
    repo, agent = sandbox
    cfg = make_config("fault_cif", paths__child_cif="demo/cssni3/structures/NOPE.cif")
    with Session(cfg) as s:
        res = s.start()
    assert res["status"] == "interrupted"
    intr = res["interrupt"][0]
    assert intr["node"] == "f0" and intr["code"] == "CIF_MISSING"
    assert intr["why_human"]["subagent"].startswith(("off", "not asked"))   # f0 menu: stop only (S5.2)
    # resume in a NEW session (as after a restart): state comes back from SQLite
    fix = {"fix": {"config_patch": {"paths": {"child_cif": "demo/cssni3/structures/orthorhombic_mp-568570_sg62.cif"}}}}
    with Session(cfg) as s2:
        assert s2.status()["next"] == ["recover"]
        res2 = s2.resume(fix)
        log = s2.audit.read()
    assert res2["status"] == "completed"
    kinds = [r["kind"] for r in log]
    assert kinds.count("interrupt") == 1 and kinds.count("resume") == 1
    fixrec = next(r for r in log if r["kind"] == "fix")
    assert fixrec["level"] == "human" and fixrec["route"] == "f0"


def test_wrong_space_group_and_checksum(make_config):
    cfg = make_config("fault_sg", expected__child_sg=63)
    with Session(cfg) as s:
        res = s.start()
    assert res["interrupt"][0]["code"] == "CIF_SG"
    cfg = make_config("fault_sha", expected__child_sha256="0" * 64)
    with Session(cfg) as s:
        res = s.start()
    assert res["interrupt"][0]["code"] == "CIF_CHANGED"


def test_replay_without_stored_inputs_stops_at_f1(make_config):
    # the sandbox repo has only the CIFs: f1 cannot find the stored ISODISTORT responses
    cfg = make_config("replay_guard", run__mode="replay")
    with Session(cfg) as s:
        res = s.start()
        log = s.audit.read()
    assert res["status"] == "interrupted"
    assert res["interrupt"][0]["node"] == "f1" and res["interrupt"][0]["code"] == "NODE_ERROR"
    assert any(r["kind"] == "node" and r.get("event") == "error" for r in log)


def test_human_stop_ends_run(make_config):
    cfg = make_config("stop", run__budget_runs=0)
    with Session(cfg) as s:
        assert s.start()["interrupt"][0]["code"] == "SCHEMA"
        res = s.resume({"option": "stop"})
    assert res["status"] == "stopped" and res["last_node"] == "f0"


def test_api_key_never_written(make_config, sandbox, monkeypatch):
    repo, agent = sandbox
    fake = "sk-ant-TEST-0123456789-should-never-be-written"
    monkeypatch.setenv("ANTHROPIC_API_KEY", fake)
    cfg = make_config("secret")
    with Session(cfg) as s:
        s.start()
    for p in (agent / "test_runs" / "secret").rglob("*"):
        assert fake.encode() not in p.read_bytes(), p
    con = sqlite3.connect(agent / "test_runs" / "secret" / "iris.sqlite")
    blob = b"".join(bytes(str(r), "utf8") for r in con.execute("select * from checkpoints"))
    assert fake.encode() not in blob
    assert os.environ["ANTHROPIC_API_KEY"] == fake
