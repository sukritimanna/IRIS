# Running IRIS live on an HPC cluster (the BaTiO₃ campaign of the paper)

This is the recipe a third party needs to reproduce the prospective BaTiO₃ run of the paper (main text Section 2.6;
Supplementary Section S13) on their own cluster, with PBS or Slurm. "Live" means that nothing stored is read: the
intake fetches the parent and child from the Materials Project, f₁ runs FINDSYM and ISODISTORT on the ISOTROPY
server, f₃ writes VASP inputs and submits them, and the same gates G₀–G₆ as in replay decide every hand-off.

## 1. What you need

| Requirement | Why | Notes |
|---|---|---|
| Python 3.11+ with `requirements.txt` | IRIS itself | `python -m venv iris-env && pip install -r requirements.txt` |
| VASP 6 and its PAW library | the DFT engine | licensed; the run used `vasp_std`, PAW `Ba_sv`, `Ti`, `O` (PBE set). IRIS writes POSCAR/INCAR/KPOINTS/POTCAR per frame and calls the command you put in `run.live.vasp_cmd` |
| A scheduler (PBS Pro/Torque or Slurm) | the executor submits one job per part of 5 frames | the job script is your own header (`run.live.job_header`) plus one VASP call per frame |
| `MP_API_KEY` | f₀ fetches structures from the Materials Project | free key from https://next-gen.materialsproject.org (profile → API) |
| `ANTHROPIC_API_KEY` (or OpenAI / Google key) | the intake model and the gate sub-agents | the run used Claude Sonnet 5.5 (`claude-sonnet` in `eval/models.yaml`); any model listed there works |
| Outbound HTTPS from the node that runs IRIS | Materials Project, ISOTROPY server (FINDSYM/ISODISTORT), the model API | the DFT nodes need no network |
| The `imhafo2` package (`iris/lib`, `demo/staged_walkthrough`) at `paths.repo_root` | FINDSYM/ISODISTORT clients, POTCAR and k-point writers, the system profiles | deposited with the data (Data availability); IRIS imports it read-only. Without it f₁ and f₃ cannot run |

Keys are read from the environment only (`llm.api_key_env`, `MP_API_KEY`); they never enter a config, a log or a
checkpoint (`tests/test_config_paths.py`, `tests/test_llm.py`). Put them in a file you `source`, mode 600, never in
the repository (`live_demo/00_setup/iris_env.template` is the pattern).

## 2. Configure the cluster once

Copy `configs/live/_template_live.yaml` (paths) and `configs/live/_template_plane_live.yaml` (planes) and edit
three blocks. Everything else is filled by the intake from the request and the fetched cells.

```yaml
run:
  live:
    submit_cmd: qsub                      # Slurm: "sbatch --parsable"  (the executor takes the FIRST token of stdout as the job id)
    queue_cmd: "qstat -u $USER"           # Slurm: "squeue -u $USER -h -o %i" (first token per line = job id; a part has ended when its id leaves the queue or its .done marker exists)
    poll_s: 30
    job_header: |                         # your scheduler header; {job_name} is replaced per part
      #!/bin/bash
      #PBS -A <project-id>                # Slurm: #SBATCH --account=... --nodes=1 --ntasks=32 --time=01:00:00 --job-name={job_name}
      #PBS -l nodes=1:ppn=32
      #PBS -l walltime=01:00:00
      #PBS -N {job_name}
      module load vasp6/6.3               # whatever loads VASP and MPI on your cluster
      NP=`wc -l < $PBS_NODEFILE`          # Slurm: NP=$SLURM_NTASKS
    vasp_cmd: mpirun -np $NP vasp_std
    potcar_dir: <your-potcar-library>     # <dir>/<Element>/POTCAR
    incar: {GGA: PE, PREC: Accurate, ENCUT: 600, EDIFF: 1.0e-7, ISMEAR: 0, SIGMA: 0.05, ISPIN: 1, NELM: 200, IBRION: -1, NSW: 0, LREAL: false, LWAVE: false, LCHARG: false}
    kspacing: 0.20                        # Γ-centred mesh, k_i = ceil(|b_i| / 0.20) from the λ = 0 cell
paths:
  repo_root: <where imhafo2 is>           # read only
  agent_root: <where this repository is>  # the only place IRIS writes
```

The paper's paths were run with `GGA: PE`; the plane template still carried `GGA: PS` (PBEsol at the PBE cell), as
the paper states. Check `incar` in both templates before you run.

Sanity checks before submitting anything (each takes seconds):

```bash
python -m iris_agent.check_env --configs configs/live                      # keys present (names only), repo_root readable, package versions
python -m pytest tests/test_live_mode.py -q                                # the executor against a fake scheduler (no VASP)
python -m iris_agent.chat --campaign trial --llm claude-sonnet --mock      # a full MOCK run: real intake, Materials Project, FINDSYM/ISODISTORT and gates; VASP and the scheduler replaced by tests/live_fakes
```

## 3. Run

Two processes: the chat (or the web page) that takes the request and runs the graph, and the executor that
submits and watches jobs. `--executor` starts the second from the first.

```bash
source ~/.iris_env
python -m iris_agent.web  --campaign batio3 --llm claude-sonnet --executor --port 8765     # browser page: chat left, graph/gates/jobs right
# or, in a terminal
python -m iris_agent.chat --campaign batio3 --llm claude-sonnet --executor --path-tag T1
```

Type the request as a sentence. The paper's rhombohedral path was asked for as

```
Map the straight-line irrep path of BaTiO3 from cubic Pm-3m (221) to rhombohedral R3m (160), 10 points, PBE
```

and the tetragonal (P4mm, 99) and orthorhombic (Amm2, 38) paths in the same form; the plane is asked for with
`--plane` (the `_template_plane_live.yaml` template: the (Pz, Px) plane of the polar mode at the clamped cubic
cell, 21 x 21 grid). Every request as typed is in the chat transcript of its run directory.

The chat shows the configuration the intake wrote and asks once for confirmation before anything is submitted;
that confirmation is the only human input of the paper's run. Each path is 10 frames in 2 jobs of 5; the plane is 66
symmetry-unique points in 14 jobs. Wall time in the paper: 6–11 min per run, 34 min for all four, dominated by the
queue.

## 4. What a run leaves behind

`test_runs/<thread>/`: `audit.jsonl` (every node, gate, fix, interrupt and job event with hashes), `iris.sqlite`
(the LangGraph checkpoint; a killed run continues with `--continue`), `chat_transcript.md`, `f3_jobs/` (the
submitted scripts and job records), and the VASP directories under `live_runs/<campaign>/`. `live_demo/04_archive/`
hashes every file and writes `live_summary.json`; `live_demo/03_record/` holds the screen-capture scripts used for
Supplementary Video 1.

## 5. If something fails

A gate failure goes to the recovery order: a stored rule (`recovery_live.yaml`; WALLTIME resubmits unfinished
frames, NELM resubmits the whole path with robust mixing so that one INCAR holds along the path), then the gate's
sub-agent (one listed option), then you, in the chat, with the listed options. Nothing is edited by hand: a fix is a
configuration patch that the next node reads. The two things that most often need you are a scheduler whose
submit output is not "job id first" (fix `submit_cmd`, see above) and a POTCAR library laid out differently from
`<dir>/<Element>/POTCAR` (fix `potcar_dir`, or symlink).
