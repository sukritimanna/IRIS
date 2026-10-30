# Manual checks on Carbon — paste one block at a time, compare with "expect"

Do these in order in a plain ssh session (not yet in tmux). Each block is independent; stop at the first
"expect" that does not match and send me the output. `check_carbon.sh` does the same in one go afterwards.

## 0. Keys
See API_KEYS_SETUP.md: Materials Project key, Anthropic key, `~/.iris_env`.

## A. Files and environment

```bash
# A1 keys/paths file
source ~/.iris_env && echo "repo=$IRIS_REPO agent=$IRIS_AGENT potcar=$IRIS_POTCAR" && [ -n "$ANTHROPIC_API_KEY" ] && [ -n "$MP_API_KEY" ] && echo keys set
```
expect: the three paths, then `keys set` (the keys themselves are never printed).

```bash
# A2 the repo has the walkthrough AND the iris package
ls $IRIS_REPO/demo/staged_walkthrough/step3_isodistort.py $IRIS_REPO/iris/lib/isodistort.py $IRIS_REPO/iris/lib/findsym.py $IRIS_REPO/iris/perovskite/structures.py
```
expect: four paths listed, no "No such file".

```bash
# A3 the live build is applied (dry run first, then --go)
bash 01_patch/apply_patch.sh $IRIS_AGENT
```
expect: `18 new, 6 modified — dry run`. Then `bash 01_patch/apply_patch.sh $IRIS_AGENT --go` → `applied (backups *.pre_live)`.
Run it a second time: expect `0 new, 0 modified`.

```bash
# A4 python env
source $(conda info --base)/etc/profile.d/conda.sh && conda activate iris && python -c "import langgraph, pymatgen, spglib, scipy, yaml, requests, PIL; print('ok')"
cd $IRIS_REPO && python -c "import iris.lib.isodistort, iris.lib.findsym, iris.perovskite.structures; print('iris ok')"
```
expect: `ok` and `iris ok`. (Missing module → `pip install <name>`; a missing `iris` dependency → tell me the module name.)

## B. Network from the login node

```bash
for h in api.anthropic.com iso.byu.edu api.materialsproject.org; do printf "%-28s " $h; curl -s -o /dev/null -m 15 -w "%{http_code}\n" https://$h/; done
```
expect: three HTTP codes (200/301/403/404 are all fine — it means the host is reachable). `000` = blocked; tell me which.

```bash
# B2 the three services really answer (one cheap call each)
curl -s -m 20 -H "X-API-KEY: $MP_API_KEY" "https://api.materialsproject.org/materials/summary/?formula=BaTiO3&spacegroup_number=221&_fields=material_id,energy_above_hull&_limit=3" | head -c 400; echo
curl -s -m 20 https://api.anthropic.com/v1/models -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" | head -c 200; echo
```
expect: a JSON with `mp-…` ids and `energy_above_hull`; a JSON model list (not `authentication_error`).

## C. VASP, PBS, POTCAR

```bash
module purge; module load impi/2019/2019.Update.9 intel/19/19.1.3 hdf5/1.10/intel-19/1.10.8-3; module load --auto --silent vasp6/6.3 && which vasp_std && which qsub qstat && qstat -u $USER | head -3
for s in Ba Ti O; do grep -m1 TITEL $IRIS_POTCAR/$s/POTCAR; done
```
expect: a path to `vasp_std`, paths to `qsub`/`qstat`, the queue header, and three `TITEL = PAW_PBE …` lines.

```bash
# C2 the template is edited (no EDIT markers) and names the right POTCAR dir
grep -n "EDIT\|potcar_dir\|nodes=\|walltime" $IRIS_AGENT/configs/live/_template_live.yaml
```
expect: no line containing `EDIT`; `potcar_dir:` equal to `$IRIS_POTCAR`; your usual `#PBS -l nodes=…` line.

## D. IRIS itself (no VASP, no network, ~10 s)

```bash
cd $IRIS_AGENT && python -m pytest -q tests/test_live_mode.py && python -m pytest -q tests | tail -1
```
expect: `4 passed`, then `141 passed, 17 skipped` (your original 137 + 4).

