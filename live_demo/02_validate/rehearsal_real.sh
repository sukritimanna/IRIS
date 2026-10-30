#!/usr/bin/env bash
# ON CARBON. One real, unrecorded end-to-end run of path T1 (submits VASP). Same command as the recording.
#   bash 02_validate/rehearsal_real.sh "<request>" [campaign]
source ~/.iris_env; source "$(conda info --base)/etc/profile.d/conda.sh"; conda activate iris
REQ="${1:?request text}"; CAMP="${2:-rehearsal_$(date +%Y%m%d)}"
cd "$IRIS_AGENT" && python -m iris_agent.chat --campaign "$CAMP" --llm claude-sonnet --request "$REQ" --executor --yes
