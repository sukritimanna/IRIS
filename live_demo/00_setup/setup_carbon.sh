#!/usr/bin/env bash
# ON CARBON, once. Creates conda env 'iris' and installs the IRIS requirements + the live-mode extras. Touches nothing else.
set -e
source ~/.iris_env
source "$(conda info --base)/etc/profile.d/conda.sh"
conda env list | grep -qE "^iris[[:space:]]" || conda create -n iris python=3.11 -y
conda activate iris
pip install -r "$IRIS_AGENT/requirements.txt"
pip install requests pyyaml pytest                     # mp_fetch, configs, tests
pip install asciinema 2>/dev/null || true              # optional terminal recording inside tmux
mkdir -p "$IRIS_LIVE/recordings" "$IRIS_LIVE/archive"
python -c "import langgraph, pymatgen, spglib, scipy, yaml, requests; print('python env ok')"
echo "next: bash 00_setup/check_carbon.sh"
