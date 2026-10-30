#!/usr/bin/env bash
# ON CARBON. Opens the tmux session the Mac records: left pane = IRIS chat, right pane = executor log + queue.
#   bash 03_record/start_demo.sh <campaign>          (then: tmux attach -t iris)
# The chat is started by YOU in the left pane (so the request is typed on camera):
#   python -m iris_agent.chat --campaign <campaign> --llm claude-sonnet --executor [--network]
source ~/.iris_env
CAMP="${1:?campaign name, e.g. batio3_$(date +%Y%m%d)}"
tmux kill-session -t iris 2>/dev/null
tmux new-session -d -s iris -x 200 -y 50 -c "$IRIS_AGENT"
tmux send-keys -t iris "source ~/.iris_env && source \$(conda info --base)/etc/profile.d/conda.sh && conda activate iris && clear" C-m
tmux split-window -h -t iris -c "$IRIS_AGENT"
tmux send-keys -t iris:0.1 "source ~/.iris_env && source \$(conda info --base)/etc/profile.d/conda.sh && conda activate iris && clear && watch -n 15 'qstat -u \$USER; echo; tail -n 12 \$(ls -t test_runs/*/f3_jobs/live_executor.log 2>/dev/null | head -1) 2>/dev/null'" C-m
tmux select-pane -t iris:0.0
tmux resize-pane -t iris:0.0 -x 120
echo "tmux session 'iris' ready. On the Mac: ssh carbon -t 'tmux attach -t iris'  (full-screen the terminal, start QuickTime screen recording, then type the chat command in the left pane)"
echo "campaign folder: $IRIS_AGENT/live_runs/$CAMP"
