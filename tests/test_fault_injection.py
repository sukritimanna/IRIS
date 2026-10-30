"""Fault injection from eval/faults.yaml: guards (always) and the full gated run E2 (needs the data)."""
import pytest
import yaml

from iris_agent import config as cfgmod
from iris_agent.inject import load_faults, patched, run_all

from .conftest import AGENT
from .test_regression_cssni3 import CFG, _available

FAULTS = AGENT / "eval" / "faults.yaml"


def test_faults_file_is_well_formed():
    fs = load_faults(FAULTS)
    assert len(fs) >= 50 and len({f["id"] for f in fs}) == len(fs)
    for f in fs:
        assert {"id", "name", "class", "system", "split", "description", "injection", "expected"} <= set(f)
        assert f["split"] in ("seed", "held-out")
        assert (AGENT / "configs" / f"{f['system']}.yaml").is_file()


def test_patch_helper_and_fault_guards(make_config):
    c = patched(cfgmod.load(make_config()), {"policy.fit.min_points_per_coef": 100,
                                             "faults.hide_stored_ids": [1]}, "x")
    assert c["thread_id"] == "x" and c["run"]["mode"] == "replay"
    assert c["policy"]["fit"]["min_points_per_coef"] == 100 and cfgmod.validate(c) == []
    c["faults"]["delete_data"] = True                                   # unknown fault kinds are rejected
    assert any("unknown fault" in e for e in cfgmod.validate(c))
    from iris_agent.gates import g0_faults_only_in_replay
    st = {"config": {"run": {"mode": "skeleton"}, "faults": {"hide_stored_ids": [1]}}}
    assert g0_faults_only_in_replay(st)[0] == "FAULTS"                # faults only in replay mode
    st["config"]["run"]["mode"] = "replay"
    assert g0_faults_only_in_replay(st) is None


def test_every_rule_has_a_fault():
    rules = {r["id"] for r in yaml.safe_load((AGENT / "recovery.yaml").read_text())["rules"]}
    covered = {fx[1] for f in load_faults(FAULTS) for fx in f["expected"].get("fixes", []) if fx[1]}
    assert rules - covered == {"f0_schema_reask"}      # needs the LLM (step 6); its human fallback is in test_graph


@pytest.mark.skipif(not _available(), reason="CsSnI3 reference data not present")
def test_all_faults_handled_as_expected_E2():
    results, _ = run_all(FAULTS, CFG.parent, "pytest_E2", system="cssni3")
    bad = {r["id"]: r["checks"] for r in results if not r["passed"]}
    assert not bad, bad
