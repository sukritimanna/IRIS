import pytest
import yaml

from iris_agent import config as cfgmod
from iris_agent.paths import Paths, WriteOutsideAgentRoot


def test_shipped_config_is_valid(make_config):
    cfg = cfgmod.load(make_config())
    assert cfgmod.validate(cfg) == []


@pytest.mark.parametrize("patch,needle", [
    ({"run__budget_runs": 0}, "run.budget_runs"),
    ({"run__budget_runs": 10 ** 6}, "run.budget_runs"),
    ({"run__mode": "fast"}, "run.mode"),
    ({"run__allow_live_submission": True}, "live submission is disabled"),
    ({"policy__a_thr": "0.05"}, "policy.a_thr"),
    ({"llm__api_key_env": "MY_KEY"}, "ANTHROPIC_API_KEY"),
    ({"llm__api_key": "sk-ant-not-a-real-key"}, "must not appear"),
    ({"run__budget_runs": True}, "run.budget_runs"),
])
def test_schema_rejects(make_config, patch, needle):
    errs = cfgmod.validate(cfgmod.load(make_config(**patch)))
    assert any(needle in e for e in errs), errs


def test_missing_key(make_config):
    p = make_config()
    cfg = yaml.safe_load(p.read_text())
    del cfg["policy"]["r5_margin"]
    assert "policy.r5_margin: missing" in cfgmod.validate(cfg)


def test_write_guard(tmp_path):
    repo, agent = tmp_path / "repo", tmp_path / "repo" / "IRIS_AGENT"
    agent.mkdir(parents=True)
    p = Paths(repo, agent, {"test_runs": "test_runs"})
    assert p.out("test_runs", "x", "audit.jsonl").is_relative_to(agent.resolve())
    for bad in ("../demo/data.csv", "/etc/passwd", "test_runs/../../README.md"):
        with pytest.raises(WriteOutsideAgentRoot):
            p.out(bad)
    with pytest.raises(ValueError):
        Paths(repo, repo, {})
