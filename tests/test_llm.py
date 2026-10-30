"""Build step 5, S5.1: the provider layer (iris_agent/llm.py) with a fake transport — no network, no keys needed.

Checks per provider: the request IRIS sends (constrained = enum of the menu ids; free = plain JSON asked for),
the parsing of a canned reply (id, tokens, model version), invalid answers (off-menu id, unparseable, truncated)
counted and never retried, transport errors retried, a missing key = no call, and the key never written anywhere.
Then recover() with the real sub-agent: a valid choice is applied as tier "subagent" and audited with the model fields.
"""
import json

import pytest

from iris_agent import llm
from iris_agent.audit import AuditLog
from iris_agent.recover import RecoveryTable, make_recover

from .conftest import AGENT

IDS = ["resubmit", "flag_and_continue", "stop"]
KEY = "sk-test-SENTINEL-0123456789"


class Fake:
    """Records requests; answers with canned (status, json) replies in order."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def anthropic_reply(id_="stop", stop="end_turn"):
    return 200, {"model": "claude-x-20261001", "stop_reason": stop,
                 "content": [{"type": "text", "text": json.dumps({"id": id_, "reason": "r"})}],
                 "usage": {"input_tokens": 900, "output_tokens": 40}}


def responses_reply(text, status="completed", reason=None):
    return 200, {"object": "response", "model": "gpt-6-x", "status": status,
                 "incomplete_details": {"reason": reason} if reason else None,
                 "output": [{"type": "reasoning", "summary": []},
                            {"type": "message", "content": [{"type": "output_text", "text": text}]}],
                 "usage": {"input_tokens": 800, "output_tokens": 60, "output_tokens_details": {"reasoning_tokens": 40}}}


def openai_reply(text, finish="stop"):
    return 200, {"model": "gpt-x-2026", "system_fingerprint": "fp1",
                 "choices": [{"finish_reason": finish, "message": {"content": text}}],
                 "usage": {"prompt_tokens": 800, "completion_tokens": 30, "completion_tokens_details": {"reasoning_tokens": 12}}}


def google_reply(text, finish="STOP"):
    return 200, {"modelVersion": "gemini-x-001", "candidates": [{"finishReason": finish, "content": {"parts": [{"text": text}]}}],
                 "usageMetadata": {"promptTokenCount": 700, "candidatesTokenCount": 25, "thoughtsTokenCount": 50}}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test may reach a provider: the real transport is replaced unless a test passes its own."""
    def refuse(*a, **k):
        raise AssertionError("network call in a test")
    monkeypatch.setattr(llm, "http_json", refuse)


