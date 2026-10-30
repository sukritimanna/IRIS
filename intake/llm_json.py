"""One structured-output call for the intake: the same provider adapters as the sub-agents (iris_agent/llm.py), with
the draft-intent schema in place of the option-id schema. Keys only from the environment; never logged."""
from __future__ import annotations

import hashlib
import time

from iris_agent import llm as L

from .schema import gemini_schema, json_schema


def _swap(prov, body):
    if prov == "anthropic":
        body["output_config"] = {"format": {"type": "json_schema", "schema": json_schema()}}
    elif prov == "openai":
        if "text" in body:
            body["text"] = {"format": {"type": "json_schema", "name": "intent", "strict": True, "schema": json_schema()}}
        else:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "intent", "strict": True, "schema": json_schema()}}
    elif prov == "google":
        body["generationConfig"]["responseMimeType"] = "application/json"
        body["generationConfig"]["responseSchema"] = gemini_schema()
    return body


def llm_json(spec: dict, system: str, user: str, *, transport=None) -> dict:
    transport = transport or L.http_json
    prov = spec["provider"]
    meta = {"provider": prov, "model": spec.get("model"), "name": spec.get("name"),
            "prompt_sha256": hashlib.sha256((system + "\n" + user).encode()).hexdigest()[:16]}
    t0 = time.monotonic()
    key = L._key(spec)
    if key is None:
        return {**meta, "obj": None, "valid": False, "error": "missing key", "latency_s": 0.0}
    build, parse = L.ADAPTERS[prov]
    url, headers, body = build(spec, system, user, [], True, key)
    body = _swap(prov, body)
    retries, status, r = 0, None, {}
    while True:
        try:
            status, r = transport("POST", url, headers, body, float(spec.get("timeout_s", 180)))
        except Exception as exc:
            status, r = None, {"error": {"message": f"{type(exc).__name__}: {exc}"}}
        if (status is None or status in L.RETRY_STATUS) and retries < 3:
            retries += 1
            time.sleep(min(30.0, 2.0 ** retries) if transport is L._REAL_HTTP else 0)
            continue
        break
    del key, headers
    if status != 200:
        msg = str((r.get("error") or {}).get("message", r))[:300] if isinstance(r, dict) else str(r)[:300]
        return {**meta, "obj": None, "valid": False, "error": f"http {status}: {msg}",
                "latency_s": round(time.monotonic() - t0, 3), "transport_retries": retries}
    f = parse(r, True)
    obj = f.get("obj") if isinstance(f.get("obj"), dict) else None
    return {**meta, "obj": obj, "valid": bool(obj) and not f.get("truncated"),
            "error": None if obj and not f.get("truncated") else ("truncated" if f.get("truncated") else "unparseable"),
            "model_version": f.get("model_version"), "tokens_in": f.get("tokens_in"), "tokens_out": f.get("tokens_out"),
            "tokens_reasoning": f.get("tokens_reasoning"),
            "cost_usd": L._cost(spec, f.get("tokens_in"), f.get("tokens_out"), f.get("tokens_reasoning")),
            "latency_s": round(time.monotonic() - t0, 3), "transport_retries": retries, "raw_text": (f.get("text") or "")[:3000]}
