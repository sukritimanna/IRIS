"""Sub-agents (build step 5): one provider-agnostic call, llm_choose(), that asks a model to pick ONE option id.

Providers (plain HTTPS, standard library only; no SDKs, nothing to install):
  anthropic  Messages API            constrained = output_config.format json_schema with the id enum (enforced; the API
                                     notes that enum capitalisation is not guaranteed -> matched case-insensitively,
                                     recorded as case_normalized)
  openai     Responses API (api.openai.com, default `api: responses`): text.format json_schema, strict, id enum;
             Chat Completions (`api: chat`; default with `base_url`): response_format json_schema, strict — also any
             OpenAI-compatible server (vLLM, Ollama, ...) for open models (e.g. Qwen)
  google     Gemini generateContent  constrained = responseSchema with the id enum (enforced by the API)
  fake       no network; for tests (answers from the spec's `fake_answers` map or the first option)
mode "free": no schema; the model is asked for a JSON object in plain text and IRIS parses it. An id that is not
on the menu, unparseable text or a truncated answer is INVALID: logged, never retried, and recover() sends the case
to the human. Transport errors (429 / 5xx / timeout) are retried up to 3 times with back-off and counted.

Keys: read from the provider's environment variable inside the call only (ANTHROPIC_API_KEY, OPENAI_API_KEY,
GOOGLE_API_KEY; an OpenAI-compatible server may name another variable or none). A key never enters state, the
audit log or llm_calls.jsonl.

  python -m iris_agent.llm --check                             # all of the below, saved to results/llm_checks/<UTC time>/
  python -m iris_agent.llm --list anthropic|openai|google      # model ids the account can use (pin them in eval/models.yaml)
  python -m iris_agent.llm --ping <name>|all [--mode free]     # one call with a fixed dummy prompt (no project data)
--list / --ping also save their output when given --save (same folder layout).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

PROVIDERS = ("anthropic", "openai", "google", "fake", "policy")
POLICIES = {"tree": ("policies.tree", "choose"), "retrieval": ("policies.retrieval", "choose"),
            "retrieval_seed": ("policies.retrieval", "choose_seed"), "rules_only": ("policies.rules_only", "choose")}
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "google": "GOOGLE_API_KEY"}
ALLOWED_KEY_ENVS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "OPENAI_COMPAT_API_KEY", "none")
CONSTRAINED = {"anthropic": "enforced (output_config json_schema)", "openai": "enforced (json_schema strict)",
               "google": "enforced (responseSchema enum)", "fake": "n/a", "policy": "n/a (deterministic policy)"}
URL = {"anthropic": "https://api.anthropic.com/v1/messages",
       "openai": "https://api.openai.com/v1",
       "google": "https://generativelanguage.googleapis.com/v1beta"}
ANTHROPIC_VERSION = "2023-06-01"
RETRY_STATUS = (408, 429, 500, 502, 503, 504, 529)
MODELS_YAML = Path(__file__).resolve().parents[1] / "eval" / "models.yaml"
FREE_SUFFIX = ('\n\nReply with a single JSON object {"id": "<one option id>", "reason": "<one sentence>"} '
               "and nothing else.")


class LLMError(Exception):
    pass


# ---- transport (replaced by a fake in tests) --------------------------------------------------------------------
def http_json(method: str, url: str, headers: dict, body: dict | None, timeout: float) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


_REAL_HTTP = http_json


def _key(spec: dict) -> str | None:
    env = spec.get("api_key_env") or KEY_ENV.get(spec["provider"])
    if env == "none":
        return ""
    return os.environ.get(env) if env else None


def _schema(option_ids: list[str], constrained: bool) -> dict:
    idp = {"type": "string", "description": "one id from the options list"}
    if constrained:
        idp["enum"] = list(option_ids)
    return {"type": "object", "properties": {"id": idp, "reason": {"type": "string"}},
            "required": ["id", "reason"], "additionalProperties": False}


def _parse_free(text: str) -> dict | None:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                v = json.loads(m.group(0))
                return v if isinstance(v, dict) else None
            except Exception:
                return None
    return None


# ---- adapters: (spec, system, user, ids, constrained) -> (url, headers, body); parse(response) -> fields ---------
def _anthropic_req(spec, system, user, ids, constrained, key):
    body = {"model": spec["model"], "max_tokens": int(spec.get("max_tokens", 2048)), "system": system,
            "messages": [{"role": "user", "content": user if constrained else user + FREE_SUFFIX}]}
    if spec.get("temperature") is not None:
        body["temperature"] = spec["temperature"]
    if constrained:
        body["output_config"] = {"format": {"type": "json_schema", "schema": _schema(ids, True)}}
    return URL["anthropic"], {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}, body


def _anthropic_parse(r, constrained):
    content = r.get("content") or []
    text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
    u = r.get("usage") or {}
    return {"obj": _parse_free(text), "text": text, "model_version": r.get("model"), "finish": r.get("stop_reason"),
            "truncated": r.get("stop_reason") == "max_tokens", "refusal": r.get("stop_reason") == "refusal",
            "tokens_in": u.get("input_tokens"), "tokens_out": u.get("output_tokens"), "tokens_reasoning": None}


def _openai_api(spec):
    return spec.get("api") or ("chat" if spec.get("base_url") else "responses")


def _openai_req(spec, system, user, ids, constrained, key):
    base = (spec.get("base_url") or URL["openai"]).rstrip("/")
    headers = {"authorization": f"Bearer {key}"} if key else {}
    content = user if constrained else user + FREE_SUFFIX
    if _openai_api(spec) == "responses":
        body = {"model": spec["model"], "instructions": system, "input": content,
                "max_output_tokens": int(spec.get("max_tokens", 4096))}
        if spec.get("temperature") is not None:
            body["temperature"] = spec["temperature"]
        if spec.get("reasoning_effort"):
            body["reasoning"] = {"effort": spec["reasoning_effort"]}
        if constrained:
            body["text"] = {"format": {"type": "json_schema", "name": "choice", "strict": True, "schema": _schema(ids, True)}}
        return f"{base}/responses", headers, body
    tok = spec.get("token_param") or ("max_completion_tokens" if base == URL["openai"] else "max_tokens")
    body = {"model": spec["model"], tok: int(spec.get("max_tokens", 4096)),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
    if spec.get("temperature") is not None:
        body["temperature"] = spec["temperature"]
    if spec.get("seed") is not None:
        body["seed"] = int(spec["seed"])
    if spec.get("reasoning_effort"):
        body["reasoning_effort"] = spec["reasoning_effort"]
    if constrained:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "choice", "strict": True, "schema": _schema(ids, True)}}
    return f"{base}/chat/completions", headers, body


def _openai_parse(r, constrained):
    if r.get("object") == "response" or "output" in r:            # Responses API
        text, refusal = "", None
        for item in r.get("output") or []:
            if item.get("type") == "message":
                for c in item.get("content") or []:
                    if c.get("type") == "output_text":
                        text += c.get("text", "")
                    elif c.get("type") == "refusal":
                        refusal = c.get("refusal")
        u = r.get("usage") or {}
        inc = (r.get("incomplete_details") or {}).get("reason")
        return {"obj": _parse_free(text), "text": text, "model_version": r.get("model"), "finish": r.get("status"),
                "truncated": r.get("status") == "incomplete" and inc == "max_output_tokens", "refusal": refusal,
                "tokens_in": u.get("input_tokens"), "tokens_out": u.get("output_tokens"),
                "tokens_reasoning": (u.get("output_tokens_details") or {}).get("reasoning_tokens")}
    ch = (r.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    text = msg.get("content") or ""
    u = r.get("usage") or {}
    det = u.get("completion_tokens_details") or {}
    return {"obj": _parse_free(text), "text": text, "model_version": r.get("model"),
            "system_fingerprint": r.get("system_fingerprint"), "finish": ch.get("finish_reason"),
            "truncated": ch.get("finish_reason") == "length", "refusal": msg.get("refusal"),
            "tokens_in": u.get("prompt_tokens"), "tokens_out": u.get("completion_tokens"),
            "tokens_reasoning": det.get("reasoning_tokens")}


def _google_schema(ids, constrained):
    idp = {"type": "STRING"}
    if constrained:
        idp["enum"] = list(ids)
    return {"type": "OBJECT", "properties": {"id": idp, "reason": {"type": "STRING"}}, "required": ["id", "reason"],
            "propertyOrdering": ["id", "reason"]}


def _google_req(spec, system, user, ids, constrained, key):
    gc = {"maxOutputTokens": int(spec.get("max_tokens", 4096))}
    if spec.get("temperature") is not None:
        gc["temperature"] = spec["temperature"]
    if spec.get("seed") is not None:
        gc["seed"] = int(spec["seed"])
    if constrained:
        gc["responseMimeType"] = "application/json"
        gc["responseSchema"] = _google_schema(ids, True)
    if spec.get("thinking_budget") is not None:
        gc["thinkingConfig"] = {"thinkingBudget": int(spec["thinking_budget"])}
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user if constrained else user + FREE_SUFFIX}]}],
            "generationConfig": gc}
    return f"{URL['google']}/models/{spec['model']}:generateContent", {"x-goog-api-key": key}, body


def _google_parse(r, constrained):
    c = (r.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", []) if not p.get("thought"))
    u = r.get("usageMetadata") or {}
    return {"obj": _parse_free(text), "text": text, "model_version": r.get("modelVersion"),
            "finish": c.get("finishReason"), "truncated": c.get("finishReason") == "MAX_TOKENS",
            "tokens_in": u.get("promptTokenCount"), "tokens_out": u.get("candidatesTokenCount"),
            "tokens_reasoning": u.get("thoughtsTokenCount")}


ADAPTERS = {"anthropic": (_anthropic_req, _anthropic_parse), "openai": (_openai_req, _openai_parse),
            "google": (_google_req, _google_parse)}


def _cost(spec, tin, tout, treason):
    p = spec.get("price_usd_per_mtok") or {}
    if not p or tin is None:
        return None
    out = (tout or 0) + (treason or 0 if spec["provider"] == "google" else 0)   # Gemini bills thinking as output
    return round((tin * float(p["in"]) + out * float(p["out"])) / 1e6, 8)


_POLICY_OK = {}


def _policy(name: str):
    """Experiment A policies (IRIS_AGENT/policies): refuse unless every file matches policies/FROZEN.sha256."""
    import hashlib as _h
    import importlib
    import sys as _sys
    root = Path(__file__).resolve().parents[1]
    if not _POLICY_OK:
        for line in (root / "policies" / "FROZEN.sha256").read_text().splitlines():
            if line and not line.startswith("#"):
                h, f = line.split(None, 1)
                if _h.sha256((root / "policies" / f).read_bytes()).hexdigest() != h:
                    raise LLMError(f"policies/{f} changed since the freeze")
        _POLICY_OK["ok"] = True
    if str(root) not in _sys.path:
        _sys.path.insert(0, str(root))
    mod, fn = POLICIES[name]
    return getattr(importlib.import_module(mod), fn)


def llm_choose(spec: dict, system: str, user: str, option_ids: list[str], *, transport=None, context=None) -> dict:
    """One decision. Returns {id|None, reason, valid, status, provider, model, model_version, mode, temperature, seed,
    constrained_decoding, tokens_in/out/reasoning, cost_usd, latency_s, transport_retries, error, raw_text}."""
    transport = transport or globals()["http_json"]       # resolved at call time (tests replace it)
    prov = spec["provider"]
    if prov not in PROVIDERS:
        raise LLMError(f"unknown provider {prov!r}")
    mode = spec.get("mode", "constrained")
    constrained = mode == "constrained"
    meta = {"provider": prov, "model": spec.get("model"), "mode": mode, "temperature": spec.get("temperature"),
            "seed": spec.get("seed"), "constrained_decoding": CONSTRAINED[prov] if constrained else "none (free)",
            "name": spec.get("name"), "prompt_sha256": hashlib.sha256((system + "\n" + user).encode()).hexdigest()[:16]}
    t0 = time.monotonic()
    if prov == "policy":
        ctx = {**(context or {}), "options": list(option_ids)}
        ans, why = _policy(spec["policy"])(ctx)
        text = json.dumps({"id": ans, "reason": why})
        f = {"obj": {"id": ans, "reason": why}, "text": text, "model_version": f"policy:{spec['policy']}",
             "finish": "stop", "truncated": False, "tokens_in": 0, "tokens_out": 0, "tokens_reasoning": None}
        retries = 0
    elif prov == "fake":
        if "fake_answer" in spec:                         # scripted (None = decline; used to capture cases)
            ans = spec["fake_answer"]
        else:
            ans = (spec.get("fake_answers") or {}).get(spec.get("_case"), option_ids[0] if option_ids else None)
        text = json.dumps({"id": ans, "reason": "fake provider"})
        f = {"obj": json.loads(text), "text": text, "model_version": "fake-0", "finish": "stop", "truncated": False,
             "tokens_in": len((system + user).split()), "tokens_out": 8, "tokens_reasoning": None}
        retries = 0
    else:
        key = _key(spec)
        if key is None:
            env = spec.get("api_key_env") or KEY_ENV.get(prov)
            return {**meta, "id": None, "reason": "", "valid": False, "status": f"no {env} in environment",
                    "error": "missing key", "latency_s": 0.0, "transport_retries": 0}
        build, parse = ADAPTERS[prov]
        url, headers, body = build(spec, system, user, option_ids, constrained, key)
        timeout = float(spec.get("timeout_s", 120))
        retries, status, r = 0, None, {}
        while True:
            try:
                status, r = transport("POST", url, headers, body, timeout)
            except Exception as exc:                      # timeout / connection error
                status, r = None, {"error": {"message": f"{type(exc).__name__}: {exc}"}}
            if (status is None or status in RETRY_STATUS) and retries < 3:
                retries += 1
                time.sleep(min(30.0, 2.0 ** retries) if transport is _REAL_HTTP else 0)
                continue
            break
        del key, headers                                   # the key is never kept
        if status != 200:
            msg = str((r.get("error") or {}).get("message", r))[:300] if isinstance(r, dict) else str(r)[:300]
            return {**meta, "id": None, "reason": "", "valid": False, "status": f"http {status}", "error": msg,
                    "latency_s": round(time.monotonic() - t0, 3), "transport_retries": retries}
        f = parse(r, constrained)
    obj = f.get("obj") if isinstance(f.get("obj"), dict) else None
    cid = obj.get("id") if obj else None
    case_norm = False
    if isinstance(cid, str) and cid not in option_ids:
        hit = [o for o in option_ids if o.lower() == cid.strip().lower()]
        if len(hit) == 1:                               # Anthropic: enum capitalisation is not guaranteed
            cid, case_norm = hit[0], True
    valid = bool(obj) and cid in option_ids and not f.get("truncated")
    why = (None if valid else "truncated" if f.get("truncated") else "unparseable" if not obj
           else f"id {cid!r} not on the menu")
    out = {**meta, "id": cid if valid else None, "answered_id": cid, "reason": str((obj or {}).get("reason", ""))[:500],
           "valid": valid, "status": "answered" if valid else f"invalid: {why}", "error": None if valid else why,
           "case_normalized": case_norm, "refusal": f.get("refusal") or None,
           "model_version": f.get("model_version"), "system_fingerprint": f.get("system_fingerprint"),
           "finish": f.get("finish"), "tokens_in": f.get("tokens_in"), "tokens_out": f.get("tokens_out"),
           "tokens_reasoning": f.get("tokens_reasoning"),
           "cost_usd": _cost(spec, f.get("tokens_in"), f.get("tokens_out"), f.get("tokens_reasoning")),
           "latency_s": round(time.monotonic() - t0, 3), "transport_retries": retries, "raw_text": (f.get("text") or "")[:2000]}
    return out


# ---- the sub-agent recover() calls -----------------------------------------------------------------------------
def load_models(path: str | Path = MODELS_YAML) -> dict:
    data = yaml.safe_load(Path(path).read_text())
    out = {}
    for name, spec in (data.get("models") or {}).items():
        s = {**(data.get("defaults") or {}), **spec, "name": name}
        from .config import _has_secret
        if "api_key" in s or "key" in s or _has_secret(s):
            raise LLMError(f"{name}: keys never go in files; use api_key_env")
        if s.get("api_key_env", KEY_ENV.get(s["provider"], "none")) not in ALLOWED_KEY_ENVS:
            raise LLMError(f"{name}: api_key_env must be one of {ALLOWED_KEY_ENVS}")
        out[name] = s
    return out


def subagent_values(node: str, gate: dict, options: list[dict], state: dict) -> dict:
    from .state import GATE_OF, NODE_NAMES
    cfg = state["config"]
    hist = [{k: h.get(k) for k in ("node", "code", "level", "rule", "option", "route") if h.get(k) is not None}
            for h in state.get("history", []) if "level" in h]
    tests = [{k: t.get(k) for k in ("test", "status", "code", "detail") if t.get(k) is not None}
             for t in gate.get("tests", [])]
    return {"system": cfg.get("system"), "node": node, "node_name": NODE_NAMES[node], "gate": GATE_OF[node],
            "code": gate.get("code"), "detail": gate.get("detail", ""), "tests": tests,
            "options": [{"id": o["id"], "text": o.get("text", "")} for o in options],
            "history": hist or "nothing yet", "attempts": state.get("attempts", {}).get(node, 0),
            "max_retry": cfg["retry"]["max_per_node"]}


def _spec_from_state(state: dict) -> dict | None:
    meta = state.get("run_meta") or {}
    if meta.get("llm_spec"):
        return dict(meta["llm_spec"])
    llm = state["config"].get("llm") or {}
    if llm.get("enabled") and llm.get("provider"):
        return {k: v for k, v in llm.items() if k != "enabled"}
    return None


def bare_system(system: str) -> str:
    """Prompt variant 'bare': the system prompt without its Guidance line (the gate's fix knowledge)."""
    return "\n".join(line for line in system.splitlines() if not line.startswith("Guidance:"))


def make_subagent(transport=None, calls_log: Path | None = None):
    """subagent(node, gate, options, state) -> {"id", "reason", "status", "llm": meta} or {"status": why-not}.
    recover() applies the id only if it is on the menu, and writes the outcome once to the audit log."""
    from . import prompts

    def subagent(node: str, gate: dict, options: list[dict], state: dict) -> dict:
        spec = _spec_from_state(state)
        if not spec:
            return {"status": "off (llm disabled)"}
        from .state import GATE_OF
        shown = list(options)
        if spec.get("shuffle_options"):
            seed = f"{spec.get('option_order_seed', 0)}:{state.get('thread_id')}:{node}:{gate.get('code')}:" \
                   f"{state.get('attempts', {}).get(node, 0)}"
            random.Random(seed).shuffle(shown)
        values = subagent_values(node, gate, shown, state)
        p = prompts.render(f"subagent_{GATE_OF[node]}", **values)
        if spec.get("prompt_variant", "guided") == "bare":
            p["system"] = bare_system(p["system"])
        if spec["provider"] == "fake" and "fake_script" in spec:      # k-th sub-agent call of this run
            k = sum(1 for h in state.get("history", [])
                    if "subagent" in h and not str(h["subagent"]).startswith(("not asked", "ablated", "off")))
            sc = spec["fake_script"]
            spec["fake_answer"] = sc[k] if k < len(sc) else None
        ctx = {**{k: v for k, v in values.items() if k != "options"},
               "fault_id": (state.get("run_meta") or {}).get("fault_id")}
        res = llm_choose(spec, p["system"], p["user"], [o["id"] for o in shown], transport=transport, context=ctx)
        res["option_order"] = [o["id"] for o in shown]
        log = calls_log or (Path(state["_calls_log"]) if state.get("_calls_log") else None)
        if log:
            with open(log, "a") as fh:
                fh.write(json.dumps({"node": node, "gate": GATE_OF[node], "code": gate.get("code"),
                                     "prompt_id": f"subagent_{GATE_OF[node]}", "prompt_values": values,
                                     "prompt_variant": spec.get("prompt_variant", "guided"),
                                     "user_template": prompts.load(f"subagent_{GATE_OF[node]}")["user"],
                                     "menu": [{"id": o["id"], "text": o.get("text", "")} for o in options],
                                     "system_prompt": p["system"], "user_prompt": p["user"], **res}, default=str) + "\n")
        out = {"status": res["status"], "llm": {k: v for k, v in res.items() if k not in ("raw_text",)}}
        if res["valid"]:
            out.update({"id": res["id"], "reason": res["reason"]})
        elif res.get("answered_id"):
            out["invalid_id"] = res["answered_id"]
        return out

    return subagent


# ---- CLI: list models, ping ------------------------------------------------------------------------------------
def list_models(provider: str, transport=None) -> list[str]:
    transport = transport or globals()["http_json"]
    spec = {"provider": provider}
    key = _key(spec)
    if key is None:
        raise SystemExit(f"no {KEY_ENV[provider]} in environment")
    if provider == "anthropic":
        st, r = transport("GET", "https://api.anthropic.com/v1/models?limit=100",
                          {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}, None, 60)
        ids = [m["id"] for m in r.get("data", [])]
    elif provider == "openai":
        st, r = transport("GET", f"{URL['openai']}/models", {"authorization": f"Bearer {key}"}, None, 60)
        ids = sorted(m["id"] for m in r.get("data", []))
    else:
        st, r = transport("GET", f"{URL['google']}/models?pageSize=1000", {"x-goog-api-key": key}, None, 60)
        ids = [m["name"].split("/", 1)[1] for m in r.get("models", [])
               if "generateContent" in m.get("supportedGenerationMethods", [])]
    if st != 200:
        raise SystemExit(f"{provider}: http {st}: {str(r)[:300]}")
    return ids


PING_SYSTEM = "You are a test harness. Choose the option the user names."
PING_USER = 'Options (choose one id):\n[{"id": "alpha", "text": "first"}, {"id": "beta", "text": "second"}, ' \
            '{"id": "stop", "text": "stop"}]\n\nChoose "beta".'


CHECKS_DIR = Path(__file__).resolve().parents[1] / "results" / "llm_checks"


def _ping_line(n, r):
    return (f"{n:24s} {r['status']:28s} id={r.get('answered_id')!s:6s} version={r.get('model_version')} "
            f"tokens={r.get('tokens_in')}/{r.get('tokens_out')}"
            f"{'+' + str(r['tokens_reasoning']) if r.get('tokens_reasoning') else ''} "
            f"{r.get('latency_s')} s{'  ' + str(r.get('error')) if r.get('error') else ''}")


def _ping(models: dict, names: list[str], mode: str | None) -> list[dict]:
    rows = []
    for n in names:
        spec = {**models[n]}
        if mode:
            spec["mode"] = mode
        if not spec.get("model"):
            rows.append({"name": n, "provider": spec["provider"], "mode": spec.get("mode"), "status": "skipped: no model id pinned"})
            print(f"{n:24s} skipped: no model id pinned yet")
            continue
        r = llm_choose(spec, PING_SYSTEM, PING_USER, ["alpha", "beta", "stop"])
        r["expected_id"], r["correct"] = "beta", r.get("answered_id") == "beta"
        rows.append(r)
        print(_ping_line(n, r))
    return rows


def _out_dir(base: Path | None = None) -> Path:
    from datetime import datetime, timezone
    d = (base or CHECKS_DIR) / datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_list(d: Path, provider: str, ids: list[str] | None, err: str | None):
    (d / f"models_{provider}.txt").write_text("\n".join(ids or []) + ("\n" if ids else ""))
    return {"provider": provider, "n": len(ids or []), "error": err}


def _save_ping(d: Path, mode: str, rows: list[dict]):
    with open(d / f"ping_{mode}.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _summary(d: Path, lists: list[dict], pings: dict, models_file: str):
    import platform
    L = [f"# LLM check {d.name}", "", f"- models file: `{models_file}` (sha256 {hashlib.sha256(Path(models_file).read_bytes()).hexdigest()[:16]})",
         f"- python {platform.python_version()}; dummy prompt only (no project data); expected answer `beta`", ""]
    if lists:
        L += ["## Models listed by each account", "", "| provider | ids | file | error |", "|---|---|---|---|"]
        L += [f"| {x['provider']} | {x['n']} | `models_{x['provider']}.txt` | {x['error'] or ''} |" for x in lists]
        L.append("")
    for mode, rows in pings.items():
        L += [f"## Ping, mode {mode} (`ping_{mode}.jsonl`)", "",
              "| name | provider | model | returned version | status | answer | tokens in / out (+reasoning) | latency (s) |",
              "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            tok = "" if r.get("tokens_in") is None else f"{r['tokens_in']} / {r.get('tokens_out')}" + (
                f" (+{r['tokens_reasoning']})" if r.get("tokens_reasoning") else "")
            L.append(f"| {r.get('name')} | {r.get('provider')} | {r.get('model') or ''} | {r.get('model_version') or ''} | "
                     f"{r['status']} | {r.get('answered_id') or ''} | {tok} | {r.get('latency_s', '')} |")
        ok = [r for r in rows if r.get("correct")]
        L += ["", f"{len(ok)} of {sum(1 for r in rows if 'latency_s' in r)} called models answered `beta`.", ""]
    (d / "summary.md").write_text("\n".join(L))
    return d / "summary.md"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="list all three providers + ping all models in both modes; save")
    ap.add_argument("--list", choices=["anthropic", "openai", "google"])
    ap.add_argument("--ping", help="model name from eval/models.yaml, or 'all'")
    ap.add_argument("--models", default=str(MODELS_YAML))
    ap.add_argument("--mode", choices=["constrained", "free"])
    ap.add_argument("--save", action="store_true", help="also save --list / --ping output under results/llm_checks/")
    a = ap.parse_args(argv)
    if a.check:
        d = _out_dir()
        lists = []
        for prov in ("anthropic", "openai", "google"):
            try:
                ids, err = list_models(prov), None
            except SystemExit as e:
                ids, err = None, str(e)
            print(f"{prov}: {len(ids or [])} models" + (f"  ({err})" if err else ""))
            lists.append(_save_list(d, prov, ids, err))
        models = load_models(a.models)
        pings = {}
        for mode in ("constrained", "free"):
            print(f"-- ping, mode {mode}")
            pings[mode] = _ping(models, list(models), mode)
            _save_ping(d, mode, pings[mode])
        print(f"\nsaved: {_summary(d, lists, pings, a.models)}")
        return
    if a.list:
        ids = list_models(a.list)
        print("\n".join(ids))
        if a.save:
            d = _out_dir()
            _summary(d, [_save_list(d, a.list, ids, None)], {}, a.models)
            print(f"\nsaved: {d}")
        return
    if a.ping:
        models = load_models(a.models)
        names = list(models) if a.ping == "all" else [a.ping]
        rows = _ping(models, names, a.mode)
        if a.save:
            d = _out_dir()
            mode = a.mode or "as_configured"
            _save_ping(d, mode, rows)
            _summary(d, [], {mode: rows}, a.models)
            print(f"\nsaved: {d}")


if __name__ == "__main__":
    main()
