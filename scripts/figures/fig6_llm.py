"""Fig. 6 (v3): what the language model adds to a gated workflow.
a intake; b hand-offs (rules+human vs rules+model); c where a model can be trusted (by case class); d gates."""
import sys, numpy as np, pandas as pd, matplotlib as mpl
mpl.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.patches import Patch
D="../../results/summary"; P1="../../results/frozen_2026-10-19"; OUT=sys.argv[1] if len(sys.argv)>1 else "fig6v5"
mpl.rcParams.update({"font.family":"sans-serif","font.sans-serif":["Helvetica","Arial","Liberation Sans","DejaVu Sans"],
 "font.size":7.8,"axes.spines.top":False,"axes.spines.right":False,"axes.edgecolor":"#8a8a85","axes.linewidth":0.6,
 "xtick.color":"#55554f","ytick.color":"#55554f","xtick.major.width":0.5,"ytick.major.width":0.5,"pdf.fonttype":42})
INK="#1a1a19"; MM=1/25.4
LLM="#c96f3b"; LLM2="#e3a27b"; LLM3="#3c8a6e"; LLM4="#4d6fd6"; DET="#8a8a85"; DET2="#c9c8c2"
GREEN,LGREEN,ORANGE,BLUE,LBLUE,PURPLE,LGREY,VIOLET="#1baf7a","#9fd8c1","#eb6834","#2a78d6","#9cc3ef","#6250d6","#d9dbe0","#e3dcf7"
def lab(ax,t,s,dx=-0.02,dy=1.07,pad=4):
    ax.text(dx,dy,t,transform=ax.transAxes,fontsize=10,fontweight="bold",color=INK,ha="right",va="bottom")
    ax.set_title(s,fontsize=8.2,loc="left",color=INK,pad=pad)
Esum=pd.read_csv(f"{D}/E_summary_v5.csv").set_index("model")   # + rule-based parser (2026-10-29)
Aruns=pd.read_csv(f"{P1}/A/A_runs.csv"); Aruns=Aruns[~Aruns.fault.astype(str).str.startswith("ALL")]
Acases=pd.read_csv(f"{P1}/A/A_cases.csv"); Acases=Acases[~Acases.case.astype(str).str.startswith("ALL")]
calls=pd.read_csv(f"{D}/S5_3_calls.csv"); e2=pd.read_csv(f"{D}/E2_faults_gated.csv"); e4=pd.read_csv(f"{D}/E4_faults_ungated.csv")
e9=pd.read_csv(f"{D}/E9_gate_ablation.csv"); Cop=pd.read_csv(f"{P1}/C/C_options.csv"); C2=pd.read_csv(f"{P1}/C/C2_options.csv")
kind=e9.drop_duplicates("fault").set_index("fault").fault_kind
for t in (e2,e4): t["kind"]=t.fault.map(kind)
det=e9[e9.is_detecting_gate]

fig=plt.figure(figsize=(183*MM,245*MM))
gs=fig.add_gridspec(3,2,width_ratios=[1.1,1],height_ratios=[1,1.15,0.62],wspace=0.5,hspace=0.72,left=0.17,right=0.98,top=0.935,bottom=0.115)

# (a) intake
ax=fig.add_subplot(gs[0,0])
EM=[("claude-sonnet","Sonnet 5.5 (reference)",LLM),("claude-opus","Opus 5.5",LLM2),("gpt-sol","GPT-6.1 Sol",LLM3),
    ("gemini-argon","Gemini 4 Argon",LLM4),("parser","rule-based parser",DET),("baseline","keyword lookup",DET2)]
CATS=[("all_critical_right_expert","expert"),("all_critical_right_terse","terse"),("all_critical_right_non-specialist","non-\nspecialist"),
      ("underspecified_correct","under-\nspecified\n(asks)"),("out_of_scope_refused_or_asked","out of\nscope\n(declines)"),("new_material_correct","new\nmaterial\n(flags)")]
