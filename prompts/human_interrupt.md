---
id: human_interrupt
role: Message shown to the human when recover() escalates (not sent to an LLM)
used_by: iris_agent/recover.py interrupt() payload; printed by iris_agent/run.py
status: active (build step 1)
step: 1
inputs: [node, node_name, gate, code, detail, why_human, options, attempts, thread_id, config_path]
rules:
  - Reached when no rule applies (or it is used up), the sub-agent gives no valid option, or the node's retry budget is spent.
  - The human answers with one listed option, a config patch, or stop; the answer is written to the audit log.
output_schema:
  type: object
  description: "the resume value passed to run.py --resume"
  oneOf:
    - {required: [option], properties: {option: {type: string}}}
    - {required: [fix], properties: {fix: {type: object}}}
examples:
  - title: Missing child CIF (fault injection in tests/test_graph.py)
    input: |
      f0 Intake failed G0 with CIF_MISSING: child CIF not found: demo/cssni3/structures/NOPE.cif
    output:
      fix: {config_patch: {paths: {child_cif: demo/cssni3/structures/orthorhombic_mp-568570_sg62.cif}}}
---
What the person running IRIS sees when the workflow pauses for a decision, and how to answer.

## system
(not an LLM prompt — this text is shown to the human)

## user
IRIS paused at {node} {node_name}: gate {gate} failed with {code}.
Detail: {detail}
Why this came to you: {why_human}
Retries used on {node}: {attempts}

Options:
{options}

Answer with one of:
  python -m iris_agent.run --config {config_path} --thread {thread_id} --resume '{{"option": "<id>"}}'
  python -m iris_agent.run --config {config_path} --thread {thread_id} --resume '{{"fix": {{...}}}}'
Choosing "stop" ends the run; the audit log keeps the full trail.