```bash
# D2 the chat starts and the intake works (Claude call, no run)
cd $IRIS_AGENT && python -m iris_agent.chat --campaign check --llm claude-sonnet --request "Map the straight-line irrep path of BaTiO3 from cubic Pm-3m (221) to tetragonal P4mm (99), 10 points, PBEsol"
```
expect: `intake (claude-sonnet-5-5): system=new, formula=BaTiO3, parent_sg=221, child_sg=99, analysis=path, …`,
`verdict: needs_new_dft`, two `fetching …` lines with mp-ids (parent 5 atoms a≈4.0 Å; child 5 atoms, c/a ≈ 1.01),
`config written: …/test_runs/batio3_T1_221_99_live/config.yaml`, the `plan:` line, then `run it? [y/N]` → type **n**.
Keep the config: `cat test_runs/batio3_T1_221_99_live/config.yaml` and read it once end to end.

## E. One PBS job by hand (≈ 10–20 min queue + run) — validates the INCAR before IRIS submits anything

```bash
cd 02_validate/vasp_checks/vasp_static && bash make_potcar.sh && cat INCAR.PBEsol && qsub run_static.pbs
```
(edit `run_static.pbs` first with the same `#PBS` lines as the template.) expect after it finishes: `grep "free  energy" OUTCAR | tail -1`
gives a TOTEN near −40 eV for the 5-atom cell, `grep -c "DAV\|RMM" OSZICAR` well below NELM, wall time noted → that
time × 5 ≤ the template walltime.

## F. Live f₁ alone (FINDSYM + ISODISTORT, ≈ 1–3 min, nothing submitted)

```bash
cd $IRIS_AGENT && python -m iris_agent.chat --campaign check --llm claude-sonnet --request "<same request>" --yes --dry-run
```
expect: `G0 PASS 11/11`, `f1 Crystallographer starts` … `G1 (decomposition): PASS, 5/5 tests`, `G2 PASS 4/4`,
`f3 waiting for 2 of 2 job parts`, executor `DRY RUN would run: qsub …/r0_p0.sh`, then `DRY RUN: inputs in …`.
Then look at what f₁ got from the server and what f₃ wrote:

```bash
ls live_runs/check/T1_221-99__lin10/isodistort/demo/runs/*/step3_isodistort/04_raw_isodistort/
cat live_runs/check/T1_221-99__lin10/isodistort/demo/runs/*/step3_isodistort/03_data/displacive_modes.json
head -20 live_runs/check/T1_221-99__lin10/L05/POSCAR; cat live_runs/check/T1_221-99__lin10/L05/INCAR live_runs/check/T1_221-99__lin10/L05/KPOINTS
cat test_runs/batio3_T1_221_99_live/f3_jobs/live/r0_p0.sh
```
expect: `modes_details.txt`, `irreps.txt`, `tree.txt`, `full_movie.cif`, `mode_*.cif`; displacive modes with
`GM4-` as the large one (A_p ≈ 0.1–0.2 Å); POSCAR with Ba Ti O / 1 1 3; the template INCAR; `8 8 8`; a PBS script
with your header, the module line and ten `cd …/L0k` + `mpirun vasp_std > vasp.out` blocks (5 per script).
Clean up the dry run: `rm -r test_runs/batio3_T1_221_99_live live_runs/check live_inputs/check`.

## G. Short real run (4 points, one PBS job, ≈ 15–30 min), unrecorded or recorded as a trial

```bash
cd $IRIS_AGENT && python -m iris_agent.chat --campaign short --llm claude-sonnet --n-points 4 --part-size 4 --executor
```
expect the full sequence to `G6 … PASS` and `f6: 33 of 33 reported numbers re-derived and equal`, with
`profile dE(lambda)` of 4 values, the last one negative (P4mm below Pm-3m by ~10–30 meV/f.u. at PBEsol, straight
line, no relaxation). `cat test_runs/batio3_T1_221_99_live/chat_transcript.md` is the transcript.

## H. Full run = the recording (10 points, 2 PBS jobs per path, T1 then T2 then T3 `--network`)

See RUNBOOK_carbon.md §4. Start the snapshotter first (03_record/capture/README.md).
