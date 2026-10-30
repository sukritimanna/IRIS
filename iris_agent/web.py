"""IRIS chat in the browser (live demo surface for the recording). Python standard library only.

  python -m iris_agent.web --campaign batio3_20261103 --llm claude-sonnet --executor [--port 8765]
  then on the Mac:  ssh -L 8765:localhost:8765 carbon   and open  http://localhost:8765

Left: the conversation (human request, IRIS replies, the human-expert menu as buttons). Right: the f0-f6 workflow
board with the G0-G6 verdicts and test counts, the PBS job parts, and at the end the dE(lambda) profile and the f6
re-derivation count. Underneath it is exactly iris_agent.chat's pipeline (same intake, same graph, same executor,
same files): this module only replaces the terminal with an HTTP page that polls /state.
"""
from __future__ import annotations

import json
import queue
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import chat as CH

NODE_TITLES = {"f0": "Intake", "f1": "Crystallographer", "f2": "Path planner", "f3": "Runner", "f4": "Reviewer",
               "f5": "Analyst", "f6": "Skeptic"}
NODE_DOING = {"f0": "reading the request, checking the structures and the config (G0)",
              "f1": "FINDSYM + ISODISTORT live at iso.byu.edu: symmetry-mode decomposition of the child (G1)",
              "f2": "building the frames from the mode vectors; symmetry, orbits and d_min of every frame (G2)",
              "f3": "writing VASP inputs; the live executor submits the PBS jobs and collects them (G3)",
              "f4": "reading every OSZICAR/OUTCAR: convergence, magnetism, one INCAR/KPOINTS/POTCAR set (G4)",
              "f5": "fitting the Landau model / profile and the network checks (G5)",
              "f6": "re-deriving every reported number independently (G6)"}


class WebTranscript(CH.Transcript):
    """chat.Transcript whose say/ask go to the page (and to chat_transcript.md as before)."""

    def __init__(self, state: dict):
        super().__init__()
        self.state = state
        self.answers: queue.Queue = queue.Queue()

    def say(self, who: str, text: str):
        super().say(who, text)
        self.state["messages"].append({"t": datetime.now().strftime("%H:%M:%S"), "who": who, "text": text})

    def menu(self, payload: dict):
        self.state["menu"] = {"node": payload["node"], "gate": payload["gate"], "code": payload["code"],
                              "detail": payload.get("detail", ""), "why": payload.get("why_human", {}),
                              "options": [{"id": o["id"], "text": o["text"]} for o in payload.get("options", [])]}

    def ask(self, prompt: str) -> str:
        self.state["waiting_for"] = prompt
        ans = self.answers.get()                   # blocks the pipeline thread until the page posts an answer
        self.state["waiting_for"], self.state["menu"] = None, None
        line = f"[{datetime.now().strftime('%H:%M:%S')}] human: {ans}\n"
        if self.path:
            with open(self.path, "a") as fh:
                fh.write(line)
        else:
            self.lines.append(line)
        self.state["messages"].append({"t": datetime.now().strftime("%H:%M:%S"), "who": "human", "text": ans})
        return ans


class App:
    def __init__(self, args):
        self.args = args
        self.state = {"messages": [], "nodes": {n: {"title": t, "status": "idle", "gate": None} for n, t in NODE_TITLES.items()},
                      "jobs": {}, "menu": None, "waiting_for": None, "phase": "ready", "request": None, "config": None,
                      "result": None, "campaign": args.campaign, "started": None, "mock": bool(getattr(args, "mock", False))}
        self.T = WebTranscript(self.state)
        self.lock = threading.Lock()
        self.thread = None
        self.T.say("IRIS", "IRIS live. Describe the transition you want mapped (material, parent and child space groups, what to compute).")

    # ---- audit events -> board
    def on_event(self, e: dict):
        k, n = e.get("kind"), e.get("node")
        nodes = self.state["nodes"]
        if k == "node" and n in nodes:
            if e.get("event") == "start":
                for m in nodes.values():
                    if m["status"] == "running":
                        m["status"] = "done"
                nodes[n].update(status="running", attempts=e.get("attempts", 0), gate=None, started=time.time(), doing=NODE_DOING.get(n))
                self.state["now"] = {"node": n, "title": NODE_TITLES[n], "doing": NODE_DOING.get(n), "since": time.time()}
            elif e.get("event") in ("done", "error"):
                nodes[n]["wall_s"] = e.get("wall_time_s")
                if nodes[n].get("started"):
                    nodes[n]["wall_s"] = nodes[n].get("wall_s") or round(time.time() - nodes[n]["started"], 1)
        elif k == "gate" and n in nodes:
            tests = e.get("tests") or []
            nodes[n]["gate"] = {"id": e["gate"], "ok": bool(e.get("ok")), "code": e.get("code"), "detail": e.get("detail", ""),
                                "n_pass": sum(1 for t in tests if t.get("status") == "pass"), "n": len(tests),
                                "tests": [{"test": t.get("test"), "status": t.get("status"), "code": t.get("code")} for t in tests]}
            nodes[n]["status"] = "done" if e.get("ok") else "failed"
        elif k == "fix":
            self.state.setdefault("fixes", []).append({"node": n, "gate": e.get("gate"), "code": e.get("code"), "level": e.get("level"),
                                                       "rule": e.get("rule") or e.get("option_id"), "route": e.get("route")})
        elif k == "interrupt" and e.get("waiting_on") == "jobs":
            nodes["f3"]["status"] = "waiting"
            self.state["jobs"].update({"pending": e.get("parts_pending"), "n_parts": e.get("n_parts")})
            self.state["now"] = {"node": "f3", "title": "Runner", "doing": f"waiting for {e.get('parts_pending')} of {e.get('n_parts')} PBS job parts (live executor submits, polls qstat every 30 s, collects)", "since": time.time()}
        elif k == "end":
            self.state["phase"] = "ended"
            self.state["end"] = {"status": e.get("status"), "gate_code": e.get("gate_code")}
            self.state["now"] = {"node": None, "title": "done", "doing": f"run {e.get('status')} (last node {e.get('last_node')}, gate {e.get('gate_code')})", "since": time.time()}

    def on_config(self, cfg, cfg_path, thread, run_dir):
        lv = cfg["run"]["live"]
        lay = cfg["policy"].get("path") or cfg["policy"]["plane2"]
        plane = cfg["policy"].get("plane2")
        self.state["config"] = {"thread": thread, "path": str(cfg_path), "run_dir": str(run_dir), "system": cfg["system"],
                                "parent_sg": cfg["expected"]["parent_sg"], "child_sg": cfg["expected"]["child_sg"],
                                "plane": None if not plane else {"irrep": plane["irrep"], "n": 2 * int(plane["levels"]) - 1, "q_max": plane["q_max"]},
                                "n_points": lay.get("n_points"), "per_fu": cfg["policy"]["fit"]["per_fu"],
                                "kpoints": lv.get("kpoints") or [f"KSPACING {lv.get('kspacing')}"], "encut": lv["incar"].get("ENCUT"), "gga": lv["incar"].get("GGA", "PBE"),
                                "part_size": cfg["run"]["jobs"]["part_size"], "submit": lv["submit_cmd"],
                                "stored": lay["stored"], "network": (lay.get("network") or {}).get("paths")}
        self.cfg_path, self.thread, self.run_dir = Path(cfg_path), thread, Path(run_dir)

    def jobs_poll(self):
        """f3_jobs/live_state.json -> the jobs panel (read-only)."""
        while self.state["phase"] not in ("ended", "error"):
            time.sleep(2)
            try:
                p = getattr(self, "run_dir", None)
                if p and (p / "f3_jobs" / "live_state.json").is_file():
                    st = json.loads((p / "f3_jobs" / "live_state.json").read_text())
                    parts = []
                    for r, rs in st.get("rounds", {}).items():
                        for pp, v in rs["parts"].items():
                            parts.append({"round": int(r), "part": int(pp), "job_id": v.get("job_id"), "status": v.get("status"),
                                          "frames": v.get("frames"), "code": v.get("code"), "submitted": v.get("submitted"), "ended": v.get("ended")})
                    self.state["jobs"]["parts"] = parts
            except Exception:
                pass

    # ---- pipeline thread
    def start(self, text: str):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return False
            self.state.update(phase="running", request=text, started=datetime.now().strftime("%H:%M:%S"))
            self.state["messages"].append({"t": datetime.now().strftime("%H:%M:%S"), "who": "human", "text": text})
            self.thread = threading.Thread(target=self._run, args=(text,), daemon=True)
            self.thread.start()
            threading.Thread(target=self.jobs_poll, daemon=True).start()
            return True

    def _run(self, text):
        try:
            rc = CH.pipeline(self.args, self.T, text, on_event=self.on_event, on_config=self.on_config)
            if hasattr(self, "cfg_path"):
                try:
                    self.state["result"] = CH.final_state(self.cfg_path, self.thread)
                except Exception as exc:
                    self.T.say("IRIS", f"could not read the final state: {exc}")
            self.state["phase"] = "ended" if rc == 0 else "stopped"
        except BaseException as exc:                       # SystemExit included: IRIS refuses with SystemExit
            self.T.say("IRIS", f"error: {type(exc).__name__}: {exc}")
            self.state["phase"] = "error"


HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>IRIS</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#f4f6f9;--panel:#ffffff;--line:#e3e7ee;--fg:#1a202c;--mute:#64748b;--brand:#1f4fbf;--brand2:#e8effd;--ok:#15803d;--okbg:#e6f6ec;--bad:#b91c1c;--badbg:#fdecec;--run:#b45309;--runbg:#fff4e0;--wait:#6d28d9;--waitbg:#f1ebfd}
*{box-sizing:border-box}html,body{height:100%}body{margin:0;background:var(--bg);color:var(--fg);font:14.5px/1.5 Inter,-apple-system,Segoe UI,Helvetica,Arial,sans-serif}
.mono{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace}
header{height:60px;display:flex;align-items:center;gap:14px;padding:0 26px;background:var(--panel);border-bottom:1px solid var(--line)}
.logo{width:34px;height:34px;border-radius:9px;background:linear-gradient(135deg,#1f4fbf,#5b8def);color:#fff;display:grid;place-items:center;font-weight:700;font-size:13px;letter-spacing:.5px}
header h1{font-size:16px;margin:0;font-weight:600}header .sub{color:var(--mute);font-size:13px}
.now{margin-left:auto;font-size:12.5px;color:var(--mute);max-width:46%;text-align:right;line-height:1.3}.now b{color:var(--fg)}.now .el{font-family:"JetBrains Mono",monospace;color:var(--run)}
.status{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--mute);border:1px solid var(--line);padding:5px 12px;border-radius:999px;background:#fff}
.dot{width:8px;height:8px;border-radius:50%;background:#94a3b8}.status.running .dot{background:#f59e0b;animation:pulse 1.2s infinite}.status.ended .dot{background:#16a34a}.status.stopped .dot,.status.error .dot{background:#dc2626}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
main{display:grid;grid-template-columns:minmax(560px,1.2fr) minmax(460px,1fr);height:calc(100vh - 60px);min-height:0}body{overflow:hidden}
#chat{display:flex;flex-direction:column;min-height:0;overflow:hidden;border-right:1px solid var(--line);background:var(--panel)}
#msgs{flex:1;min-height:0;overflow-y:auto;padding:22px 28px;display:flex;flex-direction:column;gap:12px}
.row{display:flex;gap:10px;align-items:flex-start}.row.human{flex-direction:row-reverse}
.av{width:28px;height:28px;border-radius:50%;flex:none;display:grid;place-items:center;font-size:10.5px;font-weight:700;color:#fff;background:linear-gradient(135deg,#1f4fbf,#5b8def)}.row.human .av{background:#334155}
.m{max-width:80%;padding:10px 14px;border-radius:16px;white-space:pre-wrap;word-break:break-word;background:#f1f4f9;border-bottom-left-radius:5px}
.row.human .m{background:var(--brand);color:#fff;border-bottom-left-radius:16px;border-bottom-right-radius:5px}
.meta{font-size:11px;color:var(--mute);margin:0 0 4px 38px}.row.human+.meta,.meta.human{text-align:right;margin:0 38px 4px 0}
.card{max-width:86%;border:1px solid var(--line);border-radius:14px;background:#fff;overflow:hidden}
.card .hd{padding:8px 14px;font-size:12px;font-weight:600;color:var(--mute);letter-spacing:.5px;text-transform:uppercase;background:#f8fafc;border-bottom:1px solid var(--line)}
.card .bd{padding:10px 14px}.kv{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;font-size:13.5px}.kv div:nth-child(odd){color:var(--mute)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}.chip{font-size:12px;padding:2px 9px;border-radius:999px;background:var(--brand2);color:var(--brand);font-weight:500}
.tl{max-width:86%;border:1px solid var(--line);border-radius:14px;background:#fff;padding:6px 0}
.tl .it{display:grid;grid-template-columns:22px 1fr auto;gap:8px;align-items:center;padding:5px 14px;font-size:13.5px}
.tl .it+.it{border-top:1px solid #f1f4f9}.tl .ic{width:16px;height:16px;border-radius:50%;display:grid;place-items:center;font-size:10px;color:#fff;background:#94a3b8}
.tl .ic.ok{background:var(--ok)}.tl .ic.bad{background:var(--bad)}.tl .ic.run{background:#f59e0b}.tl .ic.wait{background:#7c3aed}.tl .ic.fix{background:#0e7490}
.tl .t{color:var(--mute);font-size:11.5px}.tl .d{color:var(--mute);font-size:12.5px;margin-top:1px}
.badge{display:inline-block;font-size:11.5px;padding:1px 8px;border-radius:999px;font-weight:600}.badge.ok{background:var(--okbg);color:var(--ok)}.badge.bad{background:var(--badbg);color:var(--bad)}.badge.run{background:var(--runbg);color:var(--run)}.badge.wait{background:var(--waitbg);color:var(--wait)}
.typing{display:inline-flex;gap:4px;padding:10px 14px;background:#f1f4f9;border-radius:16px;border-bottom-left-radius:5px}.typing i{width:6px;height:6px;border-radius:50%;background:#94a3b8;animation:pulse 1.2s infinite}.typing i:nth-child(2){animation-delay:.2s}.typing i:nth-child(3){animation-delay:.4s}
#menu{margin:0 28px 10px;padding:14px 16px;border:1px solid #f5c76a;border-radius:14px;background:#fffaf0}
#menu h3{margin:0 0 4px;font-size:14px;color:var(--run)}#menu .d{font-size:13px;color:#7c5a1e;margin-bottom:10px}
#menu button{display:block;width:100%;text-align:left;margin:6px 0;padding:9px 12px;border-radius:10px;border:1px solid var(--line);background:#fff;color:var(--fg);cursor:pointer;font:inherit;font-size:13.5px}
#menu button b{color:var(--run);font-family:"JetBrains Mono",monospace;font-weight:500}#menu button:hover{border-color:var(--run);background:#fff7e6}
form{display:flex;gap:10px;padding:14px 28px;border-top:1px solid var(--line);background:var(--panel)}
input{flex:1;padding:12px 16px;border-radius:12px;border:1px solid var(--line);background:#f8fafc;color:var(--fg);font:inherit;font-size:14.5px;outline:none}input:focus{border-color:var(--brand);background:#fff}
button.send{padding:10px 20px;border-radius:12px;border:0;background:var(--brand);color:#fff;font:inherit;font-weight:600;cursor:pointer}button.send:disabled{opacity:.35;cursor:default}
#board{min-height:0;overflow-y:auto;padding:18px 22px;display:flex;flex-direction:column;gap:14px;background:var(--bg)}
.pan{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}.pan h2{margin:0 0 10px;font-size:12px;color:var(--mute);letter-spacing:.6px;text-transform:uppercase;font-weight:600}
.flow{display:grid;grid-template-columns:repeat(7,1fr);gap:7px}.node{border:1px solid var(--line);border-radius:12px;padding:9px 6px;text-align:center;background:#fff}
.node .f{font-weight:700;font-size:15px}.node .t{font-size:10.5px;color:var(--mute);min-height:14px}.node .w{font-size:10.5px;color:var(--mute);margin-top:3px;font-family:"JetBrains Mono",monospace}.node .g{margin-top:7px;font-size:11px;border-radius:7px;padding:3px 4px;background:#f1f4f9;color:var(--mute);font-family:"JetBrains Mono",monospace}
.node.running{border-color:#f59e0b;background:#fffbf2}.node.waiting{border-color:#a78bfa;background:#f8f5ff}.node.done .g.ok{background:var(--okbg);color:var(--ok)}.node.failed .g,.g.bad{background:var(--badbg);color:var(--bad)}
table{width:100%;border-collapse:collapse;font-size:12.5px;font-family:"JetBrains Mono",ui-monospace,monospace}td,th{padding:4px 6px;border-bottom:1px solid #f1f4f9;text-align:left}th{color:var(--mute);font-weight:500;font-family:Inter,sans-serif}
.pbar{height:8px;border-radius:999px;background:#eef2f7;overflow:hidden;margin:6px 0 8px}.pbar i{display:block;height:100%;background:linear-gradient(90deg,#5b8def,#1f4fbf)}
.ok{color:var(--ok)}.bad{color:var(--bad)}.wait{color:var(--wait)}.mute{color:var(--mute)}
svg text{fill:var(--mute);font-size:11px}.big{font-size:22px;font-weight:700}
details summary{cursor:pointer;color:var(--mute);font-size:12.5px}
</style></head><body>
<header><div class="logo">IRIS</div><div><h1>IRIS</h1><div class="sub">symmetry-mode energy landscapes · gated agentic workflow · live run on Carbon</div></div><div class="now" id="now"></div><div class="status" id="phase"><span class="dot"></span><span id="phasetxt">ready</span></div><div class="status" id="mock" style="display:none;margin-left:8px;background:#fff4e0;color:#b45309;border-color:#f5c76a;font-weight:600">MOCK · fake VASP</div></header>
<main>
<section id="chat"><div id="msgs"></div><div id="menu" style="display:none"></div>
<form id="f"><input id="q" placeholder="Describe the transition to map — material, parent → child space groups, what to compute" autocomplete="off"><button class="send" id="send">Send</button></form></section>
<section id="board">
 <div class="pan"><h2>Workflow · gates</h2><div class="flow" id="flow"></div><div id="fixes" class="mute" style="font-size:12.5px;margin-top:10px"></div></div>
 <div class="pan" id="plan" style="display:none"><h2>Run plan</h2><div class="kv" id="plankv"></div></div>
 <div class="pan" id="jobs" style="display:none"><h2>DFT jobs · PBS · live executor</h2><div id="jobsbody"></div></div>
 <div class="pan" id="res" style="display:none"><h2>Result · energy landscape</h2><div id="resbody"></div></div>
 <div class="pan" id="tests" style="display:none"><h2>Gate tests</h2><div id="testsbody"></div></div>
</section></main>
<script>
const $=s=>document.querySelector(s);let nmsg=0,lastSig="",tlBox=null;
function esc(s){return (s||"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}
function short(p){return esc(String(p).replace(/^.*\/(IRIS_AGENT\/)/,"$1"))}
async function post(u,b){await fetch(u,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(b)})}
$("#f").onsubmit=async e=>{e.preventDefault();const v=$("#q").value.trim();if(!v)return;$("#q").value="";await post("/request",{text:v})};
function bubble(m,extraCls){const box=$("#msgs");const meta=document.createElement("div");meta.className="meta"+(m.who==="human"?" human":"");meta.textContent=(m.who==="human"?"You":"IRIS")+" · "+m.t;
 const row=document.createElement("div");row.className="row"+(m.who==="human"?" human":"");row.innerHTML=`<div class="av">${m.who==="human"?"YOU":"IRIS"}</div>`;
 const d=document.createElement("div");d.className="m"+(extraCls||"");d.textContent=m.text;row.appendChild(d);box.appendChild(meta);box.appendChild(row);tlBox=null}
function card(title,inner){const box=$("#msgs");const row=document.createElement("div");row.className="row";row.innerHTML=`<div class="av">IRIS</div><div class="card"><div class="hd">${title}</div><div class="bd">${inner}</div></div>`;box.appendChild(row);tlBox=null}
function tl(icon,cls,text,t,detail){const box=$("#msgs");if(!tlBox){const row=document.createElement("div");row.className="row";row.innerHTML=`<div class="av">IRIS</div>`;tlBox=document.createElement("div");tlBox.className="tl";row.appendChild(tlBox);box.appendChild(row)}
 const it=document.createElement("div");it.className="it";it.innerHTML=`<div class="ic ${cls}">${icon}</div><div>${text}${detail?`<div class="d">${esc(detail)}</div>`:""}</div><div class="t">${t}</div>`;tlBox.appendChild(it)}
function renderMsg(m){const x=m.text;let r;
 if(m.who==="human")return bubble(m);
 if(m.who==="executor")return tl("⚙","wait",esc(x.replace(/^\[.*?\] (\[\d+\] )?/,"")),m.t);
 if((r=x.match(/^intake \((.*?)\): (.*)$/))){const kv=r[2].split(", ").map(p=>p.split("=")).map(([k,v])=>`<div>${esc(k)}</div><div>${esc(v)}</div>`).join("");return card(`Intake · ${esc(r[1])}`,`<div class="kv">${kv}</div>`)}
 if((r=x.match(/^sources: (.*?) \| verdict: (\S+)(.*)$/))){return card("Intake verdict",`<div class="kv"><div>fields from</div><div>${esc(r[1])}</div><div>verdict</div><div><span class="badge ${r[2]==="needs_new_dft"?"run":"ok"}">${esc(r[2])}</span> ${esc(r[3].replace(/^ — /,""))}</div></div>`)}
 if(x.startsWith("fetching "))return tl("↓","wait",esc(x.replace(/ -> .*$/,"")),m.t);
 if((r=x.match(/^\s*(parent|child): (\S+)(?: \(API id (\S+)\))? #(\d+), (\d+) atoms, a,b,c = \[(.*?)\] Å, E above hull (\S+) meV\/atom/))){return card(`${r[1]} structure · Materials Project`,`<div class="kv"><div>id</div><div class="mono">${esc(r[2])}${r[3]?` <span class="mute">(API id ${esc(r[3])})</span>`:""}</div><div>space group</div><div>#${r[4]}</div><div>cell</div><div>${r[5]} atoms · a,b,c = ${esc(r[6])} Å</div><div>E above hull</div><div>${esc(r[7])} meV/atom</div></div>`)}
 if(x.startsWith("config written"))return tl("✓","ok","run config written",m.t,x.replace(/^config written: /,"").replace(/^.*\/(IRIS_AGENT\/)/,"$1"));
 if((r=x.match(/^plan: (.*)$/))){const parts=r[1].split(", ");return card("Run plan",`<div class="chips">${parts.map(p=>`<span class="chip">${esc(p)}</span>`).join("")}</div>`)}
 if(x.startsWith("live executor started"))return tl("⚙","wait","live executor started (submits and collects the PBS jobs)",m.t);
 if(x.startsWith("start the executor"))return tl("⚙","wait",esc(x),m.t);
 if((r=x.match(/^(f\d) (.*?) starts(.*)$/)))return tl("▶","run",`<b>${r[1]}</b> ${esc(r[2])}${esc(r[3])}`,m.t);
 if((r=x.match(/^(G\d) \((.*?)\): (PASS|FAIL \S+), (\d+)\/(\d+) tests(.*)$/))){const ok=r[3]==="PASS";return tl(ok?"✓":"✗",ok?"ok":"bad",`<b>${r[1]}</b> ${esc(r[2])} <span class="badge ${ok?"ok":"bad"}">${esc(r[3])}</span> <span class="mute">${r[4]}/${r[5]} tests</span>`,m.t,r[6].replace(/^ — /,""))}
 if(x.startsWith("recover ("))return tl("↻","fix",esc(x),m.t);
 if(x.startsWith("f3 waiting")||x.startsWith("waiting for the jobs"))return tl("◌","wait",esc(x),m.t);
 if(x.startsWith("resumed with"))return tl("⇢","wait","job-end event received "+esc(x.replace("resumed with ","")),m.t);
 if(x.startsWith("run ended"))return tl("■","ok",esc(x),m.t);
 if(x.startsWith("profile dE"))return card("Energy profile",`<div class="mono" style="font-size:13px">${esc(x.replace("profile dE(lambda) meV/f.u.: ",""))} <span class="mute">meV/f.u., λ = 0 … 1</span></div>`);
 if((r=x.match(/^barrier (\S+) meV\/f\.u\. at lambda = (\S+) \((L\d+)\); dE\(end\) = (\S+) meV\/f\.u\.; (.*)$/)))return card("Result",`<div class="kv"><div>barrier</div><div><span class="big">${r[1]}</span> meV/f.u. at λ = ${r[2]} (${r[3]})</div><div>ΔE(child)</div><div>${r[4]} meV/f.u.</div><div>meaning</div><div class="mute">${esc(r[5])}</div></div>`);
 if(x.startsWith("Landau fit (4mm"))return card("Landau fit · 4mm invariants",`<div class="mono" style="font-size:13px">${esc(x.replace("Landau fit (4mm invariants): ",""))}</div>`);
 if((r=x.match(/^minimum (\S+) meV\/f\.u\. at \(Q1, Q2\) = \((\S+), (\S+)\) Å on the (\w+); (.*)$/)))return card("Result",`<div class="kv"><div>minimum</div><div><span class="big">${r[1]}</span> meV/f.u. at (Q1, Q2) = (${r[2]}, ${r[3]}) Å on the ${r[4]}</div><div>computed</div><div>${esc(r[5])}</div></div>`);
 if((r=x.match(/^f6: (\d+) of (\d+) reported numbers/)))return card("Skeptic · f6",`<span class="badge ${r[1]===r[2]?"ok":"bad"}">${r[1]} of ${r[2]} reported numbers re-derived and equal</span>`);
 if(x.startsWith("  MISMATCH"))return tl("✗","bad",esc(x.trim()),m.t);
 if(x.startsWith("files:"))return tl("▤","ok","files",m.t,x.replace("files: ","").replace(/^.*\/(IRIS_AGENT\/)/,"$1"));
 if(x.startsWith("DRY RUN"))return card("Dry run",esc(x));
 if(x.startsWith("MOCK RUN"))return card("Mock run",`<span class="badge run">rehearsal</span> ${esc(x.replace("MOCK RUN — ",""))}`);
 bubble(m)}
function renderMsgs(ms){for(;nmsg<ms.length;nmsg++)renderMsg(ms[nmsg]);const box=$("#msgs");box.scrollTop=box.scrollHeight}
function fmtDur(s){s=Math.max(0,Math.round(s));return s<60?`${s}s`:(s<3600?`${Math.floor(s/60)}m ${String(s%60).padStart(2,"0")}s`:`${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m`)}
let serverNow=0,clientAt=0;
function renderNow(st){const d=$("#now");if(!st.now){d.innerHTML="";return}const el=st.now.since?fmtDur((serverNow+(Date.now()-clientAt)/1000)-st.now.since):"";d.innerHTML=`<b>${esc(st.now.title)}</b>${st.now.doing?` · ${esc(st.now.doing)}`:""}${el?` · <span class="el">${el}</span>`:""}`}
function renderFlow(nodes){$("#flow").innerHTML=Object.entries(nodes).map(([n,v])=>{const g=v.gate;const gl=g?`${g.id} ${g.ok?"PASS":g.code}`:`G${n[1]}`;const w=v.wall_s!=null?fmtDur(v.wall_s):(v.status==="running"&&v.started?fmtDur((serverNow+(Date.now()-clientAt)/1000)-v.started):"");
 return `<div class="node ${v.status}" title="${esc(v.doing||"")}"><div class="f">${n}</div><div class="t">${v.title}</div><div class="w">${w||"&nbsp;"}</div><div class="g ${g?(g.ok?"ok":"bad"):""}" title="${g?esc(g.detail):""}">${gl}${g?` <span class="mute">${g.n_pass}/${g.n}</span>`:""}</div></div>`}).join("")}
function renderPlan(c){if(!c)return;$("#plan").style.display="";$("#plankv").innerHTML=[["thread",c.thread],["transition",`#${c.parent_sg} → #${c.child_sg}`],c.plane?["plane",`${c.plane.irrep} (Q1, Q2) at the fixed parent cell, ${c.plane.n}×${c.plane.n} grid to ${c.plane.q_max}·A_p, 4mm orbit representatives`]:["path",`${c.n_points} points, straight line in amplitude + strain`],
 ["DFT",`${c.gga}, ENCUT ${c.encut} eV, k ${c.kpoints.join("×")}, ${c.per_fu} f.u./cell`],["jobs",`${c.part_size} statics per PBS job · ${c.submit}`],["points",short(c.stored)],c.network?["network check",c.network.join(", ")]:["",""]].filter(x=>x[0]).map(([k,v])=>`<div>${k}</div><div>${v}</div>`).join("")}
function renderJobs(j){if(!j||(!j.parts&&!j.n_parts))return;$("#jobs").style.display="";const parts=j.parts||[];const ended=parts.filter(p=>p.status==="ended").length,sub=parts.length,tot=Math.max(j.n_parts||0,sub);
 const dur=p=>{if(!p.submitted)return"";const a=Date.parse(p.submitted),b=p.ended?Date.parse(p.ended):Date.now();return fmtDur((b-a)/1000)};
 const rows=parts.map(p=>`<tr><td>r${p.round} p${p.part}</td><td>${p.job_id||"—"}</td><td>${p.frames??""}</td><td class="${p.status==="ended"?(p.code?"bad":"ok"):"wait"}">${p.status}${p.code?" "+p.code:""}</td><td>${dur(p)}</td><td class="mute">${(p.submitted||"").slice(11,19)} → ${(p.ended||"").slice(11,19)}</td></tr>`).join("");
 $("#jobsbody").innerHTML=`<div class="mute" style="font-size:12.5px">${ended} of ${tot} parts ended · ${sub} submitted</div><div class="pbar"><i style="width:${tot?100*ended/tot:0}%"></i></div><table><tr><th>part</th><th>job id</th><th>statics</th><th>status</th><th>elapsed</th><th>submitted → ended (UTC)</th></tr>${rows||`<tr><td colspan=6 class="wait">waiting for the executor to submit ${j.n_parts} parts…</td></tr>`}</table>`}
const COLS=["#1f4fbf","#db2777","#059669","#d97706","#7c3aed"];
function profileSvg(series,barrier){const W=440,H=240,px=46,py=18;const all=series.flatMap(s=>s.E);const ymin=Math.min(0,...all),ymax=Math.max(0,...all);
 const sy=v=>py+(H-2*py)*(1-(v-ymin)/((ymax-ymin)||1)),sx=l=>px+(W-px-14)*l;const y0=sy(0);
 let svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:560px"><line x1="${px}" y1="${y0}" x2="${W-14}" y2="${y0}" stroke="#cbd5e1"/>`;
 series.forEach((s,k)=>{const pts=s.L.map((l,i)=>`${sx(l).toFixed(1)},${sy(s.E[i]).toFixed(1)}`);svg+=`<polyline points="${pts.join(" ")}" fill="none" stroke="${COLS[k%5]}" stroke-width="${s.own?2.4:1.4}" opacity="${s.own?1:.75}"/>`;
  pts.forEach((p,i)=>{const[x,y]=p.split(",");svg+=`<circle cx="${x}" cy="${y}" r="${s.own?3.5:2.5}" fill="${s.own&&i===barrier?"#f59e0b":COLS[k%5]}"/>`})});
 [ymin,0,ymax].forEach(v=>{svg+=`<text x="4" y="${sy(v)+4}">${v.toFixed(1)}</text>`});[0,0.5,1].forEach(l=>{svg+=`<text x="${sx(l)-6}" y="${H-3}">λ=${l}</text>`});
 return svg+`<text x="${px}" y="12">ΔE (meV/f.u.)</text></svg><div style="font-size:12px;margin:2px 0 4px">${series.map((s,k)=>`<span style="color:${COLS[k%5]};margin-right:12px">● ${s.name}${s.own?" (this run)":""}</span>`).join("")}</div>`}
function barsSvg(obj,unit){const ks=Object.keys(obj);if(!ks.length)return"";const W=440,H=30+ks.length*22,vmax=Math.max(...ks.map(k=>Math.abs(+obj[k])))||1;
 let svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:560px">`;ks.forEach((k,i)=>{const w=(W-150)*Math.abs(+obj[k])/vmax;svg+=`<text x="4" y="${26+i*22}">${k}</text><rect x="90" y="${14+i*22}" width="${w.toFixed(1)}" height="15" fill="#5b8def" rx="3"/><text x="${96+w}" y="${26+i*22}">${(+obj[k]).toFixed(4)} ${unit}</text>`});return svg+"</svg>"}
function divCol(v,lo,hi){const t=v<0?Math.max(-1,v/Math.abs(lo||1)):Math.min(1,v/Math.abs(hi||1));if(t<0){const u=-t;return `rgb(${Math.round(255-170*u)},${Math.round(255-130*u)},255)`}return `rgb(255,${Math.round(255-170*t)},${Math.round(255-200*t)})`}
function landauE(c,q1,q2){return c.a*(q1*q1+q2*q2)+c.b*(q1**4+q2**4)+c.c*q1*q1*q2*q2+c.d*(q1**6+q2**6)+c.e*(q1**4*q2*q2+q1*q1*q2**4)}
function niceStep(x){const p=Math.pow(10,Math.floor(Math.log10(x)));const f=x/p;return (f<1.5?1:f<3.5?2:f<7.5?5:10)*p}
function contours(m,lv,sx,sy){const c=m.coefficients,N=80,q=m.q_max_A,g=i=>-q+2*q*i/N;let out="";
 for(const lev of lv){for(let i=0;i<N;i++)for(let j=0;j<N;j++){const x0=g(i),x1=g(i+1),y0=g(j),y1=g(j+1);const a=landauE(c,x0,y0),b=landauE(c,x1,y0),cc=landauE(c,x1,y1),d=landauE(c,x0,y1);
  const pts=[];const edge=(v1,v2,X1,Y1,X2,Y2)=>{if((v1-lev)*(v2-lev)<0){const t=(lev-v1)/(v2-v1);pts.push([X1+t*(X2-X1),Y1+t*(Y2-Y1)])}};
  edge(a,b,x0,y0,x1,y0);edge(b,cc,x1,y0,x1,y1);edge(cc,d,x1,y1,x0,y1);edge(d,a,x0,y1,x0,y0);
  const L=(p1,p2)=>`<line x1="${sx(p1[0]).toFixed(1)}" y1="${sy(p1[1]).toFixed(1)}" x2="${sx(p2[0]).toFixed(1)}" y2="${sy(p2[1]).toFixed(1)}" stroke="${lev<0?"#1a2a6c":"#4a1a1a"}" stroke-width=".9" opacity=".6"/>`;
  if(pts.length>=2)out+=L(pts[0],pts[1]);if(pts.length===4)out+=L(pts[2],pts[3])}}return out}
function heatSvg(m,ap){const idx=m.grid_index,S=m.surface_meV,n=idx.length,W=520,H=470,px=54,py=22,cbw=16,cw=(W-px-cbw-40)/n,ch=(H-py-40)/n;
 const vals=S.flat().filter(v=>v!=null),vmin=Math.min(...vals),vmax=Math.max(...vals);
 const sx=q=>px+(q/m.step_A+(n-1)/2+0.5)*cw,sy=q=>py+((n-1)/2-q/m.step_A+0.5)*ch;
 let svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:600px">`;
 for(let i=0;i<n;i++)for(let j=0;j<n;j++){const v=S[i][j];if(v==null)continue;svg+=`<rect x="${(px+i*cw).toFixed(1)}" y="${(py+(n-1-j)*ch).toFixed(1)}" width="${(cw+.6).toFixed(1)}" height="${(ch+.6).toFixed(1)}" fill="${divCol(v,vmin,vmax)}"><title>Q1=${(idx[i]*m.step_A).toFixed(3)} Q2=${(idx[j]*m.step_A).toFixed(3)} Å  ΔE=${v.toFixed(2)} meV/f.u.</title></rect>`}
 const st=niceStep((vmax-vmin)/10);const lv=[];for(let k=Math.ceil(vmin/st);k*st<vmax;k++)if(k!==0)lv.push(k*st);if(vmin<0)lv.push(vmin*0.5,vmin*0.9);svg+=contours(m,lv,sx,sy);
 svg+=`<line x1="${sx(-m.q_max_A)}" y1="${sy(0)}" x2="${sx(m.q_max_A)}" y2="${sy(0)}" stroke="#fff" stroke-dasharray="3,3" opacity=".8"/><line x1="${sx(0)}" y1="${sy(-m.q_max_A)}" x2="${sx(0)}" y2="${sy(m.q_max_A)}" stroke="#fff" stroke-dasharray="3,3" opacity=".8"/><line x1="${sx(-m.q_max_A)}" y1="${sy(-m.q_max_A)}" x2="${sx(m.q_max_A)}" y2="${sy(m.q_max_A)}" stroke="#fff" stroke-dasharray="2,4" opacity=".6"/>`;
 (m.axis_profile||[]).forEach(([q])=>{svg+=`<circle cx="${sx(q)}" cy="${sy(0)}" r="2.4" fill="#111"/>`});(m.diagonal_profile||[]).forEach(([q])=>{svg+=`<circle cx="${sx(q)}" cy="${sy(q)}" r="2.4" fill="#111"/>`});
 if(ap){svg+=`<line x1="${sx(ap)}" y1="${sy(0)-9}" x2="${sx(ap)}" y2="${sy(0)+9}" stroke="#111" stroke-width="1.5"/><text x="${sx(ap)}" y="${sy(0)+22}" text-anchor="middle" style="fill:#111;font-size:10.5px">A_p (child)</text>`}
 const mn=m.minimum;svg+=`<circle cx="${sx(mn.Q1)}" cy="${sy(mn.Q2)}" r="7" fill="none" stroke="#fff" stroke-width="2.5"/><circle cx="${sx(mn.Q1)}" cy="${sy(mn.Q2)}" r="7" fill="none" stroke="#111" stroke-width="1.2"/>`;
 svg+=`<text x="${sx(m.q_max_A)-12}" y="${sy(0)-9}" text-anchor="end" style="fill:#111;font-weight:600">[001] axis</text><text x="${sx(m.q_max_A)-12}" y="${sy(m.q_max_A)+4}" text-anchor="end" style="fill:#111;font-weight:600">[101] diagonal</text>`;
 const ticks=[-m.q_max_A,-m.q_max_A/2,0,m.q_max_A/2,m.q_max_A];ticks.forEach(q=>{svg+=`<text x="${sx(q)}" y="${H-24}" text-anchor="middle">${q.toFixed(2)}</text><text x="${px-6}" y="${sy(q)+4}" text-anchor="end">${q.toFixed(2)}</text>`});
 svg+=`<text x="${(px+n*cw/2).toFixed(0)}" y="${H-8}" text-anchor="middle">Q1 = ${esc(m.components[0])} (Å)</text><text transform="translate(12,${(py+n*ch/2).toFixed(0)}) rotate(-90)" text-anchor="middle">Q2 = ${esc(m.components[1])} (Å)</text>`;
 const cbx=px+n*cw+14,cbh=n*ch;for(let k=0;k<40;k++){const v=vmax-(k+.5)/40*(vmax-vmin);svg+=`<rect x="${cbx}" y="${(py+k*cbh/40).toFixed(1)}" width="${cbw}" height="${(cbh/40+.5).toFixed(1)}" fill="${divCol(v,vmin,vmax)}"/>`}
 const cby=v=>py+(vmax-v)/((vmax-vmin)||1)*cbh;const labs=[[vmax,cby(vmax)+4],[vmin,cby(vmin)+4]];if(vmin<0&&vmax>0&&Math.min(cby(0)-cby(vmax),cby(vmin)-cby(0))>14)labs.push([0,cby(0)+4]);labs.forEach(([v,y])=>{svg+=`<text x="${cbx+cbw+3}" y="${y}" style="font-size:10px">${v.toFixed(1)}</text>`});svg+=`<text transform="translate(${cbx+cbw+30},${py+cbh/2}) rotate(90)" text-anchor="middle" style="font-size:10px">ΔE (meV/f.u.)</text></svg>`;
 return svg}
function readPlane(m,r){const mn=m.minimum,ax=m.E_axis_min_meV,dg=m.E_diag_min_meV;const pref=mn.where==="diagonal"?"[101]-type (Amm2) direction":mn.where==="axis"?"[001]-type (P4mm) direction":mn.where;
 return `<div style="margin:8px 0 2px;font-size:13.5px"><b>Reading.</b> At the fixed cubic cell the Γ-mode landscape has its minimum ${mn.E_meV.toFixed(1)} meV/f.u. below cubic on the ${pref}; the lowest computed points are ${ax.toFixed(1)} on the axis and ${dg==null?"—":dg.toFixed(1)} on the diagonal, i.e. the two directions differ by ${dg==null?"—":Math.abs(ax-dg).toFixed(1)} meV/f.u. in this plane (c − 2b = ${m.anisotropy_c_minus_2b.toFixed(0)}: ${m.anisotropy_c_minus_2b>0?"axis favoured":"diagonal favoured"}). ${r.points?r.points.length:""} statics computed; the other ${m.n_full_points-(r.points?r.points.length:0)} cells are symmetry images.</div>`}
function renderPlane(r){const m=r.model;$("#res").style.display="";const c=m.coefficients,mn=m.minimum,rep=r.report||{};const ap=(r.irreps||{})[m.irrep];
 $("#resbody").innerHTML=heatSvg(m,ap)+readPlane(m,r)+`<div class="kv" style="margin-top:10px"><div>Landau fit</div><div class="mono" style="font-size:12.5px">a=${c.a.toFixed(1)} b=${c.b.toFixed(1)} c=${c.c.toFixed(1)} d=${c.d.toFixed(1)} e=${c.e.toFixed(1)} <span class="mute">meV/f.u. per Åⁿ · ${esc(m.terms)}</span></div><div>rms / max res</div><div>${m.rms_meV.toFixed(3)} / ${m.max_abs_res_meV.toFixed(3)} meV/f.u.</div><div>anisotropy c−2b</div><div>${m.anisotropy_c_minus_2b.toFixed(1)} → ${m.anisotropy_c_minus_2b>0?"axis ([001]-type) favoured":"diagonal ([101]-type) favoured"}</div><div>minimum</div><div><span class="big">${mn.E_meV.toFixed(2)}</span> meV/f.u. at (Q1, Q2) = (${mn.Q1.toFixed(3)}, ${mn.Q2.toFixed(3)}) Å, on the ${mn.where}</div><div>computed minima</div><div>axis ${m.E_axis_min_meV.toFixed(2)} · diagonal ${m.E_diag_min_meV==null?"—":m.E_diag_min_meV.toFixed(2)} meV/f.u.</div><div>irreps</div><div>${esc(Object.entries(r.irreps||{}).map(([k,v])=>`${k} ${(+v).toFixed(3)} Å`).join(", "))}</div><div>f6 re-derived</div><div class="${rep.n_ok===rep.n_numbers?"ok":"bad"}">${rep.n_ok??"?"} of ${rep.n_numbers??"?"} reported numbers equal</div></div>`+
 ((r.points||[]).length?`<details style="margin-top:8px"><summary>computed points (${r.points.length} orbit representatives)</summary><table style="margin-top:6px"><tr><th>point</th><th>Q1 (Å)</th><th>Q2 (Å)</th><th>mult.</th><th>ΔE (meV/f.u.)</th><th>SCF</th><th>SG</th></tr>${r.points.map(p=>{const q=Object.values(p.Q||{});return `<tr><td>${p.name}</td><td>${(+q[0]).toFixed(3)}</td><td>${(+q[1]).toFixed(3)}</td><td>${p.multiplicity??""}</td><td>${p.dE_meV==null?"":(+p.dE_meV).toFixed(3)}</td><td>${p.scf_steps??""}</td><td>${p.sg_frame??""}</td></tr>`}).join("")}</table></details>`:"")}
function renderRes(r){if(!r||!r.model)return;if(r.model.kind==="plane2")return renderPlane(r);if(!r.model.lambda)return;$("#res").style.display="";const m=r.model;
 const series=[{name:r.path_id||"this path",L:m.lambda,E:m.dE_meV,own:true}];Object.entries(r.campaign||{}).forEach(([pid,v])=>{if(pid!==r.path_id)series.push({name:pid.split("__")[0],L:v.map(x=>x.lambda),E:v.map(x=>x.dE),own:false})});
 let svg=profileSvg(series,m.barrier_index);
 const ptab=(r.points||[]).length?`<details style="margin-top:8px"><summary>per-point energies (${r.points.length})</summary><table style="margin-top:6px"><tr><th>point</th><th>λ</th><th>E0 (eV/cell)</th><th>ΔE (meV/f.u.)</th><th>SCF</th><th>|m| μB</th><th>SG</th></tr>${r.points.map(p=>`<tr><td>${p.name}</td><td>${(+p.lambda).toFixed(3)}</td><td>${(+p.E0_eV).toFixed(6)}</td><td>${p.dE_meV==null?"":(+p.dE_meV).toFixed(3)}</td><td>${p.scf_steps??""}</td><td>${p.mag==null?"":(+p.mag).toFixed(3)}</td><td>${p.sg_frame??""}</td></tr>`).join("")}</table></details>`:"";
 const amp=`<div class="mute" style="font-size:12.5px;margin-top:10px">symmetry-mode amplitudes A_p of the child (f1, live ISODISTORT)</div>`+barsSvg(r.irreps||{},"Å")+(Object.keys(r.strain||{}).length?`<div class="mute" style="font-size:12.5px;margin-top:4px">strain modes</div>`+barsSvg(r.strain,""):"");
 const rep=r.report||{};$("#resbody").innerHTML=svg+ptab+amp+`<div class="kv" style="margin-top:10px"><div>barrier</div><div><span class="big">${m.barrier_meV.toFixed(2)}</span> meV/f.u. at λ = ${m.barrier_lambda.toFixed(3)} (${m.barrier_point})</div><div>ΔE(child)</div><div>${m.dE_end_meV.toFixed(2)} meV/f.u.</div><div>spline barrier</div><div>${m.barrier_spline.meV.toFixed(2)} meV/f.u. at λ = ${m.barrier_spline.lambda.toFixed(3)}</div><div>f6 re-derived</div><div class="${rep.n_ok===rep.n_numbers?"ok":"bad"}">${rep.n_ok??"?"} of ${rep.n_numbers??"?"} reported numbers equal</div><div>note</div><div class="mute">${esc(m.barrier_kind||"")}</div></div>`}
function renderMenu(menu){const d=$("#menu");if(!menu){d.style.display="none";return}d.style.display="";d.innerHTML=`<h3>Your decision is needed · ${menu.gate} ${menu.code} at ${menu.node}</h3><div class="d">${esc(menu.detail)}<br><span class="mute">the rule table and the sub-agent did not settle this; pick one option</span></div>`+menu.options.map(o=>`<button onclick="post('/answer',{text:'${o.id}'})"><b>${o.id}</b> — ${esc(o.text)}</button>`).join("")}
function renderTests(nodes){const rows=Object.values(nodes).filter(v=>v.gate).map(v=>v.gate.tests.map(t=>`<tr><td>${v.gate.id}</td><td>${t.test}</td><td class="${t.status==="pass"?"ok":(t.status==="fail"?"bad":"mute")}">${t.status}${t.code?" "+t.code:""}</td></tr>`).join("")).join("");if(!rows)return;$("#tests").style.display="";$("#testsbody").innerHTML=`<table><tr><th>gate</th><th>test</th><th>status</th></tr>${rows}</table>`}
let typing=null;function setTyping(on){if(on&&!typing){typing=document.createElement("div");typing.className="row";typing.innerHTML=`<div class="av">IRIS</div><div class="typing"><i></i><i></i><i></i></div>`;$("#msgs").appendChild(typing)}if(!on&&typing){typing.remove();typing=null}if(typing)$("#msgs").appendChild(typing)}
async function tick(){try{const s=await (await fetch("/state")).json();serverNow=s.server_time||Date.now()/1000;clientAt=Date.now();renderNow(s);const sig=JSON.stringify([s.messages.length,s.nodes,s.jobs,s.menu,s.phase,!!s.result]);
 renderMsgs(s.messages);setTyping(s.phase==="running"&&!s.waiting_for);renderFlow(s.nodes);if(s.jobs&&s.jobs.parts)renderJobs(s.jobs);if(sig!==lastSig){lastSig=sig;renderPlan(s.config);renderJobs(s.jobs);renderRes(s.result);renderMenu(s.menu);renderTests(s.nodes);
 $("#phase").className="status "+s.phase;$("#mock").style.display=s.mock?"":"none";$("#phasetxt").textContent=s.phase+(s.campaign?" · "+s.campaign:"");$("#fixes").innerHTML=(s.fixes||[]).map(f=>`recover (${f.level}) ${f.gate} ${f.code}: <b>${esc(f.rule)}</b> → ${f.route}`).join("<br>");
 $("#send").disabled=!(s.phase==="ready"||(s.waiting_for&&!s.menu));$("#q").placeholder=s.waiting_for?s.waiting_for:"Describe the transition to map — material, parent → child space groups, what to compute";if(s.waiting_for&&!s.menu)$("#q").focus()}}catch(e){}setTimeout(tick,1000)}
tick();
</script></body></html>"""


def serve(app: App, port: int):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("content-type", ctype + "; charset=utf-8")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/state":
                self._send(200, json.dumps({**app.state, "server_time": time.time()}, default=str))
            else:
                self._send(200, HTML, "text/html")

        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            text = (body.get("text") or "").strip()
            if self.path == "/request":
                if app.state["waiting_for"] and not app.state["menu"]:
                    app.T.answers.put(text)
                elif app.state["phase"] == "ready":
                    app.start(text)
                self._send(200, "{}")
            elif self.path == "/answer":
                app.T.answers.put(text)
                self._send(200, "{}")
            else:
                self._send(404, "{}")

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"IRIS web chat on http://localhost:{port}  (from the Mac: ssh -L {port}:localhost:{port} carbon)", flush=True)
    srv.serve_forever()


def main(argv=None):
    ap = CH.parser()
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    if a.template:
        CH.TEMPLATE = CH.TEMPLATE_PLANE = Path(a.template).expanduser().resolve()
    app = App(a)
    if a.request:
        app.start(a.request)
    serve(app, a.port)


if __name__ == "__main__":
    sys.exit(main())