w=0.13
for j,(m,nm,col) in enumerate(EM):
    vals=[]
    for c,_ in CATS:
        a,b=str(Esum.loc[m,c]).split("/"); vals.append(100*int(a)/int(b))
    ax.bar(np.arange(len(CATS))+(j-2.5)*w,vals,w,color=col,label=nm,edgecolor="white",lw=0.3)
ax.set_xticks(range(len(CATS)),[n for _,n in CATS],fontsize=6.4); ax.set_ylim(0,118); ax.set_ylabel("% of calls handled correctly")
ax.axvline(2.5,color="#8a8a85",lw=0.5,ls=":")
ax.text(1,104,"clear requests:\nall critical fields right",ha="center",fontsize=6.4); ax.text(4,104,"should ask,\ndecline or flag",ha="center",fontsize=6.4)
ax.legend(frameon=False,fontsize=6.6,ncol=3,loc="upper center",bbox_to_anchor=(0.5,-0.3),handlelength=1,columnspacing=0.8)
lab(ax,"a","Language models outperform a rule-based parser\non terse and non-specialist requests",dx=-0.12,dy=1.06)

# (b) hand-offs
ax=fig.add_subplot(gs[0,1])
pol=[("rules + human (no sub-agent)","rules + human",DET),("claude-sonnet","rules + language model\n+ human",LLM)]
metrics=[("completed\n(numbers identical)","completed"),("hand-offs\nto the human","handoffs"),("judgment calls\nput to the human","pubdec")]
vals={}
for k,nm,col in pol:
    g=Aruns[Aruns.setting==k]
    vals[k]=dict(completed=int((g.final_scored=="completed").sum()),handoffs=int(g.handoffs.sum()),pubdec=int(g.published_decisions.sum()))
x=np.arange(len(metrics)); bw=0.36
for j,(k,nm,col) in enumerate(pol):
    v=[vals[k][m] for _,m in metrics]
    b=ax.bar(x+(j-0.5)*bw,v,bw,color=col,label=nm,edgecolor="white",lw=0.3)
    for xi,vi in zip(x+(j-0.5)*bw,v): ax.text(xi,vi+0.8,str(vi),ha="center",fontsize=7.0,color=INK)
ax.set_xticks(x,[n for n,_ in metrics],fontsize=7.0); ax.set_ylabel("count (53 faulted runs)"); ax.set_ylim(0,46)
ax.legend(frameon=False,fontsize=6.6,loc="upper left",handlelength=1,ncol=2,bbox_to_anchor=(0.0,1.02))
lab(ax,"b","The model takes the judgment\ncalls off the human",dx=-0.14,dy=1.06)

# (c) recovery on recorded failures: policies, with judgment calls and decoy harm
ax=fig.add_subplot(gs[1,0])
cls=Acases.drop_duplicates("case").set_index("case")["class"]
G=calls[calls.variant=="guided"].copy(); G["cls"]=G.case.map(cls)
def model_lab(m,case):
    g=G[(G.model_name==m)&(G.case==case)]; return {x:(g.label==x).mean() for x in ("correct","safe","harmful")}
def det_lab(pol,case):
    g=Acases[(Acases.policy==pol)&(Acases.case==case)]; l=g.label.iloc[0]; return {x:float(l==x) for x in ("correct","safe","harmful")}
cases=sorted(cls.index)
def policy(fn_rule,fn_rest):
    out=[]
    for c in cases: out.append((cls[c], fn_rule(c) if cls[c]=="rules_off" else fn_rest(c)))
    return out
POL=[("rules only",DET,policy(lambda c:det_lab("rules_only",c),lambda c:det_lab("rules_only",c))),
     ("decision tree",DET2,policy(lambda c:det_lab("tree",c),lambda c:det_lab("tree",c))),
     ("Sonnet 5.5 alone",LLM2,policy(lambda c:model_lab("claude-sonnet",c),lambda c:model_lab("claude-sonnet",c))),
     ("GPT-6.1 Sol alone",LLM2,policy(lambda c:model_lab("gpt-sol",c),lambda c:model_lab("gpt-sol",c))),
     ("rules → Sonnet 5.5",LLM,policy(lambda c:det_lab("rules_only",c),lambda c:model_lab("claude-sonnet",c))),
     ("rules → GPT-6.1 Sol",LLM3,policy(lambda c:det_lab("rules_only",c),lambda c:model_lab("gpt-sol",c)))]
