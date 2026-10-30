#!/usr/bin/env bash
# ON CARBON. Rehearsal without submitting: the chat runs f0 (Claude intake) -> Materials Project fetch -> f1 (live
# FINDSYM + ISODISTORT) -> f2 -> f3 writes the VASP inputs; then the executor in dry-run writes POTCAR + the PBS
# scripts and nothing is submitted. Inspect test_runs/<thread>/f3_jobs/live/r0_p0.sh and live_runs/<campaign>/<path>/L00/.
#   bash 02_validate/dry_run.sh "<request>" [campaign]
set -e
source ~/.iris_env; source "$(conda info --base)/etc/profile.d/conda.sh"; conda activate iris
REQ="${1:?request text}"; CAMP="${2:-rehearsal_$(date +%Y%m%d)}"
cd "$IRIS_AGENT" && python -m iris_agent.chat --campaign "$CAMP" --llm claude-sonnet --request "$REQ" --yes --dry-run
