from pathlib import Path

from iris_agent.audit import AuditLog
from iris_agent.gates import SKIP, TESTS, run_gate
from iris_agent.recover import RecoveryTable, make_recover

REC = Path(__file__).resolve().parents[1] / "recovery.yaml"


def test_skeleton_skips_and_replay_checks():
    st = {"config": {"run": {"mode": "skeleton"}, "expected": {"parent_sg": 221, "child_sg": 62}}}
    g = run_gate("G1", st)
    assert g["ok"] and all(t["status"] == "skipped" for t in g["tests"])
    st["config"]["run"]["mode"] = "replay"
    g = run_gate("G1", st)                       # empty decomposition must fail, not pass
    assert not g["ok"] and g["code"] == "NOT_SUBGROUP"


def test_skip_never_passes_outside_skeleton(monkeypatch):
    monkeypatch.setitem(TESTS, "G3", [("none_queued_or_running", lambda s: SKIP)])
    g = run_gate("G3", {"config": {"run": {"mode": "replay"}}})
    assert not g["ok"] and g["code"] == "NOT_IMPLEMENTED"


def test_crashing_test_fails(monkeypatch):
    def boom(s):
        raise RuntimeError("x")
    monkeypatch.setitem(TESTS, "G3", [("none_queued_or_running", boom)])
    g = run_gate("G3", {"config": {"run": {"mode": "replay"}}})
    assert not g["ok"] and g["code"] == "TEST_ERROR"


def test_every_gate_has_tests():
    assert {g for g in TESTS if "_" not in g} == {f"G{i}" for i in range(7)} and set(TESTS) - {f"G{i}" for i in range(7)} == {"G5_surface", "G5_meier_QP", "G2_grid6", "G4_grid6", "G5_landau6d", "G2_path", "G4_path", "G5_path", "G2_plane2", "G5_plane2"}
    assert all(TESTS[g] for g in TESTS)


def test_recovery_table_seeded():
    t = RecoveryTable(REC)
    for node, code in [("f4", "WALLTIME"), ("f4", "NELM"), ("f2", "TRANSLATION"), ("f1", "NO_BASIS"),
                       ("f0", "SCHEMA"), ("f5", "THIN_GRID"), ("f2", "SINGLE_MODE_SG")]:
        assert t.lookup(node, code), (node, code)
    assert t.lookup("f4", "NELM")["fix"]["incar"] == {"AMIX": 0.2, "BMIX": 0.0001, "NELM": 300}
    assert all(any(o["id"] == "stop" for o in t.menu(n)) for n in [f"f{i}" for i in range(7)])


def _state(node, code, **extra):
    return {"last_node": node, "gate": {"ok": False, "code": code, "detail": ""},
            "config": {"retry": {"max_per_node": 3}, "llm": {"enabled": False}},
            "attempts": {}, "overrides": {}, "history": [], **extra}


def _recover(tmp_path, subagent=lambda *a: {"status": "off"}):
    return make_recover(RecoveryTable(REC), AuditLog(tmp_path / "a.jsonl", "t"), subagent)


def test_rule_fix_applied_and_routed(tmp_path):
    out = _recover(tmp_path)(_state("f4", "NELM"))
    assert out["route"] == "f3" and out["overrides"]["f3"]["incar"]["NELM"] == 300
    assert out["overrides"]["f3"]["resubmit_failed"] is True
    assert out["history"][-1]["level"] == "rule" and out["attempts"]["f4"] == 1


def test_goto_from_g5_to_f2(tmp_path):
    out = _recover(tmp_path)(_state("f5", "THIN_GRID"))
    assert out["route"] == "f2" and out["overrides"]["f2"]["densify"] == 2


def test_ladder_steps_then_escalates(tmp_path):
    rec, st, seen = _recover(tmp_path, subagent=lambda *a: {"id": "stop", "reason": "ladder done"}), \
        _state("f1", "NO_BASIS"), []
    for _ in range(4):
        out = rec(st)
        seen.append(out["overrides"].get("f1", {}).get("basis_dmax_A"))
        st = {**st, **out, "attempts": {}}            # ignore budget here: test the ladder alone
    assert seen[:3] == [1.0, 1.5, 2.0]
    assert out["history"][-1]["level"] == "subagent" and out["route"] == "END"


