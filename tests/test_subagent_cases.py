"""S5.2: the sub-agent benchmark cases (eval/subagent_cases.yaml + eval/subagent_cases/<id>.json).

Static checks only (the capture itself needs the replays): every case was captured at the gate it expects, every
menu option has exactly one label, the captured prompt re-renders from its stored template and values, the bare
variant differs from the guided one only by the Guidance line, and no absolute path is left in a case file.
"""
import json

import pytest

from iris_agent import prompts
from iris_agent.llm import bare_system
from iris_agent.recover import RecoveryTable
from iris_agent.subagent_cases import check_labels, load_cases

from .conftest import AGENT

CASES = load_cases(AGENT / "eval" / "subagent_cases.yaml")["cases"]
DIR = AGENT / "eval" / "subagent_cases"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_captured_labelled_and_reproducible(case):
    f = DIR / f"{case['id']}.json"
    assert f.is_file(), "run: python -m iris_agent.subagent_cases"
    cap = json.loads(f.read_text())
    assert (cap["node"], cap["code"]) == (case["expect"]["node"], case["expect"]["code"])
    menu = [o["id"] for o in cap["menu"]]
    assert menu == [o["id"] for o in RecoveryTable(AGENT / "recovery.yaml").menu(cap["node"])]
    assert check_labels(case, menu) == []
    assert prompts._fill(cap["user_template"], {k: (json.dumps(v, indent=1) if isinstance(v, (dict, list)) else v)
                                                for k, v in cap["prompt_values"].items()}) == cap["user_prompt"]
    assert bare_system(cap["system_prompt"]) == cap["system_prompt_bare"] != cap["system_prompt"]
    text = f.read_text()
    assert "/home/" not in text and "/Users/" not in text and "/tmp/" not in text


def test_case_set_balance():
    n = len(CASES)
    stop = sum(1 for c in CASES if c["labels"]["correct"] == ["stop"])
    assert n >= 50 and 0.3 <= stop / n <= 0.6               # an always-stop policy must not win
    assert {c["class"] for c in CASES} >= {"rules_off", "used_up", "judgment", "decoy", "no_rule"}
    assert all("stop" not in c["labels"].get("harmful", []) for c in CASES)      # always-stop is never harmful
    held = [c for c in CASES if c.get("split") == "held-out"]
    assert 0.25 <= len(held) / n <= 0.35
    assert {c["system"].split("_")[0] for c in held} == {"cssni3", "ca3ti2o7", "inmno3", "ermno3", "bifeo3", "hfo2"}
    assert {c["system"].split("_")[0] for c in CASES} == {"cssni3", "ca3ti2o7", "inmno3", "ermno3", "bifeo3", "hfo2"}
