"""IRIS chat (live demo surface): one terminal conversation from the plain-language request to the f6 report.

  python -m iris_agent.chat --campaign batio3_demo [--llm claude-sonnet | baseline] [--executor]

Turn by turn:
  1. The human types the request. f0's language-model intake (intake/, frozen) drafts the intent — system, formula,
     parent / child space groups, analysis, strain policy, budget — and the code resolves it (sources recorded).
     The intent and the verdict are shown. The model never sets a DFT parameter.
  2. A material without a stored campaign (status needs_new_dft) is what live mode is for: the chat fetches the parent
     and child structures from the Materials Project (engines/mp_fetch.py, MP_API_KEY from the environment), builds the
     run config from the live template (configs/live/_template_live.yaml: PBS header, VASP settings, policy) with the
     cell-dependent fields (f.u. per cell, k-mesh) derived from the fetched child cell, and shows it. The human confirms.
  3. The graph runs (iris_agent.run.Session, run.mode live). Every gate verdict is printed as it is written to
     audit.jsonl. At f3 the thread waits for the live executor (python -m iris_agent.live_executor, a second process
     or --executor to start it from here); the chat follows the audit log until the thread ends.
  4. A human interrupt (recover: rule -> sub-agent -> human) prints the menu; the human answers by option id.
  5. At the end: the f6 report (every reported number re-derived), the barrier, the files.

Everything the chat prints is appended to test_runs/<thread>/chat_transcript.md.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

TEMPLATE = AGENT_ROOT / "configs" / "live" / "_template_live.yaml"
TEMPLATE_PLANE = AGENT_ROOT / "configs" / "live" / "_template_plane_live.yaml"
K_LENGTH_A = 32.0          # k-points per axis = round(K_LENGTH / |a_i|): 8 for a = 4 Å (the validated BaTiO3 mesh)


class Transcript:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.lines: list[str] = []

    def bind(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with open(path, "a") as fh:
            fh.write("".join(self.lines))
        self.lines = []

    def say(self, who: str, text: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {who}: {text}\n"
        print(line, end="", flush=True)
        if self.path:
            with open(self.path, "a") as fh:
                fh.write(line)
        else:
            self.lines.append(line)

    def ask(self, prompt: str) -> str:
        print(prompt, end="", flush=True)
        ans = sys.stdin.readline().rstrip("\n")
        line = f"[{datetime.now().strftime('%H:%M:%S')}] human: {ans}\n"
        if self.path:
            with open(self.path, "a") as fh:
                fh.write(line)
        else:
            self.lines.append(line)
        return ans


# ---------------------------------------------------------------- 1. intake
def draft_intent(text: str, llm: str, models: str | None, attachments: list[str] | None = None) -> tuple[dict, dict]:
    from intake import baseline as BL, build as B, schema as S
    if llm in ("off", "baseline"):
        draft, meta = BL.draft(text, attachments), {"model": "keyword-baseline"}
    else:
        from intake.llm_json import llm_json
        from iris_agent.llm import MODELS_YAML, load_models
        mods = load_models(models or MODELS_YAML)
        if llm not in mods:
            raise SystemExit(f"--llm {llm!r} not in {models or MODELS_YAML}; known: {sorted(mods)}")
        r = llm_json({**mods[llm], "name": llm}, S.system_prompt(), S.user_prompt(text, attachments or []))
        draft = r.pop("obj") or {}
        meta = {k: r.get(k) for k in ("model", "model_version", "valid", "error", "latency_s", "tokens_in", "tokens_out")}
        if not draft:
            raise SystemExit(f"intake call failed: {meta}")
    return B.resolve(draft, attachments), meta


# ---------------------------------------------------------------- 2. live config
def kmesh(lattice_abc) -> list[int]:
    return [max(1, int(round(K_LENGTH_A / a))) for a in lattice_abc]


def build_live_config(res: dict, request: str, campaign: str, path_tag: str, inputs: dict, network: list[str],
                      template: dict | None = None) -> dict:
    """Template + intent + fetched cells. inputs: mp_fetch provenance (roles.parent/child)."""
    from pymatgen.core import Composition, Structure
    cfg = template or yaml.safe_load(TEMPLATE.read_text())
    it = res["intent"]
    psg, csg = int(it["parent_sg"]), int(it["child_sg"])
    formula = it.get("formula") or inputs["roles"]["child"]["formula"]
    child = Structure.from_file(inputs["roles"]["child"]["file"])
    n_fu = int(Composition(child.composition).get_reduced_formula_and_factor()[1])
    system = "".join(ch for ch in formula.lower() if ch.isalnum())
    plane = cfg["policy"].get("plane2")
    if plane:
        n = 2 * int(plane["levels"]) - 1
        pid = f"{path_tag}_{psg}-{csg}__{n}x{n}"
    else:
        pid = f"{path_tag}_{psg}-{csg}__lin{cfg['policy']['path']['n_points']}"
    thread = f"{system}_{campaign}_{path_tag}_{psg}_{csg}_live"      # one thread per campaign and path/plane
    lay = plane or cfg["policy"]["path"]
    cfg["system"] = system
    cfg["thread_id"] = thread
    cfg["request"] = request
    cfg["expected"] = {"parent_sg": psg, "child_sg": csg}
    rel = Path(inputs["roles"]["parent"]["file"]).resolve().relative_to(Path(cfg["paths"]["repo_root"]).expanduser().resolve())
    cfg["paths"]["parent_cif"] = str(rel)
    cfg["paths"]["child_cif"] = str(Path(inputs["roles"]["child"]["file"]).resolve().relative_to(Path(cfg["paths"]["repo_root"]).expanduser().resolve()))
    cfg["paths"]["system_json"] = str(Path(rel).with_name("system.json"))
    cfg["paths"]["isodistort_live"] = f"IRIS_AGENT/live_runs/{campaign}/{pid}/isodistort"
    lay["stored"] = f"IRIS_AGENT/live_runs/{campaign}/{pid}"
    lay["collected"] = f"IRIS_AGENT/live_runs/{campaign}"
    cfg["policy"]["fit"]["per_fu"] = n_fu
    if cfg["run"]["live"].get("kspacing") is None:              # no KSPACING in the template: explicit mesh from the child cell
        cfg["run"]["live"]["kpoints"] = kmesh(child.lattice.abc)
    cfg["run"]["live"]["incar"]["SYSTEM"] = f"{formula} {path_tag} static ({cfg['run']['live']['incar'].get('GGA', 'PBE')})"
    cfg["run"]["budget_runs"] = int(it.get("budget") or cfg["run"]["budget_runs"])
    if plane:
        pass
    elif network:
        cfg["policy"]["path"]["network"] = {"paths": sorted(set(network) | {pid}), "closure": [],
                                            "match": {"ltol": 0.01, "stol": 0.01, "angle_tol": 0.5},   # tight: BaTiO3 displacements are ~0.1 Å
                                            "cross_setting_meV": 1.0}
    else:
        cfg["policy"]["path"].pop("network", None)
    cfg["intake"] = {"status": "ok", "frozen_status": res["status"], "reason": res.get("reason"), "question": None,
                     "checks": res.get("checks", []), "template": "configs/live/_template_plane_live.yaml" if plane else "configs/live/_template_live.yaml",
                     "model_question": res.get("model_question"), "model_clarify_field": res.get("model_clarify_field"),
                     "intent": it, "sources": res["sources"],
                     "live": "the request needs new DFT; run.mode live computes it (no stored campaign is read)"}
    return cfg


FAKES = AGENT_ROOT / "tests" / "live_fakes"


def apply_mock(cfg: dict) -> None:
    """Rehearsal: everything real except the DFT — fake scheduler + fake VASP from tests/live_fakes."""
    fq = Path(os.environ.get("FAKEQ") or (AGENT_ROOT / "test_runs" / "_fakeq"))
    fq.mkdir(parents=True, exist_ok=True)
    os.environ["FAKEQ"] = str(fq)
    lv = cfg["run"]["live"]
    lv.update({"submit_cmd": str(FAKES / "fake_qsub"), "queue_cmd": str(FAKES / "fake_qstat"), "vasp_cmd": str(FAKES / "fake_vasp"),
               "job_header": "#!/bin/bash\n# MOCK job {job_name}: fake scheduler, fake VASP (tests/live_fakes)\n", "poll_s": 5})
    if not Path(lv["potcar_dir"]).expanduser().is_dir():
        lv["potcar_dir"] = str(FAKES / "potpaw_el")
    cfg["run"]["jobs"]["part_size"] = min(int(cfg["run"]["jobs"]["part_size"]), 5)


def write_system_json(path: Path, formula: str, psg: int, csg: int, live: dict):
    from pymatgen.core import Composition
    comp = {str(k): int(v) for k, v in Composition(formula).get_el_amt_dict().items()}
    path.write_text(json.dumps({"name": "".join(ch for ch in formula.lower() if ch.isalnum()), "composition": comp,
                                "structure_family": "from the Materials Project (live run)", "expected_parent_sg": psg,
                                "expected_child_sgs": [csg],
                                "vasp": {"encut": live["incar"].get("ENCUT"), "ispin": live["incar"].get("ISPIN"),
                                         "kpoints": live.get("kpoints"), "kspacing": live.get("kspacing", 0.20)},
                                "pseudopotentials": live.get("potcar_labels") or {s: s for s in comp}, "potcar_dir": live.get("potcar_dir")}, indent=1))


# ---------------------------------------------------------------- 3. follow the run
GATE_NAMES = {"G0": "intake", "G1": "decomposition", "G2": "path plan", "G3": "jobs", "G4": "energies",
              "G5": "profile", "G6": "re-derivation"}


class _Pump:
    """Pump an AuditFollower from a background thread while the graph runs (gate lines appear as they happen)."""

    def __init__(self, follower, every: float = 1.0):
        import threading
        self.f, self.every, self.stop = follower, every, threading.Event()
        self.t = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self.stop.wait(self.every):
            try:
                self.f.pump()
            except Exception:
                pass

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *a):
        self.stop.set()
        self.t.join(timeout=5)
        self.f.pump()


class AuditFollower:
    def __init__(self, path: Path, say, on_event=None):
        self.path, self.say, self.n, self.on_event = path, say, 0, on_event

    def pump(self):
        if not self.path.is_file():
            return
        lines = self.path.read_text().splitlines()
        for ln in lines[self.n:]:
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                continue
            k = e.get("kind")
            if self.on_event:
                self.on_event(e)
            if k == "node" and e.get("event") == "start":
                self.say("IRIS", f"{e['node']} {e.get('title', '')} starts" + (f" (attempt {e['attempts']})" if e.get("attempts") else ""))
            elif k == "gate":
                tests = e.get("tests") or []
                nt = sum(1 for t in tests if t.get("status") == "pass")
                verdict = "PASS" if e.get("ok") else f"FAIL {e.get('code')}"
                self.say("IRIS", f"{e['gate']} ({GATE_NAMES.get(e['gate'], '')}): {verdict}, {nt}/{len(tests)} tests"
                         + (f" — {e.get('detail')}" if e.get("detail") and not e.get("ok") else ""))
            elif k == "fix":
                self.say("IRIS", f"recover ({e.get('level')}): {e.get('rule') or e.get('option_id')} -> {e.get('route')}")
            elif k == "interrupt" and e.get("waiting_on") == "jobs":
                self.say("IRIS", f"f3 waiting for {e.get('parts_pending')} of {e.get('n_parts')} job parts (live executor submits them)")
            elif k == "resume":
                self.say("IRIS", f"resumed with {json.dumps(e.get('answer'))[:120]}")
            elif k == "end":
                self.say("IRIS", f"run ended: {e.get('status')} (last node {e.get('last_node')}, gate {e.get('gate_code')})")
        self.n = len(lines)


def run_and_follow(cfg_path: Path, thread: str, llm: str, models, T: Transcript, exec_proc=None, poll: float = 5.0, ablations=(),
                   on_event=None):
    from iris_agent.run import Session, human_message
    with Session(cfg_path, thread, llm=llm if llm not in ("baseline",) else "off", mode="live", models=models, ablations=ablations) as s:
        follower = AuditFollower(s.run_dir / "audit.jsonl", T.say, on_event)
        with _Pump(follower):
            res = s.start()
    while True:
        if res["status"] == "interrupted":
            p = res["interrupt"][0]
            T.say("IRIS", "a decision is needed (the rule table and the sub-agent did not settle it):")
            if hasattr(T, "menu"):
                T.menu(p)
            else:
                print(human_message(p, cfg_path, thread))
            ans = T.ask("human expert, option id> ").strip()
            if not ans and not sys.stdin.isatty():
                T.say("IRIS", "no human answer available (stdin closed); leaving the thread paused — answer later with "
                              f"python -m iris_agent.run --config {cfg_path} --resume '{{\"option\": \"<id>\"}}'")
                return res
            opt = next((o for o in p.get("options", []) if o["id"] == ans), None)
            if opt is None:
                T.say("IRIS", f"unknown option {ans!r}; choose one of {[o['id'] for o in p.get('options', [])]}")
                continue
            with Session(cfg_path, thread, llm=llm if llm != "baseline" else "off", mode="live", models=models) as s:
                with _Pump(follower):
                    res = s.resume({"option": opt["id"]})
            continue
        if res["status"] == "waiting_on_jobs":
            T.say("IRIS", "waiting for the jobs; the live executor will resume the thread when they end")
            while True:
                time.sleep(poll)
                follower.pump()
                with Session(cfg_path, thread, llm="off", mode="live") as s:
                    st = s.status()
                if st["interrupts"] and not any(isinstance(i, dict) and i.get("kind") == "job_wait" for i in st["interrupts"]):
                    res = {"status": "interrupted", "interrupt": st["interrupts"]}
                    break
                if not st["next"] and not st["interrupts"]:
                    res = {"status": "ended", "last_node": st.get("last_node"), "gate": st.get("gate")}
                    break
                if exec_proc is not None and exec_proc.poll() is not None:
                    T.say("IRIS", f"the live executor exited with code {exec_proc.returncode}; restart it and the chat continues")
                    exec_proc = None
            continue
        break
    follower.pump()
    return res


def final_state(cfg_path: Path, thread: str) -> dict:
    from iris_agent.run import Session
    with Session(cfg_path, thread, llm="off", mode="live") as s:
        st = s.graph.get_state(s.cfg).values
    import csv
    en, cfg = st.get("energies") or {}, st.get("config") or {}
    points = [{k: p.get(k) for k in ("id", "name", "lambda", "Q", "multiplicity", "E0_eV", "dE_meV", "scf_steps", "last_dE", "mag", "sg_frame")}
              for p in en.get("points", [])]
    campaign = {}
    try:                       # every finished path of the campaign (energies.csv of the shared collected folder)
        from .paths import from_config
        from .nodes._layout import grid_policy
        col = from_config(cfg).repo_root / grid_policy(cfg["policy"])["collected"] / "energies.csv"
        with open(col) as fh:
            for r in csv.DictReader(fh):
                campaign.setdefault(r["path"], []).append({"lambda": float(r["lambda"]), "dE": float(r["dE_meV_per_fu"])})
        for v in campaign.values():
            v.sort(key=lambda x: x["lambda"])
    except Exception:
        pass
    dec = st.get("decomposition") or {}
    return {"report": st.get("report") or {}, "model": st.get("model") or {}, "run_dir": str(s.run_dir),
            "grid": {k: v for k, v in (st.get("grid") or {}).items() if k in ("active", "n_frames", "kind")},
            "irreps": {ir: v.get("Ap") for ir, v in (dec.get("irreps") or {}).items()},
            "strain": dec.get("strain") or {}, "points": points, "campaign": campaign,
            "path_id": (cfg.get("policy", {}).get("path") or cfg.get("policy", {}).get("plane2") or {}).get("stored", "").rstrip("/").split("/")[-1]}


def report(cfg_path: Path, thread: str, T: Transcript):
    fs = final_state(cfg_path, thread)
    rep, model = fs["report"], fs["model"]
    if model.get("kind") == "plane2":
        c, mn = model["coefficients"], model["minimum"]
        T.say("IRIS", f"Landau fit (4mm invariants): a={c['a']:.1f} b={c['b']:.1f} c={c['c']:.1f} d={c['d']:.1f} e={c['e']:.1f} meV/f.u. per Å^n; "
                      f"rms {model['rms_meV']:.3f} meV/f.u.; c - 2b = {model['anisotropy_c_minus_2b']:.1f} ({'axis favoured' if model['anisotropy_c_minus_2b'] > 0 else 'diagonal favoured'})")
        T.say("IRIS", f"minimum {mn['E_meV']:.3f} meV/f.u. at (Q1, Q2) = ({mn['Q1']:.3f}, {mn['Q2']:.3f}) Å on the {mn['where']}; "
                      f"lowest computed point on the axis {model['E_axis_min_meV']:.3f}, on the diagonal {model['E_diag_min_meV']:.3f} meV/f.u.")
    if model.get("kind") == "path":
        T.say("IRIS", f"profile dE(lambda) meV/f.u.: {[round(x, 3) for x in model['dE_meV']]}")
        T.say("IRIS", f"barrier {model['barrier_meV']:.3f} meV/f.u. at lambda = {model['barrier_lambda']:.3f} ({model['barrier_point']}); "
                      f"dE(end) = {model['dE_end_meV']:.3f} meV/f.u.; {model.get('barrier_kind')}")
    if rep:
        T.say("IRIS", f"f6: {rep.get('n_ok')} of {rep.get('n_numbers')} reported numbers re-derived and equal")
        bad = [r for r in rep.get("rows", []) if not r.get("ok")]
        for r in bad[:10]:
            T.say("IRIS", f"  MISMATCH {r['name']}: reported {r['value']} vs re-derived {r['rederived']}")
    T.say("IRIS", f"files: {fs['run_dir']}/audit.jsonl, iris.sqlite, f3_jobs/, chat_transcript.md")


# ---------------------------------------------------------------- main
def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campaign", required=True, help="folder name under IRIS_AGENT/live_runs/ shared by the paths of one demo")
    ap.add_argument("--path-tag", default=None, help="T1, T2, ... (default: next free tag in the campaign)")
    ap.add_argument("--llm", default="baseline", help="intake + sub-agents: a model from eval/models.yaml, or baseline")
    ap.add_argument("--models", default=None)
    ap.add_argument("--network", action="store_true", help="check this path against the campaign's finished paths (f5)")
    ap.add_argument("--executor", action="store_true", help="start the live executor from here (else run it in another pane)")
    ap.add_argument("--request", default=None, help="skip the prompt and use this request")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation before running")
    ap.add_argument("--parent-id", default=None, help="pin the Materials Project id of the parent")
    ap.add_argument("--child-id", default=None)
    ap.add_argument("--n-points", type=int, default=None, help="path points (template: 10). Short run: 4")
    ap.add_argument("--part-size", type=int, default=None, help="statics per PBS job (template: 5)")
    ap.add_argument("--plane", action="store_true", help="two-component plane of the primary irrep (configs/live/_template_plane_live.yaml)")
    ap.add_argument("--levels", type=int, default=None, help="plane: non-negative levels per axis (5 -> 9x9 grid, 15 statics)")
    ap.add_argument("--mock", action="store_true", help="MOCK run: real intake, Materials Project, FINDSYM/ISODISTORT, gates; "
                    "VASP and PBS replaced by tests/live_fakes (fake_qsub/fake_qstat/fake_vasp, synthetic energies). Rehearsal only.")
    ap.add_argument("--dry-run", action="store_true", help="rehearsal: run to f3, write POTCAR + PBS scripts without submitting, exit")
    ap.add_argument("--template", default=None, help=f"live template (default {TEMPLATE})")
    ap.add_argument("--ablate", default="", help="comma list of ablations (tests only)")
    return ap


def main(argv=None):
    global TEMPLATE, TEMPLATE_PLANE
    a = parser().parse_args(argv)
    if a.template:                                   # one override for whichever template this run uses
        TEMPLATE = TEMPLATE_PLANE = Path(a.template).expanduser().resolve()
    T = Transcript()
    T.say("IRIS", "IRIS live. Describe the transition you want mapped (material, parent and child space groups, what to compute).")
    text = a.request or T.ask("human> ")
    return pipeline(a, T, text)


def pipeline(a, T: Transcript, text: str, on_event=None, on_config=None) -> int:
    """request text -> intake -> structures -> config -> run -> report. T.say / T.ask are the only I/O."""
    res, meta = draft_intent(text, a.llm, a.models)
    it = res["intent"]
    T.say("IRIS", f"intake ({meta.get('model')}): " + ", ".join(f"{k}={it[k]}" for k in ("system", "formula", "parent_sg", "child_sg", "analysis", "strain_policy", "budget") if it.get(k) is not None))
    by = {}
    for k, v in res["sources"].items():
        if it.get(k) not in (None, []):
            by.setdefault(v or "unset", []).append(k)
    T.say("IRIS", "sources: " + "; ".join(f"{src}: {', '.join(ks)}" for src, ks in by.items()) + f" | verdict: {res['status']}"
          + (f" — {res.get('reason')}" if res.get("reason") else ""))
    if res["status"] == "ambiguous":
        T.say("IRIS", f"question: {res['question']}")
        return 2
    if res["status"] == "out_of_scope":
        return 2
    if res["status"] != "needs_new_dft":
        T.say("IRIS", "this request has a stored campaign; run it with python -m iris_agent.run (replay). Live mode is for new DFT.")
        return 2
    plane = (it.get("analysis") == "plane") or bool(getattr(a, "plane", False))
    if it.get("analysis") not in (None, "path", "plane"):
        T.say("IRIS", f"live mode computes straight-line paths and two-component planes; analysis {it['analysis']} is not live yet")
        return 2
    # ---- structures
    from iris_agent.engines import mp_fetch
    tmpl_path = TEMPLATE_PLANE if plane else TEMPLATE
    cfg0 = yaml.safe_load(tmpl_path.read_text())
    repo = Path(cfg0["paths"]["repo_root"]).expanduser()
    runs = repo / "IRIS_AGENT" / "live_runs" / a.campaign
    if plane:
        tag = a.path_tag or "PL"
    else:
        tag = a.path_tag or f"T{1 + sum(1 for d in runs.glob('T*__lin*') if d.is_dir()) if runs.is_dir() else 1}"
    inputs_dir = repo / "IRIS_AGENT" / "live_inputs" / a.campaign / tag
    T.say("IRIS", f"fetching {it['formula']} #{it['parent_sg']} and #{it['child_sg']} from the Materials Project -> {inputs_dir}")
    prov = mp_fetch.fetch(it["formula"], int(it["parent_sg"]), int(it["child_sg"]), inputs_dir, a.parent_id, a.child_id)
    for role, i in prov["roles"].items():
        alias = f" (API id {i['material_id_api']})" if i.get("material_id_api") and i["material_id_api"] != i["material_id"] else ""
        T.say("IRIS", f"  {role}: {i['material_id']}{alias} #{i['space_group_written']}, {i['n_atoms_conventional']} atoms, "
                      f"a,b,c = {[round(x, 4) for x in i['lattice_abc']]} Å, E above hull {1000 * float(i['energy_above_hull_eV_per_atom'] or 0):.1f} meV/atom")
    network = [d.name for d in runs.glob("T*__lin*") if (d.parent / "energies_summary.json").is_file()
               and d.name in json.loads((d.parent / "energies_summary.json").read_text()).get("paths", {})] if (a.network and runs.is_dir()) else []
    cfg0 = yaml.safe_load(tmpl_path.read_text())
    if a.n_points and not plane:
        cfg0["policy"]["path"]["n_points"] = a.n_points
    if plane and getattr(a, "levels", None):
        cfg0["policy"]["plane2"]["levels"] = int(a.levels)
    if a.part_size:
        cfg0["run"]["jobs"]["part_size"] = a.part_size
    if a.mock:
        apply_mock(cfg0)
    cfg = build_live_config(res, text, a.campaign, tag, prov, network, cfg0)
    if a.mock:
        cfg["intake"]["mock"] = "MOCK RUN: VASP and PBS replaced by tests/live_fakes; the energies are synthetic"
    write_system_json(inputs_dir / "system.json", it["formula"], int(it["parent_sg"]), int(it["child_sg"]), cfg["run"]["live"])
    from iris_agent import config as C
    errs = C.validate(cfg)
    thread = cfg["thread_id"]
    run_dir = repo / "IRIS_AGENT" / "test_runs" / thread
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = run_dir / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=140))
    T.bind(run_dir / "chat_transcript.md")
    if on_config:
        on_config(cfg, cfg_path, thread, run_dir)
    T.say("IRIS", f"config written: {cfg_path}" + (f"; schema errors: {errs}" if errs else ""))
    lv = cfg["run"]["live"]
    if a.mock:
        T.say("IRIS", "MOCK RUN — VASP and the PBS scheduler are replaced by tests/live_fakes (synthetic energies); intake, "
                      "Materials Project, FINDSYM/ISODISTORT, the graph and every gate are real")
    kdesc = ("k-mesh " + "×".join(str(k) for k in lv["kpoints"])) if lv.get("kpoints") else f"KSPACING {lv.get('kspacing')} (Gamma mesh per cell)"
    if plane:
        lv2 = cfg["policy"]["plane2"]
        n = 2 * int(lv2["levels"]) - 1
        T.say("IRIS", f"plan: {lv2['irrep']} plane (Q1, Q2) at the fixed parent cell, {n}x{n} grid to {lv2['q_max']} x A_p, "
                      f"orbit representatives under 4mm only, {cfg['policy']['fit']['per_fu']} f.u./cell, {kdesc}, "
                      f"ENCUT {lv['incar'].get('ENCUT')} eV, {cfg['run']['jobs']['part_size']} statics per PBS job, submit with {lv['submit_cmd']}")
    else:
        T.say("IRIS", f"plan: {cfg['policy']['path']['n_points']} frames {tag} #{it['parent_sg']} -> #{it['child_sg']}, "
                    f"{cfg['policy']['fit']['per_fu']} f.u./cell, {kdesc}, ENCUT {lv['incar'].get('ENCUT')} eV, "
                    f"{cfg['run']['jobs']['part_size']} statics per PBS job, submit with {lv['submit_cmd']}"
                    + (f", network check against {' + '.join(x.split('__')[0] for x in network)}" if network else ""))
    if not a.yes:
        ans = T.ask("run it? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            T.say("IRIS", "not started")
            return 0
    proc = None
    if a.dry_run:
        from iris_agent.live_executor import Executor
        from iris_agent.run import Session
        with Session(cfg_path, thread, llm=a.llm if a.llm != "baseline" else "off", mode="live", models=a.models,
                     ablations=[x for x in a.ablate.split(",") if x]) as s:
            follower = AuditFollower(s.run_dir / "audit.jsonl", T.say, on_event)
            with _Pump(follower):
                res = s.start()
        if res["status"] != "waiting_on_jobs":
            T.say("IRIS", f"dry run stopped before f3: {res.get('status')} {res.get('gate') or res.get('interrupt')}")
            return 1
        ex = Executor(str(cfg_path), thread, dry_run=True, log=lambda m: T.say("executor", m))
        ex.step()
        T.say("IRIS", f"DRY RUN: inputs in {repo / cfg['policy']['path']['stored']}, PBS scripts in {run_dir}/f3_jobs/live/ "
                      f"(nothing submitted). Delete {run_dir} and live_runs/{a.campaign}/ before the real run, or keep them as the rehearsal record.")
        return 0
    if a.executor:
        proc = subprocess.Popen([sys.executable, "-m", "iris_agent.live_executor", "--config", str(cfg_path), "--thread", thread],
                                cwd=str(AGENT_ROOT), stdout=open(run_dir / "live_executor.stdout", "a"), stderr=subprocess.STDOUT)
        T.say("IRIS", f"live executor started (pid {proc.pid}), log {run_dir}/f3_jobs/live_executor.log")
    else:
        T.say("IRIS", f"start the executor in the other pane:  python -m iris_agent.live_executor --config {cfg_path}")
    res = run_and_follow(cfg_path, thread, a.llm, a.models, T, proc, ablations=[x for x in a.ablate.split(",") if x],
                         on_event=on_event)
    report(cfg_path, thread, T)
    if proc is not None and proc.poll() is None:
        proc.wait(timeout=120)
    return 0 if res.get("status") in ("completed", "ended") else 1


if __name__ == "__main__":
    sys.exit(main())