def test_subagent_answer_outside_menu_is_ignored(tmp_path):
    from langgraph.errors import GraphInterrupt
    rec = _recover(tmp_path, subagent=lambda *a: {"id": "delete_everything", "reason": "?"})
    try:
        rec(_state("f2", "R3_FAIL"))
    except (GraphInterrupt, RuntimeError):
        pass                                  # escalated to human (interrupt outside a graph)
    else:
        raise AssertionError("an invalid sub-agent answer must not be applied")


def test_subagent_valid_option(tmp_path):
    out = _recover(tmp_path, subagent=lambda *a: {"id": "anchor_only", "reason": "margin 0.078"})(
        _state("f2", "R5_BORDERLINE"))
    assert out["overrides"]["f2"]["r5_decision"] == "anchor_only" and out["route"] == "f2"
    assert out["history"][-1]["reason"] == "margin 0.078"


def test_every_menu_option_changes_something_a_node_reads():
    """An option whose patch no node reads would be a no-op offered to the sub-agent (S5.2)."""
    import re
    src = "\n".join(p.read_text() for p in (Path(__file__).resolve().parents[1] / "iris_agent" / "nodes").glob("*.py"))
    t = RecoveryTable(REC)
    dead = []
    for node, opts in t.options.items():
        for o in opts:
            for k in o["patch"]:
                if k in ("goto", "abort"):
                    continue
                pat = re.compile(r"""(?:\.get\(|\[)["']%s["']""" % re.escape(k))
                if not any(pat.search(line) for line in src.splitlines() if "over" in line):
                    dead.append((node, o["id"], k))
    assert dead == []


def test_stop_only_menu_skips_the_subagent(tmp_path):
    called = []
    rec = _recover(tmp_path, subagent=lambda *a: called.append(a) or {"id": "stop"})
    try:
        rec(_state("f3", "UNMATCHED"))
    except Exception:
        pass                                   # interrupt() outside a graph: the human is asked
    assert called == []


def test_g4_missing_frames_needs_human_authorisation():
    """flag_and_continue drops frames; G4 refuses the smaller grid unless policy.fit.allow_missing_frames is set."""
    from iris_agent.gates import g4_missing_frames_authorized
    st = {"config": {"policy": {"fit": {}}}, "grid": {"n_frames": 545},
          "energies": {"n": 530, "flagged": [{"id": k, "code": "WALLTIME", "accepted": True, "reason": "job part 3 failed:WALLTIME"} for k in range(15)]}}
    r = g4_missing_frames_authorized(st)
    assert r and r[0] == "MISSING_FRAMES" and "15 of 545" in r[1]
    st["config"]["policy"]["fit"]["allow_missing_frames"] = True
    assert g4_missing_frames_authorized(st) is None
    st["config"]["policy"]["fit"]["allow_missing_frames"] = False
    st["energies"]["flagged"] = [{"id": 1, "code": "WALLTIME", "accepted": False, "reason": "x"}]   # not accepted: G4's own code applies
    assert g4_missing_frames_authorized(st) is None
    st["energies"]["flagged"] = []
    assert g4_missing_frames_authorized(st) is None
    # SCF-limited frames whose energy is kept (policy qc.scf_limited, BiFeO3) are not missing frames
    st["energies"]["flagged"] = [{"id": 7, "code": "SCF_LIMITED", "accepted": True, "energy_kept": True, "reason": "gradients dropped"}]
    assert g4_missing_frames_authorized(st) is None
    st["energies"]["flagged"] = [{"id": 7, "code": "WALLTIME", "accepted": True}]
    st["energies"]["eV_per_cell"] = {"7": -1.0}      # an energy in the fit is not a dropped frame either
    assert g4_missing_frames_authorized(st) is None


def test_g5_missing_frames_counts_unaccepted_flags_too():
    """With G4 ablated a failed frame is flagged but never accepted; G5 must still refuse the smaller fit."""
    from iris_agent.gates import g5_missing_frames, g4_missing_frames_authorized
    st = {"config": {"policy": {"fit": {}}}, "grid": {"n_frames": 545},
          "energies": {"n": 540, "eV_per_cell": {}, "flagged": [{"id": k, "code": "WALLTIME", "accepted": False, "reason": "part 3 WALLTIME"} for k in range(5)]}}
    assert g4_missing_frames_authorized(st) is None            # G4 reports WALLTIME itself through converged_or_flagged
    r = g5_missing_frames(st)
    assert r and r[0] == "MISSING_FRAMES" and "5 of 545" in r[1]
    st["config"]["policy"]["fit"]["allow_missing_frames"] = True
    assert g5_missing_frames(st) is None


