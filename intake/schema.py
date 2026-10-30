"""The draft-intent JSON schema the model must answer through, and the prompt (both frozen with the requests).

Every field is an id from intake/library.py or null; the only number is the budget. No DFT parameter exists in the
schema, so the model cannot set one.
"""
from __future__ import annotations

from .library import ANALYSES, OUTPUTS, STRAIN_POLICIES, SYSTEMS, TRANSITIONS, profiles

CLARIFY_FIELDS = ["system", "transition", "analysis", "strain_policy", "system_profile", "budget", "outputs"]


def _enum_or_null(values):
    return {"anyOf": [{"type": "string", "enum": list(values)}, {"type": "null"}]}


def json_schema() -> dict:
    """Standard JSON schema (Anthropic output_config, OpenAI strict json_schema)."""
    props = {
        "system": _enum_or_null(list(SYSTEMS) + ["new"]),
        "formula": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "parent_sg": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "child_sg": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "transition": _enum_or_null(TRANSITIONS),
        "analysis": _enum_or_null(ANALYSES),
        "strain_policy": _enum_or_null(STRAIN_POLICIES),
        "system_profile": _enum_or_null(profiles()),
        "budget": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "outputs": {"type": "array", "items": {"type": "string", "enum": list(OUTPUTS)}},
        "clarify_field": _enum_or_null(CLARIFY_FIELDS),
        "question": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "out_of_scope": {"type": "boolean"},
        "out_of_scope_reason": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    }
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def gemini_schema() -> dict:
    """Gemini responseSchema (OpenAPI subset: upper-case types, nullable instead of a null branch)."""
    def conv(p):
        if "anyOf" in p:
            base = next(x for x in p["anyOf"] if x.get("type") != "null")
            out = conv(base)
            out["nullable"] = True
            return out
        t = p["type"].upper()
        out = {"type": t}
        if "enum" in p:
            out["enum"] = p["enum"]
        if t == "ARRAY":
            out["items"] = conv(p["items"])
        return out
    s = json_schema()
    props = {k: conv(v) for k, v in s["properties"].items()}
    return {"type": "OBJECT", "properties": props, "required": list(props), "propertyOrdering": list(props)}


def system_prompt() -> str:
    L = ["You are the intake step (f0) of IRIS, a workflow that maps symmetry-mode energy landscapes from stored DFT "
         "campaigns. Turn the user's request into a draft intent by choosing ids from the tables below.",
         "",
         "Rules:",
         "- Fill a field only when the request states or clearly implies it; otherwise return null (code then uses the "
         "policy default of the chosen system and analysis).",
         "- You never set DFT parameters (cutoffs, k-points, U, magnetic moments, functionals) or any number other than "
         "the run budget. Choose only existing system profiles and policy options.",
         "- If a required choice (system, transition, or what to compute) cannot be decided from the request, set "
         "clarify_field to that field and write ONE short question; do not guess.",
         "- If the request cannot be served by these tables (no listed transition, an engine other than the stored VASP "
         "DFT campaigns, molecular dynamics, ...), set out_of_scope = true and give the reason.",
         "- parent_sg / child_sg: the space-group numbers of the parent and child, when stated or implied.",
         "- A material without a stored campaign: system = \"new\", its formula, parent_sg / child_sg and the analysis. "
         "Choose a system profile only if one exists for that same material; never use the profile of another "
         "material. Such a request needs new DFT; it is not out of scope.",
         "",
         "Systems:"]
    L += [f"  {k}: {v}" for k, v in SYSTEMS.items()] + ["  new: any other material (give its formula)"]
    L += ["", "Stored transitions (id: system, parent -> child):"]
    L += [f"  {k}: {v['system']}, #{v['parent_sg']} -> #{v['child_sg']}, {v['label']}" for k, v in TRANSITIONS.items()]
    L += ["", "Analyses:"] + [f"  {k}: {v}" for k, v in ANALYSES.items()]
    L += ["", "Strain policies:"] + [f"  {k}: {v}" for k, v in STRAIN_POLICIES.items()]
    L += ["", "System profiles (id: material, note):"] + [f"  {k}: {v['formula']}, {v['text']}" for k, v in profiles().items()]
    L += ["", "Outputs:"] + [f"  {k}: {v}" for k, v in OUTPUTS.items()]
    L += ["", "Answer only with the JSON object of the schema."]
    return "\n".join(L)


def user_prompt(text: str, attachments: list[str]) -> str:
    att = ("\nAttached: " + ", ".join(attachments)) if attachments else ""
    return f"Request: {text}{att}"
