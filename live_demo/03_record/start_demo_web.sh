#!/usr/bin/env bash
# ON CARBON. The browser version of the demo: IRIS web chat on localhost:8765 (login node), executor started by it.
#   bash 03_record/start_demo_web.sh <campaign> [--mock] [--n-points 4 --part-size 4] [--network]
#   --mock: rehearsal — fake VASP/PBS (tests/live_fakes), everything else real; the page shows a MOCK badge
# Then on the Mac:   ssh -L 8765:localhost:8765 carbon      (keep that ssh open)
#                    open http://localhost:8765 in Chrome/Safari, full-screen it, start the screen photos (capture/snap_mac.sh)
# Type the request in the page; answer "run it? [y/N]" with y in the same box; expert menus appear as buttons.
# The page is the same pipeline as the terminal chat: every line also goes to test_runs/<thread>/chat_transcript.md.
source ~/.iris_env; source "$(conda info --base)/etc/profile.d/conda.sh"; conda activate iris
CAMP="${1:?campaign name}"; shift
cd "$IRIS_AGENT" && echo "python: $(which python)" && exec python -m iris_agent.web --campaign "$CAMP" --llm claude-sonnet --executor --port 8765 "$@"
