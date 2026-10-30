#!/usr/bin/env bash
# ON CARBON. Every precondition of the live demo, one line each: PASS / FAIL. Read-only (writes only to /tmp and
# the pytest tmp dirs). Run it after setup, again the morning of the recording.
source ~/.iris_env 2>/dev/null || { echo "FAIL  ~/.iris_env missing (copy 00_setup/iris_env.template)"; exit 1; }
source "$(conda info --base)/etc/profile.d/conda.sh" && conda activate iris 2>/dev/null || { echo "FAIL  conda env iris"; exit 1; }
ok(){ echo "PASS  $1"; }; bad(){ echo "FAIL  $1"; FAILS=$((FAILS+1)); }; FAILS=0
[ -n "$ANTHROPIC_API_KEY" ] && ok "ANTHROPIC_API_KEY set" || bad "ANTHROPIC_API_KEY empty in ~/.iris_env"
[ -n "$MP_API_KEY" ] && ok "MP_API_KEY set" || bad "MP_API_KEY empty in ~/.iris_env"
[ -f "$IRIS_AGENT/iris_agent/live_executor.py" ] && ok "live build applied in $IRIS_AGENT" || bad "live build not applied (01_patch/apply_patch.sh)"
[ -d "$IRIS_REPO/demo/staged_walkthrough" ] && ok "demo/staged_walkthrough present" || bad "demo/staged_walkthrough missing in $IRIS_REPO"
( cd "$IRIS_REPO" && python -c "import iris.lib.isodistort, iris.lib.findsym, iris.perovskite.structures" 2>/dev/null ) && ok "iris/ package imports (live ISODISTORT + FINDSYM)" || bad "iris.lib / iris.perovskite not importable from $IRIS_REPO (f1 live needs them)"
for h in api.anthropic.com iso.byu.edu api.materialsproject.org; do
  curl -s -o /dev/null -m 15 -w "%{http_code}" "https://$h/" | grep -qE "^[2345]" && ok "HTTPS to $h" || bad "no HTTPS to $h from this login node"
done
module purge; module load impi/2019/2019.Update.9 intel/19/19.1.3 hdf5/1.10/intel-19/1.10.8-3; module load --auto --silent vasp6/6.3 2>/dev/null && ok "modules load" || bad "module load failed"
command -v vasp_std >/dev/null && ok "vasp_std on PATH after module load" || bad "vasp_std not found"
command -v qsub >/dev/null && command -v qstat >/dev/null && ok "qsub/qstat" || bad "qsub/qstat missing"
qstat -u "$USER" >/dev/null 2>&1 && ok "qstat -u \$USER works" || bad "qstat -u \$USER fails"
for s in Ba Ti O; do [ -f "$IRIS_POTCAR/$s/POTCAR" ] && ok "POTCAR $s ($(grep -m1 TITEL $IRIS_POTCAR/$s/POTCAR | awk '{print $4}'))" || bad "POTCAR $IRIS_POTCAR/$s/POTCAR missing (writePotcar layout: <dir>/<Element>/POTCAR)"; done
grep -q "potcar_dir: $IRIS_POTCAR" "$IRIS_AGENT/configs/live/_template_live.yaml" && ok "template potcar_dir = \$IRIS_POTCAR" || bad "edit configs/live/_template_live.yaml: potcar_dir -> $IRIS_POTCAR"
grep -q "EDIT" "$IRIS_AGENT/configs/live/_template_live.yaml" && bad "configs/live/_template_live.yaml still has an EDIT marker (the PBS nodes line)" || ok "template has no EDIT markers"
command -v tmux >/dev/null && ok "tmux" || bad "tmux missing (module load tmux?)"
command -v asciinema >/dev/null && ok "asciinema (optional)" || echo "note  asciinema not installed (optional; the Mac records the screen anyway)"
( cd "$IRIS_AGENT" && python -m pytest -q tests/test_live_mode.py >/tmp/iris_live_tests.log 2>&1 ) && ok "tests/test_live_mode.py (fake scheduler, fake VASP)" || bad "tests/test_live_mode.py failed: see /tmp/iris_live_tests.log"
( cd "$IRIS_AGENT" && python -m pytest -q tests >/tmp/iris_tests.log 2>&1 ) && ok "full IRIS test suite unchanged" || bad "IRIS test suite: see /tmp/iris_tests.log"
df -h "$IRIS_LIVE" | tail -1 | awk '{print "note  disk at " $6 ": " $4 " free"}'
echo; [ $FAILS -eq 0 ] && echo "ALL CHECKS PASS" || echo "$FAILS check(s) failed"