n=len(cases); ys=np.arange(len(POL))[::-1]
for y,(pn,pc,res) in zip(ys,POL):
    tot={x:sum(r[x] for _,r in res)/n*100 for x in ("correct","safe","harmful")}
    judg=sum(r["correct"] for k,r in res if k=="judgment"); dec=sum(r["harmful"] for k,r in res if k=="decoy")
    left=0
    for x,col in (("correct",GREEN),("safe",LGREEN),("harmful",ORANGE)):
        ax.barh(y,tot[x],0.62,left=left,color=col,edgecolor="white",lw=0.5)
        if tot[x]>=6: ax.text(left+tot[x]/2,y,f"{tot[x]:.0f}",ha="center",va="center",fontsize=6.8,color="white" if col!=LGREEN else INK)
        left+=tot[x]
    ax.text(112,y,f"{judg:.1f}/2",va="center",ha="center",fontsize=7.0,color=INK)
    ax.text(133,y,f"{dec:.1f}/11",va="center",ha="center",fontsize=7.0,color=ORANGE if dec>0.05 else INK)
ax.text(112,len(POL)-0.55,"judg-\nment",ha="center",va="bottom",fontsize=6.4)
ax.text(133,len(POL)-0.55,"decoy\nharm",ha="center",va="bottom",fontsize=6.4); ax.set_ylim(-0.6,len(POL)+0.25)
ax.set_yticks(ys,[p for p,_,_ in POL])
for t,(p,pc,_) in zip(ax.get_yticklabels(),POL): t.set_color(INK if pc in (DET,DET2) else pc)
ax.set_xlim(0,142); ax.set_xticks([0,20,40,60,80,100]); ax.set_xlabel("% of decisions, 53 recorded failures\n(guided prompt; 10 repeats)")
ax.spines["bottom"].set_bounds(0,100)
ax.legend(handles=[Patch(color=GREEN,label="correct"),Patch(color=LGREEN,label="safe (handed to the human)"),Patch(color=ORANGE,label="harmful")],
          frameon=False,fontsize=6.6,ncol=3,loc="upper center",bbox_to_anchor=(0.42,-0.2),handlelength=1)
lab(ax,"c","Recorded failures: rules first; the model adds\nthe judgment calls but errs on decoys",dx=-0.4,dy=1.08)

# (d) gates: errors (left) and executed options (right)
sub=gs[1,1].subgridspec(2,1,hspace=1.35)
ax=fig.add_subplot(sub[0])
g_on=e2[e2.kind=="error"]; g_rm=det[det.fault_kind=="error"]; g_off=e4[e4.kind=="error"]
# replay-only = stopped later only by a check that exists in replay alone (G6 comparison with the stored campaign, G3 frame matching)
orc=g_rm.detected_by.isin(["G6 MISMATCH","G3 UNMATCHED"])&(g_rm.verdict=="stopped")
crash=(g_rm.detected_by=="G3 NODE_ERROR")&(g_rm.verdict=="stopped")        # the crash the ablation itself causes (InMnO3, G2 removed)
rows=[("all gates",[("caught, completed",BLUE,(g_on.final=="completed").sum()),("caught, stopped",LBLUE,(g_on.final=="stopped").sum())]),
      ("catching gate off",[("caught later (production check)",VIOLET,((g_rm.verdict=="stopped")&~orc&~crash).sum()),("caught later (replay-only check)","#efeafb",orc.sum()),
                            ("harmless",LGREY,(g_rm.verdict=="harmless").sum()),("crash",PURPLE,(crash|(g_rm.verdict=="crashed")).sum()),("silent wrong result",ORANGE,(g_rm.verdict=="silent corruption").sum())]),
      ("no gates",[("harmless",LGREY,(g_off.verdict=="harmless").sum()),("crash",PURPLE,(g_off.verdict=="crashed").sum()),("silent wrong result",ORANGE,(g_off.verdict=="silent corruption").sum())])]
