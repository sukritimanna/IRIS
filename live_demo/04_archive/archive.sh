#!/usr/bin/env bash
# ON CARBON. One tarball of the demo: the campaign (VASP inputs/outputs, energies, ISODISTORT raw responses),
# the thread folders (audit.jsonl, iris.sqlite, chat_transcript.md, f3_jobs/, llm_calls.jsonl), the live inputs
# (MP CIFs + provenance) and the config template. Copies only.
#   bash 04_archive/archive.sh <campaign>   ->  $IRIS_LIVE/archive/iris_live_<campaign>_<date>.tar.gz
source ~/.iris_env
CAMP="${1:?campaign}"
cd "$IRIS_AGENT"
T="$IRIS_LIVE/archive/iris_live_${CAMP}_$(date +%Y%m%d_%H%M).tar.gz"
tar czf "$T" "live_runs/$CAMP" "live_inputs/$CAMP" configs/live/_template_live.yaml recovery_live.yaml $(ls -d test_runs/*_live 2>/dev/null)
sha256sum "$T" | tee "$T.sha256"
echo "copy to the Mac:  scp carbon:$T ."
