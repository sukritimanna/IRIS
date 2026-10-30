#!/usr/bin/env bash
# ON CARBON, right after the recording: freeze what was produced. sha256 of every file of the campaign and the
# thread folders -> MANIFEST.sha256 next to them. Nothing is moved or deleted.
#   bash 03_record/stop_and_hash.sh <campaign>
source ~/.iris_env
CAMP="${1:?campaign}"
cd "$IRIS_AGENT"
OUT="live_runs/$CAMP/MANIFEST.sha256"
{ find "live_runs/$CAMP" -type f ! -name MANIFEST.sha256 -print0; find test_runs -maxdepth 1 -type d -name "*_live" -print0 | xargs -0 -I{} find {} -type f -print0; } | xargs -0 sha256sum | sort -k2 > "$OUT"
echo "$(wc -l < "$OUT") files hashed -> $OUT"; sha256sum "$OUT"