for y,(rn,parts) in zip([2,1,0],rows):
    left=0
    for lbn,col,n in parts:
        n=int(n)
        if n: ax.barh(y,n,0.62,left=left,color=col,edgecolor="white",lw=0.5)
        if n>=2: ax.text(left+n/2,y,str(n),ha="center",va="center",fontsize=6.8,color="white" if col in (BLUE,PURPLE,ORANGE) else INK)
        left+=n
ax.set_yticks([2,1,0],[r for r,_ in rows]); ax.set_xlim(0,30); ax.set_xlabel("30 injected errors",labelpad=1)
seen={}
for _,parts in rows:
    for lbn,col,_ in parts: seen.setdefault(lbn,col)
ax.legend(handles=[Patch(color=c,label=l) for l,c in seen.items()],frameon=False,fontsize=6.0,ncol=2,loc="upper center",bbox_to_anchor=(0.35,-0.4),handlelength=1,columnspacing=0.6)
lab(ax,"d","The gates keep wrong results\nout, whoever chooses",dx=-0.3,dy=1.15)
ax=fig.add_subplot(sub[1])
K=C2[["case","option"]].merge(Cop,on=["case","option"],how="left")
on=[("completed, correct or equivalent",GREEN,int(K.consequence.isin(["accepted-correct","accepted_equivalent_settings"]).sum())),
    ("refused by the gate, then repaired",BLUE,int((K.consequence=="gate_refused_option").sum())),
    ("stopped by a later production check",LBLUE,int(((K.consequence=="rejected")&~K.replay_oracle.astype(bool)).sum())),
    ("stopped only by a replay-only check","#efeafb",int(((K.consequence=="rejected")&K.replay_oracle.astype(bool)).sum())),
    ("completed, wrong result",ORANGE,int((K.consequence=="accepted-wrong").sum()))]
sw=C2.silent_wrong.astype(str)=="True"
off=[("completed, correct or equivalent",GREEN,int(((C2.final=="completed")&~sw).sum())),("stopped (error or no data)",LGREY,int((C2.final=="stopped").sum())),
     ("completed, wrong result",ORANGE,int(sw.sum()))]
for y,parts in [(1,on),(0,off)]:
    left=0
    for lbn,col,n in parts:
        if n: ax.barh(y,n,0.55,left=left,color=col,edgecolor="white",lw=0.5)
        if n>=4: ax.text(left+n/2,y,str(n),ha="center",va="center",fontsize=6.8,color="white" if col in (GREEN,BLUE,ORANGE) else INK)
        left+=n
ax.set_yticks([1,0],["gates on","gates off"]); ax.set_xlim(0,len(K)); ax.set_xlabel(f"{len(K)} executed non-reference options",labelpad=1)
seen={}
for lbn,col,_ in on+off: seen.setdefault(lbn,col)
ax.legend(handles=[Patch(color=c,label=l) for l,c in seen.items()],frameon=False,fontsize=6.0,ncol=2,loc="upper center",bbox_to_anchor=(0.35,-0.45),handlelength=1,columnspacing=0.6)

# (e) rules + language model + gates: what reaches the result
ax=fig.add_subplot(gs[2,:]); _p=ax.get_position(); ax.set_position([0.33,_p.y0+0.02,0.55,_p.height-0.02])
def on_out(case,opt):
    if not isinstance(opt,str) or opt=="stop": return "human"
    r=Cop[(Cop.case==case)&(Cop.option==opt)]
    if r.empty: return "human"
    return {"accepted-correct":"ok","accepted_equivalent_settings":"ok","stopped":"human","gate_refused_option":"caught","rejected":"caught","accepted-wrong":"wrong"}[r.consequence.iloc[0]]
