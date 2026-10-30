import pytest
import yaml

from iris_agent import prompts
from iris_agent.recover import RecoveryTable

from .conftest import AGENT


def test_all_prompts_load_with_metadata():
    ps = prompts.all_prompts()
    ids = {p["id"] for p in ps}
    assert {"intake_f0", "borderline_R5", "human_interrupt"} <= ids
    assert {f"subagent_G{i}" for i in range(7)} <= ids
    for p in ps:
        assert p["id"] == p["id"].strip() and p["system"] and p["user"]
        assert set(prompts.placeholders(p["user"])) <= set(p["inputs"]), p["id"]


def test_gallery_is_up_to_date(tmp_path):
    fresh = prompts.build_gallery(tmp_path / "g.md")
    assert fresh.read_text() == (AGENT / "PROMPT_GALLERY.md").read_text(), \
        "regenerate with: python -m iris_agent.prompts --gallery"


def test_render_refuses_missing_values():
    with pytest.raises(KeyError):
        prompts.render("subagent_G2", system="cssni3")


def test_borderline_options_exist_in_recovery_menu():
    menu = {o["id"] for o in RecoveryTable(AGENT / "recovery.yaml").menu("f2")}
    allowed = set(prompts.load("borderline_R5")["output_schema"]["properties"]["id"]["enum"])
    assert allowed <= menu


def test_human_message_renders(make_config):
    from iris_agent.run import human_message
    msg = human_message({"node": "f0", "gate": "G0", "code": "CIF_MISSING", "detail": "x",
                         "options": [{"id": "stop", "text": "Stop"}], "why_human": {}, "attempts": 0},
                        "configs/cssni3.yaml", "cssni3_221_62")
    assert "f0 Intake" in msg and '--resume \'{"option": "<id>"}\'' in msg


def test_intake_example_matches_shipped_config():
    ex = prompts.load("intake_f0")["examples"][0]["output"]
    cfg = yaml.safe_load((AGENT / "configs" / "cssni3.yaml").read_text())
    assert ex["run"]["budget_runs"] == cfg["run"]["budget_runs"]
    assert ex["policy"]["strain_policy"] == cfg["policy"]["strain_policy"]
    assert ex["run"]["allow_live_submission"] is False
