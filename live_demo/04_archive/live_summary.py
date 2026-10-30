#!/usr/bin/env python3
"""Summarise a live IRIS campaign for the manuscript: one block per thread, then campaign totals.

    python live_summary.py <campaign>            # e.g. batio3_pbe_20261028   (reads $IRIS_AGENT)
    python live_summary.py <campaign> --md       # markdown table of the paths

Reads  $IRIS_AGENT/test_runs/*_<campaign>_*_live/{chat_transcript.md,audit.jsonl,f3_jobs/live/*.sh}
and    $IRIS_AGENT/live_runs/<campaign>/energies.csv.   Nothing is written.
"""
import csv, glob, json, os, re, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

camp = sys.argv[1]
agent = Path(os.environ.get("IRIS_AGENT", "."))
md = "--md" in sys.argv

def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

# ---- campaign energies -----------------------------------------------------------------------
rows = defaultdict(list)
csvf = agent / "live_runs" / camp / "energies.csv"
if csvf.exists():
    with open(csvf) as fh:
        for r in csv.DictReader(fh):
            rows[r["path"]].append(r)

threads = sorted(glob.glob(str(agent / "test_runs" / f"*_{camp}_*_live")))
tot = {"statics": 0, "jobs": 0, "wall_s": 0.0, "f6": [0, 0], "human": 0, "gates_failed": 0}
table = []
for td in threads:
    td = Path(td)
    name = td.name
    tr = (td / "chat_transcript.md").read_text().splitlines() if (td / "chat_transcript.md").exists() else []
    aud = [json.loads(l) for l in open(td / "audit.jsonl")] if (td / "audit.jsonl").exists() else []
    if not aud:
        continue
    mock = any("MOCK RUN" in l for l in tr)
    t0, t1 = ts(aud[0]["ts"]), ts(aud[-1]["ts"])
    wall = (t1 - t0).total_seconds()
    gates = [(e["gate"], e["ok"], e.get("code")) for e in aud if e.get("kind") == "gate"]
    nfail = sum(1 for g in gates if not g[1])
    end = next((e for e in aud if e.get("kind") == "end"), {})
    human = sum(1 for l in tr if "] human:" in l and not l.rstrip().endswith("human: y"))
    mp = [l.split("IRIS:")[1].strip() for l in tr if re.search(r"\b(parent|child): mp-", l)]
    intake = next((l.split("intake")[1].strip() for l in tr if "] IRIS: intake (" in l), "")
    landau = [l.split("IRIS:")[1].strip() for l in tr if "Landau fit" in l or l.split("IRIS:")[-1].strip().startswith("minimum ") or "barrier " in l]
    f6 = next((re.search(r"f6: (\d+) of (\d+)", l) for l in tr if "f6:" in l), None)
    jobs = sorted(glob.glob(str(td / "f3_jobs" / "live" / "r*_p*.sh")))
    statics = sum(sum(1 for l in open(j) if l.startswith("cd ")) for j in jobs)
    # job wall times from the audit job events if present, else from .sh mtime -> .done
    jw = []
    for j in jobs:
        d = Path(j[:-3] + ".done")
        if d.exists():
            try:
                jw.append((ts(d.read_text().strip()) - datetime.fromtimestamp(os.path.getmtime(j), tz=t0.tzinfo)).total_seconds())
            except Exception:
                pass
    pid = next((r for r in rows if r.split("_")[0] == name.split(f"_{camp}_")[1].split("_")[0]), None)
    emin = None
    if pid:
        pts = [(float(r["lambda"] or "nan"), float(r["dE_meV_per_fu"])) for r in rows[pid]]
        emin = min(pts, key=lambda x: x[1])
    print(f"== {name}{'   [MOCK]' if mock else ''}")
    print(f"   start {t0:%Y-%m-%d %H:%M:%S} UTC  end {t1:%H:%M:%S}  wall {wall/60:.1f} min   status {end.get('status')} ({end.get('gate_code')})")
    print(f"   intake{intake}")
    for m in mp:
        print(f"   {m}")
    gstr = " ".join("%s:%s" % (g, "PASS" if ok else c) for g, ok, c in gates)
    print(f"   gates: {gstr}   failed {nfail}   human decisions {human}")
    print(f"   jobs {len(jobs)}  statics {statics}" + (f"  job wall min/median/max {min(jw)/60:.1f}/{sorted(jw)[len(jw)//2]/60:.1f}/{max(jw)/60:.1f} min" if jw else ""))
    if pid:
        print(f"   path {pid}: {len(rows[pid])} points, min dE {emin[1]:.3f} meV/f.u. at lambda {emin[0]:.3f}")
    for l in landau:
        print(f"   {l}")
    if f6:
        print(f"   f6: {f6.group(1)} of {f6.group(2)}")
    if not mock:
        tot["statics"] += statics; tot["jobs"] += len(jobs); tot["wall_s"] += wall; tot["human"] += human; tot["gates_failed"] += nfail
        if f6:
            tot["f6"][0] += int(f6.group(1)); tot["f6"][1] += int(f6.group(2))
        table.append((name, pid, len(rows.get(pid, [])), len(jobs), statics, wall / 60, emin, f6.groups() if f6 else ("", "")))
print(f"\n== campaign {camp} (non-mock threads): {len(table)} threads, {tot['jobs']} PBS jobs, {tot['statics']} statics, "
      f"{tot['wall_s']/3600:.2f} h summed wall, gates failed {tot['gates_failed']}, human decisions {tot['human']}, f6 {tot['f6'][0]} of {tot['f6'][1]}")
if md:
    print("\n| thread | path | points | jobs | statics | wall (min) | min dE (meV/f.u.) | at lambda | f6 |\n|---|---|---|---|---|---|---|---|---|")
    for n, p, np_, nj, ns, w, em, f in table:
        print(f"| {n} | {p} | {np_} | {nj} | {ns} | {w:.1f} | {em[1]:.3f} | {em[0]:.3f} | {f[0]}/{f[1]} |" if em else f"| {n} | {p} | {np_} | {nj} | {ns} | {w:.1f} | | | {f[0]}/{f[1]} |")