def test_g2_r5_decision_applied():
    from iris_agent.gates import g2_r5_decision_applied
    ok = {"overrides": {"f2": {"r5_decision": "exclude"}}, "selection": {"code": "OK", "r5_decision": "exclude", "borderline": ["GM2-", "K1"], "active": ["K3"], "r5_anchors": []},
          "grid": {"built": True, "active": ["K3"]}}
    assert g2_r5_decision_applied(ok) is None
    stale = {**ok, "selection": {**ok["selection"], "r5_decision": None, "active": ["K3", "GM2-"]}}
    assert g2_r5_decision_applied(stale)[0] == "R5_NOT_APPLIED"
    mism = {**ok, "grid": {"built": True, "active": ["K3", "GM2-"]}}
    assert g2_r5_decision_applied(mism)[0] == "R5_NOT_APPLIED"
    anc = {"overrides": {"f2": {"r5_decision": "anchor_only"}}, "selection": {"code": "OK", "r5_decision": "anchor_only", "borderline": ["GM2-", "K1"], "active": ["K3"], "r5_anchors": ["GM2-"]},
           "grid": {"built": True, "active": ["K3"], "r5": {"anchors": [{"irrep": "GM2-"}]}}}
    assert g2_r5_decision_applied(anc) is None
    assert g2_r5_decision_applied({**anc, "grid": {"built": True, "active": ["K3"], "r5": None}})[0] == "R5_NOT_APPLIED"
    assert g2_r5_decision_applied({"selection": {"code": "OK"}, "grid": {}}) is None      # no decision: nothing to check
    # a recorded answer on a selection with no borderline irreps (a wrong menu choice at another failure) is moot
    moot = {"overrides": {"f2": {"r5_decision": "exclude"}}, "selection": {"code": "OK", "r5_decision": None, "borderline": [], "active": ["M3+", "R4+"]},
            "grid": {"built": True, "active": ["M3+", "R4+"]}}
    assert g2_r5_decision_applied(moot) is None


def test_menu_eligibility_filters_options_by_code():
    """Options carry the error codes they are admissible for; the menu a sub-agent or human sees is filtered by the
    failing code in code. A decoy failure (COVERAGE with a minimum near the edge, PATH_LATTICE, a tolerance failure)
    leaves only stop, so no model is asked; a rule-fixable failure keeps its fix."""
    from iris_agent.recover import RecoveryTable
    t = RecoveryTable(REC)
    ids = lambda node, code: [o["id"] for o in t.menu(node, code)]
    assert ids("f5", "COVERAGE") == ["stop"]
    assert ids("f5", "RESIDUALS") == ["stop"] and ids("f5", "CLOSURE") == ["stop"]
    assert ids("f5", "THIN_GRID") == ["densify", "stop"]
    assert ids("f5", "SECONDARY_COUPLED") == ["accept_secondary_hold", "stop"]
    assert ids("f2", "PATH_LATTICE") == ["stop"]
    assert ids("f2", "SINGLE_MODE_SG") == ["rebuild_fixed_lattice", "stop"]
    assert ids("f2", "R5_BORDERLINE") == ["include_borderline", "exclude_borderline", "anchor_only", "stop"]
    assert ids("f4", "WALLTIME") == ["resubmit", "flag_and_continue", "stop"]
    assert ids("f4", "NELM") == ["robust_mixing", "flag_and_continue", "stop"]
    assert ids("f4", "DFT_INCONSISTENT") == ["stop"]
    assert ids("f4", "SCF_LIMITED") == ["stop"]        # an SCF-limited frame keeps its energy (NELM_AFTER_ROBUST); nothing to drop
    assert ids("f1", "NO_BASIS") == ["widen_basis_search", "stop"]
    assert "stop" in ids("f6", "MISMATCH") and "rerun_analysis" in ids("f6", "MISMATCH")
    # every option except stop names its codes, in both tables
    for fn in ("recovery.yaml", "recovery_live.yaml"):
        tt = RecoveryTable(REC.parent / fn)
        for node, opts in tt.options.items():
            for o in opts:
                assert o["id"] == "stop" or o.get("for"), (fn, node, o["id"])


def test_ineligible_option_is_not_offered_to_the_subagent(tmp_path):
    """On a COVERAGE decoy the sub-agent is not asked (only stop is admissible), even though densify is on f5's table."""
    called = []
    rec = _recover(tmp_path, subagent=lambda *a: called.append(a) or {"id": "densify"})
    try:
        rec(_state("f5", "COVERAGE"))
    except Exception:
        pass                                   # interrupt() outside a graph: the human is asked
    assert called == []