@pytest.fixture
def keys(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.setenv(k, KEY)


def spec(provider, **kw):
    return {"provider": provider, "model": f"{provider}-model", "mode": "constrained", "temperature": 0, "seed": 0, **kw}


def test_anthropic_constrained_request_and_parse(keys):
    t = Fake(anthropic_reply("flag_and_continue"))
    r = llm.llm_choose(spec("anthropic", price_usd_per_mtok={"in": 3, "out": 15}), "sys", "user", IDS, transport=t)
    b, h = t.calls[0]["body"], t.calls[0]["headers"]
    assert t.calls[0]["url"] == "https://api.anthropic.com/v1/messages" and h["x-api-key"] == KEY
    fmt = b["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["properties"]["id"]["enum"] == IDS
    assert fmt["schema"]["additionalProperties"] is False and "tools" not in b and b["temperature"] == 0
    assert r["valid"] and r["id"] == "flag_and_continue" and r["model_version"] == "claude-x-20261001"
    assert (r["tokens_in"], r["tokens_out"]) == (900, 40) and r["cost_usd"] == pytest.approx((900 * 3 + 40 * 15) / 1e6)
    assert r["constrained_decoding"].startswith("enforced")


def test_anthropic_enum_case_is_normalised_and_temperature_omitted(keys):
    t = Fake(anthropic_reply("Flag_and_continue"))
    r = llm.llm_choose(spec("anthropic", temperature=None), "s", "u", IDS, transport=t)
    assert "temperature" not in t.calls[0]["body"]
    assert r["valid"] and r["id"] == "flag_and_continue" and r["case_normalized"] is True


def test_openai_responses_api_is_the_default(keys):
    t = Fake(responses_reply('{"id": "resubmit", "reason": "x"}'))
    r = llm.llm_choose(spec("openai", temperature=None, reasoning_effort="low"), "sys", "user", IDS, transport=t)
    c = t.calls[0]
    b = c["body"]
    assert c["url"] == "https://api.openai.com/v1/responses" and c["headers"]["authorization"] == f"Bearer {KEY}"
    assert b["instructions"] == "sys" and b["input"] == "user" and b["reasoning"] == {"effort": "low"}
    assert b["text"]["format"]["strict"] is True and b["text"]["format"]["schema"]["properties"]["id"]["enum"] == IDS
    assert "temperature" not in b and "seed" not in b and "max_output_tokens" in b
    assert r["valid"] and r["id"] == "resubmit" and (r["tokens_in"], r["tokens_out"], r["tokens_reasoning"]) == (800, 60, 40)
    t = Fake(responses_reply('{"id": "stop"', "incomplete", "max_output_tokens"))
    r = llm.llm_choose(spec("openai", mode="free"), "s", "u", IDS, transport=t)
    assert not r["valid"] and "truncated" in r["status"]


def test_openai_chat_completions_request_and_parse(keys):
    t = Fake(openai_reply('{"id": "resubmit", "reason": "x"}'))
    r = llm.llm_choose(spec("openai", api="chat"), "sys", "user", IDS, transport=t)
    b = t.calls[0]["body"]
    assert t.calls[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert t.calls[0]["headers"]["authorization"] == f"Bearer {KEY}"
    assert b["response_format"]["json_schema"]["strict"] is True
    assert b["response_format"]["json_schema"]["schema"]["properties"]["id"]["enum"] == IDS
    assert "max_completion_tokens" in b and b["seed"] == 0 and b["messages"][0]["role"] == "system"
    assert r["valid"] and r["id"] == "resubmit" and r["tokens_reasoning"] == 12 and r["system_fingerprint"] == "fp1"


def test_openai_compatible_server_and_no_temperature(monkeypatch):
    monkeypatch.delenv("OPENAI_COMPAT_API_KEY", raising=False)
    t = Fake(openai_reply('{"id": "stop", "reason": "x"}'))
    r = llm.llm_choose(spec("openai", base_url="http://localhost:8000/v1/", api_key_env="none", temperature=None),
                       "s", "u", IDS, transport=t)
    b = t.calls[0]["body"]
    assert t.calls[0]["url"] == "http://localhost:8000/v1/chat/completions" and "authorization" not in t.calls[0]["headers"]
    assert "max_tokens" in b and "temperature" not in b and r["valid"]


def test_google_constrained_request_and_parse(keys):
    t = Fake(google_reply('{"id": "stop", "reason": "x"}'))
    r = llm.llm_choose(spec("google", price_usd_per_mtok={"in": 1, "out": 10}), "sys", "user", IDS, transport=t)
    c = t.calls[0]
    assert c["url"].endswith("/models/google-model:generateContent") and c["headers"]["x-goog-api-key"] == KEY
    gc = c["body"]["generationConfig"]
    assert gc["responseMimeType"] == "application/json" and gc["responseSchema"]["properties"]["id"]["enum"] == IDS
    assert c["body"]["systemInstruction"]["parts"][0]["text"] == "sys"
    assert r["valid"] and r["model_version"] == "gemini-x-001" and r["tokens_reasoning"] == 50
    assert r["cost_usd"] == pytest.approx((700 * 1 + (25 + 50) * 10) / 1e6)


@pytest.mark.parametrize("prov,reply", [("anthropic", None), ("openai", responses_reply), ("google", google_reply)])
def test_free_mode_has_no_schema_and_parses_text(keys, prov, reply):
    if prov == "anthropic":
        rep = (200, {"model": "m", "stop_reason": "end_turn", "content": [{"type": "text", "text": '```json\n{"id": "stop", "reason": "r"}\n```'}],
                     "usage": {"input_tokens": 1, "output_tokens": 1}})
    else:
        rep = reply('Sure. {"id": "stop", "reason": "r"}')
    t = Fake(rep)
    r = llm.llm_choose(spec(prov, mode="free"), "s", "u", IDS, transport=t)
    b = json.dumps(t.calls[0]["body"])
    assert "enum" not in b and "output_config" not in b and '"text": {"format"' not in b and "response_format" not in b \
        and "responseSchema" not in b
    assert "single JSON object" in b
    assert r["valid"] and r["id"] == "stop" and r["constrained_decoding"] == "none (free)"


@pytest.mark.parametrize("text,finish,why", [('{"id": "rerun", "reason": "x"}', "stop", "not on the menu"),
                                             ("I would stop.", "stop", "unparseable"),
                                             ('{"id": "stop", "reason": "x"}', "length", "truncated")])
def test_invalid_answers_are_counted_not_retried(keys, text, finish, why):
    t = Fake(openai_reply(text, finish))
    r = llm.llm_choose(spec("openai", mode="free", api="chat"), "s", "u", IDS, transport=t)
    assert not r["valid"] and r["id"] is None and why in r["status"] and len(t.calls) == 1


def test_transport_errors_retried_then_http_error_reported(keys):
    t = Fake((429, {}), TimeoutError("slow"), anthropic_reply("stop"))
    r = llm.llm_choose(spec("anthropic"), "s", "u", IDS, transport=t)
    assert r["valid"] and r["transport_retries"] == 2 and len(t.calls) == 3
    t = Fake((400, {"error": {"message": "bad request"}}))
    r = llm.llm_choose(spec("anthropic"), "s", "u", IDS, transport=t)
    assert not r["valid"] and r["status"] == "http 400" and "bad request" in r["error"] and len(t.calls) == 1


def test_missing_key_makes_no_call(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    t = Fake()
    r = llm.llm_choose(spec("google"), "s", "u", IDS, transport=t)
    assert not r["valid"] and r["status"] == "no GOOGLE_API_KEY in environment" and t.calls == []


def test_models_file(tmp_path):
    ms = llm.load_models(AGENT / "eval" / "models.yaml")
    assert {"claude-haiku", "claude-sonnet", "claude-opus"} <= set(ms)
    assert {m["provider"] for m in ms.values()} == {"anthropic", "openai", "google"} and all(m["model"] for m in ms.values())
    assert all(m["mode"] == "constrained" for m in ms.values())
    bad = tmp_path / "m.yaml"
    bad.write_text("models:\n  x: {provider: openai, model: m, api_key: sk-proj-abc}\n")
    with pytest.raises(llm.LLMError):
        llm.load_models(bad)
    bad.write_text("models:\n  x: {provider: openai, model: m, api_key_env: MY_SECRET}\n")
    with pytest.raises(llm.LLMError):
        llm.load_models(bad)


# ---- recover() with the real sub-agent --------------------------------------------------------------------------
def _state(node, code, spec_):
    return {"last_node": node, "gate": {"ok": False, "code": code, "detail": "part 3 failed again",
                                        "tests": [{"test": "converged_or_flagged", "status": "fail", "code": code}]},
            "config": {"system": "cssni3", "retry": {"max_per_node": 3}, "llm": {"enabled": False}},
            "run_meta": {"llm_spec": spec_, "ablation_flags": ["no-rules"]}, "thread_id": "t",
            "attempts": {}, "overrides": {}, "history": []}


def test_recover_applies_valid_choice_and_audits_model_fields(tmp_path, keys):
    t = Fake(anthropic_reply("flag_and_continue"))
    sub = llm.make_subagent(transport=t, calls_log=tmp_path / "llm_calls.jsonl")
    audit = AuditLog(tmp_path / "a.jsonl", "t")
    out = make_recover(RecoveryTable(AGENT / "recovery.yaml"), audit, sub)(
        _state("f4", "WALLTIME", spec("anthropic", name="claude-sonnet", shuffle_options=True)))
    h = out["history"][-1]
    assert h["level"] == "subagent" and h["option"] == "flag_and_continue" and out["route"] == "f4"
    assert out["overrides"]["f4"] == {"flag_unconverged": True}
    user = t.calls[0]["body"]["messages"][0]["content"]
    assert "WALLTIME" in user and "flag_and_continue" in user and "part 3 failed again" in user
    fix = [r for r in audit.read() if r["kind"] == "fix"][-1]
    assert fix["recovery_tier"] == "subagent" and fix["output_valid"] is True
    assert fix["tokens_in"] == 900 and fix["llm"]["provider"] == "anthropic" and fix["llm"]["model_version"] == "claude-x-20261001"
    assert sorted(fix["llm"]["option_order"]) == sorted(o["id"] for o in RecoveryTable(AGENT / "recovery.yaml").menu("f4", "WALLTIME"))   # the admissible menu for this code
    for f in (tmp_path / "a.jsonl", tmp_path / "llm_calls.jsonl"):
        assert KEY not in f.read_text()
    call = json.loads((tmp_path / "llm_calls.jsonl").read_text().splitlines()[0])
    assert call["valid"] and "WALLTIME" in call["user_prompt"]


def test_recover_sends_invalid_choice_to_human(tmp_path, keys):
    from langgraph.errors import GraphInterrupt
    t = Fake(responses_reply('{"id": "rerun_everything", "reason": "x"}'))
    sub = llm.make_subagent(transport=t)
    rec = make_recover(RecoveryTable(AGENT / "recovery.yaml"), AuditLog(tmp_path / "a.jsonl", "t"), sub)
    with pytest.raises((GraphInterrupt, RuntimeError)):           # interrupt() outside a graph
        rec(_state("f4", "WALLTIME", spec("openai", mode="free")))
    assert len(t.calls) == 1


def test_option_order_shuffle_is_deterministic(keys):
    def order(seed):
        t = Fake(anthropic_reply("stop"))
        out = llm.make_subagent(transport=t)("f4", {"code": "WALLTIME", "tests": []},
                                             RecoveryTable(AGENT / "recovery.yaml").menu("f4"),
                                             _state("f4", "WALLTIME", spec("anthropic", shuffle_options=True, option_order_seed=seed)))
        return out["llm"]["option_order"]
    assert order(1) == order(1) and order(1) != order(2) or order(1) != order(3)


def test_graph_runs_a_fault_with_the_subagent_and_no_rules(tmp_path):
    """CsSnI3 F001 (part 3 WALLTIME) with the rule table ablated: the (fake) sub-agent is asked at G4, its choice
    (first menu item: resubmit) is applied, the run completes, and the audit/fix line carries the model fields."""
    from .test_regression_cssni3 import CFG, _available
    if not _available():
        pytest.skip("CsSnI3 runs not present")
    from iris_agent.inject import load_faults, run_fault
    m = tmp_path / "models.yaml"
    m.write_text("models:\n  fake-first: {provider: fake, model: fake-0, mode: constrained}\n")
    f = next(x for x in load_faults(AGENT / "eval" / "faults.yaml") if x["id"] == "F001")
    from iris_agent import config as cfgmod
    from iris_agent.paths import from_config
    tr = from_config(cfgmod.load(CFG)).agent_root / "test_runs"
    r = run_fault(f, CFG.parent, "pytest_s51", tr / "pytest_s51", ablations=["no-rules"], llm="fake-first", models=m)
    assert r["final"] == "completed", r
    rd = tr / "pytest_s51_F001"
    fixes = [json.loads(x) for x in (rd / "audit.jsonl").read_text().splitlines() if '"kind": "fix"' in x]
    assert [x["recovery_tier"] for x in fixes] == ["subagent"] and fixes[0]["option_id"] == "resubmit"
    assert fixes[0]["llm"]["provider"] == "fake" and fixes[0]["provider"] == "fake"
    assert (rd / "llm_calls.jsonl").is_file()


def test_check_saves_an_organized_folder(tmp_path, monkeypatch, keys):
    """--check: lists + pings in both modes, saved as models_<provider>.txt, ping_<mode>.jsonl, summary.md."""
    def fake_http(method, url, headers, body, timeout):
        if method == "GET":
            if "anthropic" in url:
                return 200, {"data": [{"id": "claude-a"}]}
            if "openai" in url:
                return 200, {"data": [{"id": "gpt-b"}, {"id": "gpt-a"}]}
            return 200, {"models": [{"name": "models/gem-a", "supportedGenerationMethods": ["generateContent"]}]}
        if "anthropic" in url:
            return anthropic_reply("beta")
        if "openai" in url:
            return responses_reply('{"id": "beta", "reason": "r"}')
        return google_reply('{"id": "beta", "reason": "r"}')
    monkeypatch.setattr(llm, "http_json", fake_http)
    monkeypatch.setattr(llm, "CHECKS_DIR", tmp_path / "checks")
    m = tmp_path / "models.yaml"
    m.write_text("models:\n  c: {provider: anthropic, model: claude-a}\n  o: {provider: openai, model: gpt-a}\n"
                 "  g: {provider: google, model: gem-a}\n  x: {provider: openai, model: null}\n")
    llm.main(["--check", "--models", str(m)])
    d, = (tmp_path / "checks").iterdir()
    assert sorted(p.name for p in d.iterdir()) == ["models_anthropic.txt", "models_google.txt", "models_openai.txt",
                                                    "ping_constrained.jsonl", "ping_free.jsonl", "summary.md"]
    assert (d / "models_openai.txt").read_text().split() == ["gpt-a", "gpt-b"]
    rows = [json.loads(x) for x in (d / "ping_free.jsonl").read_text().splitlines()]
    assert [r.get("correct") for r in rows] == [True, True, True, None] and rows[3]["status"].startswith("skipped")
    s = (d / "summary.md").read_text()
    assert "3 of 3 called models answered `beta`" in s and KEY not in s
    for f in d.iterdir():
        assert KEY not in f.read_text()