def off_out(case,opt):
    if not isinstance(opt,str) or opt=="stop": return "human"
    r=C2[(C2.case==case)&(C2.option==opt)]
    if r.empty: return on_out(case,opt)          # reference option: not re-run without gates
    r=r.iloc[0]
    if str(r.silent_wrong)=="True": return "wrong"
    return "crash" if r.final=="stopped" else "ok"
def det_ch(pol):
    g=Acases[Acases.policy==pol].set_index("case").choice; return {c:[g.get(c)] for c in cases}
def mod_ch(m):
    g=G[G.model_name==m]; return {c:list(g[g.case==c].answered_id) for c in cases}
def hyb_ch(m):
    r=det_ch("rules_only"); mm=mod_ch(m); return {c:(r[c] if cls[c]=="rules_off" else mm[c]) for c in cases}
OC=[("ok","completed, correct",GREEN),("human","stopped for the human",LGREEN),("caught","stopped by a gate or check",LBLUE),
    ("crash","crashed",PURPLE),("wrong","completed, wrong result",ORANGE)]
ROWS=[("rules + gates",det_ch("rules_only"),on_out,DET),
      ("rules → Sonnet 5.5, no gates",hyb_ch("claude-sonnet"),off_out,LLM),
      ("rules → Sonnet 5.5 + gates (IRIS)",hyb_ch("claude-sonnet"),on_out,LLM),
      ("rules → GPT-6.1 Sol + gates",hyb_ch("gpt-sol"),on_out,LLM3)]
ye=np.arange(len(ROWS))[::-1]; E_OUT={}
for y,(rn,ch,fn,pc) in zip(ye,ROWS):
    t={k:0.0 for k,_,_ in OC}
    for c,lst in ch.items():
        for o in lst: t[fn(c,o)]+=1/len(lst)
    t={k:100*v/len(ch) for k,v in t.items()}; E_OUT[rn]=t; left=0
    for k,_,col in OC:
        if t[k]>0: ax.barh(y,t[k],0.66,left=left,color=col,edgecolor="white",lw=0.5)
        if t[k]>=4: ax.text(left+t[k]/2,y,f"{t[k]:.0f}",ha="center",va="center",fontsize=6.8,color="white" if col in (GREEN,PURPLE,ORANGE) else INK)
        left+=t[k]
    ax.text(110,y,f"{t['wrong']:.1f}%",va="center",ha="center",fontsize=7.0,fontweight="bold" if t['wrong']>0 else "normal",color=ORANGE if t['wrong']>0 else INK)
ax.text(110,len(ROWS)-0.5,"wrong result\naccepted",ha="center",va="bottom",fontsize=6.4)
ax.set_yticks(ye,[r[0] for r in ROWS])
for t,r in zip(ax.get_yticklabels(),ROWS):
    t.set_color(INK if r[3]==DET else r[3]);
    if "IRIS" in r[0]: t.set_fontweight("bold")
ax.set_xlim(0,118); ax.set_ylim(-0.6,len(ROWS)+0.35); ax.set_xticks([0,20,40,60,80,100]); ax.spines["bottom"].set_bounds(0,100)
ax.set_xlabel("% of faulted runs, 53 recorded failures\n(each choice executed in replay; model: 10 repeats)")
ax.legend(handles=[Patch(color=c,label=l) for _,l,c in OC],frameon=False,fontsize=6.6,ncol=5,loc="upper center",bbox_to_anchor=(0.4,-0.62),handlelength=1,columnspacing=0.9)
lab(ax,"e","Rules first, the model for the rest, gates on everything:\nno wrong result accepted",dx=-0.5,dy=1.06)
fig.savefig(f"{OUT}/Figure_6_LLM_v5.pdf"); fig.savefig(f"{OUT}/Figure_6_LLM_v5.png",dpi=200)
print({k:v for k,v in vals.items()}); print({k:{a:round(b,1) for a,b in v.items()} for k,v in E_OUT.items()})
