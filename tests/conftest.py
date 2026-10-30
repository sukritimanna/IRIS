"""Test fixtures. Every test builds its own temporary repo_root/agent_root pair, so the test suite
never reads from or writes to the real imhafo2 repo (the CsSnI3 inputs are copies in fixtures/)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

AGENT = Path(__file__).resolve().parents[1]
FIX = AGENT / "tests" / "fixtures" / "cssni3"


@pytest.fixture
def sandbox(tmp_path):
    """tmp/repo (read-only inputs) + tmp/repo/IRIS_AGENT (agent_root with recovery.yaml)."""
    repo = tmp_path / "repo"
    (repo / "demo/cssni3/structures").mkdir(parents=True)
    for f in FIX.glob("*.cif"):
        shutil.copy(f, repo / "demo/cssni3/structures" / f.name)
    agent = repo / "IRIS_AGENT"
    agent.mkdir()
    shutil.copy(AGENT / "recovery.yaml", agent / "recovery.yaml")
    return repo, agent


@pytest.fixture
def make_config(sandbox):
    repo, agent = sandbox

    def _make(name="t", **patch):
        cfg = yaml.safe_load((AGENT / "configs" / "cssni3.yaml").read_text())
        cfg["paths"]["repo_root"] = str(repo)
        cfg["paths"]["agent_root"] = str(agent)
        cfg["thread_id"] = name
        cfg["run"]["mode"] = "skeleton"          # graph tests: f1-f6 stubbed unless a test sets replay
        for dotted, v in patch.items():
            cur, keys = cfg, dotted.split("__")
            for k in keys[:-1]:
                cur = cur.setdefault(k, {})
            cur[keys[-1]] = v
        p = agent / "configs" / f"{name}.yaml"
        p.parent.mkdir(exist_ok=True)
        p.write_text(yaml.safe_dump(cfg, sort_keys=False))
        return p

    return _make


@pytest.fixture
def cssni3_step3():
    import json
    c = json.loads((FIX / "classification.json").read_text())
    t = json.loads((FIX / "subgroup_tree.json").read_text())
    return c, t
