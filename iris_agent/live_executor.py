"""Live executor: the real job-end hook for run.mode = live (replaces the stand-in `iris_agent.jobend`).

It is the only process that submits jobs. Loop (every run.live.poll_s seconds, default 60):

  1. Read f3's submission records (test_runs/<thread>/f3_jobs/submission.json, submission_r<k>.json).
     For every part of the newest round that is queued and not yet submitted: write POTCAR (and, on a
     resubmission round, the INCAR patch of that round), write the job script (run.live.job_header +
     one VASP call per frame), and submit it with run.live.submit_cmd. On a resubmission, outputs of the
     earlier attempt are moved to <point>/attempt_r<k>/ and points that already converged are skipped.
  2. A part has ended when its job script wrote its .done marker, or when its job id has left the queue
     (run.live.queue_cmd) without the marker (killed: walltime, node failure).
  3. For ended parts: collect (engines/live_vasp.collect_path: result.json, energies.csv,
     energies_summary.json), derive the part code (WALLTIME / NELM / UNKNOWN or none) and send ONE job-end
     event to the waiting thread, as iris_agent.jobend does:
         {"event": "job_end", "parts": [...], "failed": {"<p>": "<CODE>"}}
  4. Stop when the thread has ended (or with --once after one pass).

  python -m iris_agent.live_executor --config configs/batio3_T1_live.yaml [--thread NAME] [--once] [--dry-run]

--dry-run writes everything but does not call the scheduler (prints the commands).
State: test_runs/<thread>/f3_jobs/live_state.json (job ids, times, codes); log: .../f3_jobs/live_executor.log.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfgmod
from .engines import live_vasp as LV
from .paths import from_config

OUTPUTS = ("OSZICAR", "OUTCAR", "vasp.out", "result.json", "DONE", "CONTCAR", "vasprun.xml", "EIGENVAL", "DOSCAR",
           "IBZKPT", "PCDAT", "XDATCAR", "REPORT", "CHG", "CHGCAR", "WAVECAR")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Executor:
    def __init__(self, config_path: str, thread: str | None = None, dry_run: bool = False, log=print):
        self.config_path = str(Path(config_path).expanduser().resolve())
        raw = cfgmod.load(self.config_path)
        if (raw.get("run") or {}).get("mode") != "live" or not raw["run"].get("allow_live_submission"):
            raise SystemExit("the live executor runs only for run.mode: live with run.allow_live_submission: true")
        self.thread = thread or raw["thread_id"]
        self.P = from_config(raw)
        self.run_dir = self.P.run_dir(self.thread)
        self.jdir = self.P.out(self.run_dir, "f3_jobs")
        self.ldir = self.P.out(self.jdir, "live")
        self.dry_run, self._log = dry_run, log
        self.state_path = self.P.out(self.jdir, "live_state.json")

    # ------------------------------------------------------------------ helpers
    def log(self, msg: str):
        line = f"[{now()}] [{os.getpid()}] {msg}"
        self._log(line)
        self.jdir.mkdir(parents=True, exist_ok=True)
        with open(self.P.out(self.jdir, "live_executor.log"), "a") as fh:
            fh.write(line + "\n")

    def load_state(self) -> dict:
        return json.loads(self.state_path.read_text()) if self.state_path.is_file() else {"rounds": {}}

    def save_state(self, st: dict):
        self.state_path.write_text(json.dumps(st, indent=1))

    def records(self) -> list[dict]:
        """Submission records in round order (round 0 holds the frame layout)."""
        if not self.jdir.is_dir():
            return []
        recs = []
        r0 = self.jdir / "submission.json"
        if r0.is_file():
            recs.append(json.loads(r0.read_text()))
        for p in sorted(self.jdir.glob("submission_r*.json"), key=lambda x: int(x.stem.split("_r")[-1])):
            recs.append(json.loads(p.read_text()))
        return recs

    def cfg_live(self) -> dict:
        # the config of the run as f0 resolved it ({run} token) is in the checkpoint; the file is enough here:
        # the executor needs only run.live and the frame layout written by f3 (submission.json["live"])
        return cfgmod.load(self.config_path)["run"]["live"]

    # ------------------------------------------------------------------ 1. submit
    def job_script(self, rnd: int, part: int, frame_dirs: list[Path], live: dict) -> Path:
        name = (self.thread.replace("_live", "")[:9] + f"_r{rnd}p{part}")[:15]     # PBS -N: 15 characters max (Torque)
        done = self.P.out(self.ldir, f"r{rnd}_p{part}.done")
        lines = [live["job_header"].replace("{job_name}", name).rstrip(), "set +e"]
        for d in frame_dirs:
            lines += [f"cd {shlex.quote(str(d))}", f"{live['vasp_cmd']} > vasp.out 2>&1",
                      "echo $? > DONE"]
        lines += [f"date -u +%FT%TZ > {shlex.quote(str(done))}", ""]
        sp = self.P.out(self.ldir, f"r{rnd}_p{part}.sh")
        sp.write_text("\n".join(lines))
        sp.chmod(0o750)
        return sp

    def prepare_part(self, rec0: dict, rec: dict, part: str, live: dict) -> list[Path]:
        lv = rec0["live"]
        stored = Path(lv["stored"])
        base_incar = LV.incar_text(live["incar"], rec.get("incar_patch") or None)
        pot, _ = LV.potcar_text(lv["species"], live["potcar_dir"], live.get("potcar_labels") or {})
        dirs = []
        for fid in rec["book"]["parts"][part]["frames"]:
            d = self.P.out(stored, lv["frames"][str(fid)])
            if rec["round"] > 0:
                old = json.loads((d / "result.json").read_text()) if (d / "result.json").is_file() else {}
                if old.get("converged") and not rec.get("rerun_all"):
                    continue                                  # finished frames are skipped (recovery.yaml)
                keep = self.P.out(d, f"attempt_r{rec['round'] - 1}")
                keep.mkdir(exist_ok=True)
                for f in OUTPUTS + ("INCAR",):
                    if (d / f).exists():
                        shutil.move(str(d / f), str(keep / f))
            self.P.out(d, "INCAR").write_text(base_incar)
            self.P.out(d, "POTCAR").write_text(pot)
            dirs.append(d)
        return dirs

    def submit(self, script: Path, live: dict) -> str:
        cmd = shlex.split(os.path.expandvars(live["submit_cmd"])) + [str(script)]
        if self.dry_run:
            self.log("DRY RUN would run: " + " ".join(cmd))
            return f"dry-{script.stem}"
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            raise RuntimeError(f"submit failed ({out.returncode}): {out.stderr.strip()}")
        return out.stdout.strip().split()[0]

    def submit_new(self, st: dict) -> int:
        recs = self.records()
        if not recs or recs[0].get("engine") != "live":
            return 0
        live = self.cfg_live()
        rec0, rec = recs[0], recs[-1]
        rs = st["rounds"].setdefault(str(rec["round"]), {"parts": {}})
        n = 0
        for p, v in rec["book"]["parts"].items():
            if v["status"] != "queued" or p in rs["parts"]:
                continue
            self.ldir.mkdir(parents=True, exist_ok=True)
            dirs = self.prepare_part(rec0, rec, p, live)
            if not dirs:                                      # every frame of the part already converged
                rs["parts"][p] = {"job_id": None, "submitted": now(), "frames": 0, "status": "nothing_to_run"}
                self.P.out(self.ldir, f"r{rec['round']}_p{p}.done").write_text(now())
                continue
            script = self.job_script(rec["round"], int(p), dirs, live)
            jid = self.submit(script, live)
            rs["parts"][p] = {"job_id": jid, "submitted": now(), "frames": len(dirs), "status": "submitted",
                              "script": str(script), "incar_patch": rec.get("incar_patch") or {}}
            self.log(f"round {rec['round']} part {p}: {len(dirs)} frames submitted as {jid}")
            n += 1
        self.save_state(st)
        return n

    # ------------------------------------------------------------------ 2. ended parts
    def queue_ids(self, live: dict) -> set[str]:
        if self.dry_run:
            return set()
        out = subprocess.run(shlex.split(os.path.expandvars(live["queue_cmd"])), capture_output=True, text=True, timeout=120)
        ids = set()
        for ln in out.stdout.splitlines():
            tok = ln.split()
            if tok:
                ids.add(tok[0].split(".")[0])
        return ids

    def ended_parts(self, st: dict) -> list[tuple[str, str, bool]]:
        """[(round, part, vanished_without_done)] for parts that ended since the last pass."""
        live = self.cfg_live()
        q = None
        out = []
        for r, rs in st["rounds"].items():
            for p, v in rs["parts"].items():
                if v["status"] not in ("submitted", "nothing_to_run"):
                    continue
                done = (self.ldir / f"r{r}_p{p}.done").is_file()
                if done:
                    out.append((r, p, False))
                    continue
                if self.dry_run:
                    continue
                if q is None:
                    q = self.queue_ids(live)
                if str(v["job_id"]).split(".")[0] not in q:
                    out.append((r, p, True))
        return out

    # ------------------------------------------------------------------ 3. collect + job-end event
    def collect_and_notify(self, st: dict, ended: list[tuple[str, str, bool]]) -> dict | None:
        if not ended:
            return None
        recs = self.records()
        rec0 = recs[0]
        lv = rec0["live"]
        from .nodes.f2_path_planner import SYMPREC
        from .nodes.f3_path import _poscar

        def sg_of(d: Path) -> int:
            from pymatgen.core import Lattice, Structure
            from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
            lat, sp, fr = _poscar((d / "POSCAR").read_text())
            return SpacegroupAnalyzer(Structure(Lattice(lat), sp, fr), symprec=SYMPREC).get_space_group_number()

        frames = [json.loads((Path(lv["stored"]) / name / "frame.json").read_text()) for name in
                  [lv["frames"][k] for k in sorted(lv["frames"], key=int)]]
        col = LV.collect_path(Path(lv["stored"]), Path(lv["collected"]), frames, lv["per_fu"], sg_of)
        parts, failed = [], {}
        for r, p, vanished in ended:
            rec = next(x for x in recs if str(x["round"]) == r)
            fids = rec["book"]["parts"][p]["frames"]
            res = [col["results"].get(lv["frames"][str(f)], {"finished": False, "flags": ["NO_OUTPUT"]}) for f in fids]
            code = LV.failure_code(res, vanished)
            st["rounds"][r]["parts"][p].update({"status": "ended", "ended": now(), "code": code})
            parts.append(int(p))
            if code:
                failed[p] = code
            self.log(f"round {r} part {p} ended" + (f" with {code}" if code else " (all frames finished)"))
        self.save_state(st)
        return {"event": "job_end", "parts": sorted(parts), "failed": failed}

    def send(self, event: dict) -> dict:
        from .run import Session
        with Session(self.config_path, self.thread) as s:
            stt = s.status()
            waiting = [i for i in stt["interrupts"] if isinstance(i, dict) and i.get("kind") == "job_wait"]
            if not waiting:
                return {"status": "not_waiting", "next": stt["next"]}
            res = s.resume(event)
        self.log(f"sent {json.dumps(event)} -> {res.get('status')} (last node {res.get('last_node')})")
        return res

    def thread_status(self) -> dict:
        from .run import Session
        with Session(self.config_path, self.thread) as s:
            return s.status()

    # ------------------------------------------------------------------ loop
    def step(self) -> dict:
        st = self.load_state()
        n_sub = self.submit_new(st)
        st = self.load_state()
        pend = st.get("pending_event")
        if pend is None:
            pend = self.collect_and_notify(st, self.ended_parts(st))
            if pend:
                st = self.load_state()
                st["pending_event"] = pend
                self.save_state(st)
        res = None
        if pend:
            res = self.send(pend)
            if res.get("status") != "not_waiting":
                st = self.load_state()
                st.pop("pending_event", None)
                st.setdefault("events_sent", []).append({"utc": now(), "event": pend, "result": res.get("status")})
                self.save_state(st)
        return {"submitted": n_sub, "event": pend, "result": res}

    def run(self, poll_s: float, once: bool = False):
        self.log(f"live executor started for thread {self.thread} (poll {poll_s} s, dry run {self.dry_run})")
        while True:
            out = self.step()
            if once:
                return out
            stt = self.thread_status()
            if not stt["next"] and not stt["interrupts"] and stt.get("last_node"):
                self.log(f"thread ended (last node {stt['last_node']}); executor stops")
                return out
            time.sleep(poll_s)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--thread", default=None)
    ap.add_argument("--once", action="store_true", help="one pass (submit, check, notify), then exit")
    ap.add_argument("--dry-run", action="store_true", help="write inputs and scripts, do not call the scheduler")
    ap.add_argument("--poll", type=float, default=None, help="seconds between passes (default run.live.poll_s or 60)")
    a = ap.parse_args(argv)
    ex = Executor(a.config, a.thread, dry_run=a.dry_run)
    poll = a.poll or float(ex.cfg_live().get("poll_s", 60))
    out = ex.run(poll, once=a.once)
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
