"""Prompt gallery loader: every LLM prompt IRIS can send lives in prompts/<id>.md as YAML front
matter + a system section + a user template. The same files build PROMPT_GALLERY.md
(`python -m iris_agent.prompts --gallery`).

Templates use {placeholders} (a bare identifier in braces); any other brace text, e.g. a JSON example
{"id": ..., "reason": ...}, is left as written. render() fails loudly on a missing value so a prompt can
never be sent half-filled.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
_FM = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)
_SECTION = re.compile(r"^## (system|user)\s*$", re.M)
REQUIRED_META = {"id", "role", "used_by", "status", "step", "inputs", "output_schema", "rules"}


def load(pid: str, prompt_dir: Path = PROMPT_DIR) -> dict:
    text = (prompt_dir / f"{pid}.md").read_text()
    m = _FM.match(text)
    if not m:
        raise ValueError(f"{pid}: missing YAML front matter")
    meta = yaml.safe_load(m.group(1))
    parts = _SECTION.split(m.group(2))
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    missing = REQUIRED_META - set(meta)
    if missing or set(sections) != {"system", "user"}:
        raise ValueError(f"{pid}: missing {sorted(missing)} or sections {sorted(sections)}")
    return {**meta, "system": sections["system"], "user": sections["user"],
            "preamble": parts[0].strip()}


def all_prompts(prompt_dir: Path = PROMPT_DIR) -> list[dict]:
    return [load(p.stem, prompt_dir) for p in sorted(prompt_dir.glob("*.md"))]


_PH = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def placeholders(template: str) -> set[str]:
    return set(_PH.findall(template))


_TOK = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _fill(template: str, v: dict) -> str:
    """One pass over the template: {{ / }} -> literal braces (str.format escapes), {name} -> value; inserted
    values are never re-scanned, other brace text is kept."""
    def sub(m):
        t = m.group(0)
        if t == "{{":
            return "{"
        if t == "}}":
            return "}"
        return str(v[m.group(1)]) if m.group(1) in v else t
    return _TOK.sub(sub, template)


def render(pid: str, **values) -> dict:
    p = load(pid)
    need = placeholders(p["user"]) | placeholders(p["system"])
    missing = need - set(values)
    if missing:
        raise KeyError(f"{pid}: missing values {sorted(missing)}")
    v = {k: (json.dumps(x, indent=1) if isinstance(x, (dict, list)) else x) for k, x in values.items()}
    return {"system": _fill(p["system"], v), "user": _fill(p["user"], v),
            "output_schema": p["output_schema"]}


def build_gallery(out: Path, prompt_dir: Path = PROMPT_DIR) -> Path:
    ps = all_prompts(prompt_dir)
    lines = ["# IRIS prompt gallery", "",
             "Every prompt the IRIS graph can send to an LLM, generated from `prompts/*.md` by "
             "`python -m iris_agent.prompts --gallery`. Do not edit by hand.", "",
             "The LLM never computes, never decides pass/fail, never routes and never writes numbers: "
             "each prompt returns one choice from a fixed list (or a config that the validator then checks).",
             "", "| id | role | used by | step | status |", "|---|---|---|---|---|"]
    for p in ps:
        lines.append(f"| [{p['id']}](#{p['id']}) | {p['role']} | {p['used_by']} | {p['step']} | {p['status']} |")
    for p in ps:
        lines += ["", "---", "", f"## {p['id']}", "", p.get("preamble", ""), "",
                  f"**Role:** {p['role']}  ", f"**Used by:** {p['used_by']}  ",
                  f"**Introduced in build step:** {p['step']}  ", f"**Status:** {p['status']}", "",
                  "**Inputs:** " + ", ".join(f"`{i}`" for i in p["inputs"]), "",
                  "**Rules the prompt enforces:**", *[f"- {r}" for r in p["rules"]], "",
                  "**Output schema:**", "", "```json", json.dumps(p["output_schema"], indent=1), "```", "",
                  "**System prompt:**", "", "```text", p["system"], "```", "",
                  "**User template:**", "", "```text", p["user"], "```"]
        for ex in p.get("examples", []) or []:
            lines += ["", f"**Example — {ex['title']}:**", "", "```text", ex["input"].strip(), "```",
                      "", "Expected output:", "", "```json", json.dumps(ex["output"], indent=1), "```"]
    out.write_text("\n".join(lines).rstrip() + "\n")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gallery", action="store_true")
    a = ap.parse_args()
    if a.gallery:
        print(build_gallery(PROMPT_DIR.parent / "PROMPT_GALLERY.md"))
