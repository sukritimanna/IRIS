"""Transfer across systems: leave-one-system-out (LOSO) scoring of the deterministic deciders on the 53 frozen cases.

The rule table (recovery.yaml) and the Guidance lines of the sub-agent prompts were written with the six campaigns in
view. Supplementary Table "rules" records which campaign seeded each rule. Here every case is scored by a decider that
has never seen its own system: for a case of system S, the rules (and the Guidance branches of the tree) seeded only
by S are removed, and the retrieval memory excludes every case of S. A removed rule means "no rule -> stop", as in
production. Nothing in policies/ is changed (their FROZEN hashes still verify); this script wraps them.

  python -m eval_extra.loso            # -> results/LOSO/loso_cases.csv, loso_summary.csv, printed table
"""
from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from iris_agent import freeze_eval, subagent_bench as B  # noqa: E402
from iris_agent.llm import _policy  # noqa: E402  (verifies policies/FROZEN.sha256)
from policies import retrieval, rules_only, tree  # noqa: E402

# Campaign groups: the variants of one campaign are one system.
GROUP = {"hfo2_T1": "hfo2", "hfo2_T3": "hfo2", "hfo2_T4": "hfo2", "hfo2_T5": "hfo2", "cssni3": "cssni3",
         "cssni3_d4": "cssni3", "inmno3": "inmno3", "inmno3_joint": "inmno3", "bifeo3": "bifeo3",
         "ca3ti2o7": "ca3ti2o7", "ermno3": "ermno3"}

# Seeded-from column of the SI rule table, for the rules that have a menu option (dagger rules). A rule whose
# provenance is empty is a policy rule (Methods), not seeded by a campaign, and stays in every held-out table.
PROVENANCE = {
    "f1_no_basis_dmax_ladder": {"hfo2"},                              # HfO2 137 -> 60
    "f2_translation": {"bifeo3", "ca3ti2o7", "hfo2", "inmno3"},       # polar Gamma modes
    "f2_single_mode_sg_fixed_lattice": {"cssni3"},                     # CsSnI3 No. 55
    "f4_walltime_resubmit": {"bifeo3"},                                # 50 runs, 45 recovered
    "f4_nelm_robust_mixing": {"bifeo3"},                               # 15 runs
    "f5_thin_grid_densify": set(),                                     # Methods (policy rule)
}
RULE_CODE = {"f1_no_basis_dmax_ladder": ("G1", "NO_BASIS"), "f2_translation": ("G2", "TRANSLATION"),
             "f2_single_mode_sg_fixed_lattice": ("G2", "SINGLE_MODE_SG"), "f4_walltime_resubmit": ("G4", "WALLTIME"),
             "f4_nelm_robust_mixing": ("G4", "NELM"), "f5_thin_grid_densify": ("G5", "THIN_GRID")}


def dropped_for(group: str) -> set[str]:
    """Rules whose every seeding campaign is the held-out group."""
    return {r for r, prov in PROVENANCE.items() if prov and prov <= {group}}


def rules_loso(ctx: dict, group: str) -> tuple[str, str]:
    drop = dropped_for(group)
    rule = next((r for r in rules_only.REC["rules"] if r["node"] == rules_only.NODE[ctx["gate"]]
                 and r["code"] == ctx["code"]), None)
    if rule is not None and rule["id"] in drop:
        return "stop", f"no rule for this failure (rule {rule['id']} seeded by the held-out system)"
    return rules_only.choose(ctx)


def tree_loso(ctx: dict, group: str) -> tuple[str, str]:
    """The tree transcribes the Guidance sentences; the sentence that names a code seeded only by the held-out
    system is removed, so that code falls to the gate's default branch (stop)."""
    held = {RULE_CODE[r] for r in dropped_for(group)}
    if (ctx["gate"], ctx["code"]) in held:
        ctx = {**ctx, "code": f"{ctx['code']}__HELD_OUT"}   # no branch -> gate default
        opt, why = tree.choose(ctx)
        return opt, f"{why} (Guidance sentence seeded by the held-out system removed)"
    return tree.choose(ctx)


def retrieval_loso(ctx: dict, group: str, cases_by_id: dict) -> tuple[str, str]:
    pool = [m for m in retrieval.memory() if GROUP[cases_by_id[m["id"]]["system"]] != group
            and m["gate"] == ctx["gate"] and m["code"] == ctx["code"]]
    if not pool:
        return "stop", f"no memory case of another system with {ctx['gate']} {ctx['code']}"
    vecs = retrieval._tfidf([retrieval.tokens(ctx.get("detail", ""))] + [retrieval.tokens(m["detail"]) for m in pool])
    q = vecs[0]
    sims = [sum(q.get(t, 0.0) * x for t, x in v.items()) for v in vecs[1:]]
    best = max(range(len(pool)), key=lambda i: (round(sims[i], 12), [-ord(ch) for ch in pool[i]["id"]]))
    m = pool[best]
    if m["action"] not in ctx["options"]:
        return "stop", f"nearest {m['id']} ({cases_by_id[m['id']]['system']}) -> {m['action']}, not on the menu"
    return m["action"], f"nearest {m['id']} ({cases_by_id[m['id']]['system']}, sim {sims[best]:.3f})"


def main():
    ok, probs = freeze_eval.verify(ROOT / "eval")
    if ok is not True:
        raise SystemExit(f"eval/ not frozen / changed: {probs}")
    _policy("tree")                                         # verifies policies/FROZEN.sha256
    cases = B.load_bench_cases()
    by_id = {c["id"]: c for c in cases}
    out = ROOT / "results" / "LOSO"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in cases:
        group = GROUP[c["system"]]
        shown = B.order_for(c["id"], 0, c["menu"])
        ctx = {**{k: v for k, v in c["values"].items() if k != "options"}, "case_id": c["id"],
               "options": [o["id"] for o in shown]}
        deciders = {
            "rules_only": rules_only.choose(ctx), "rules_only_loso": rules_loso(ctx, group),
            "tree": tree.choose(ctx), "tree_loso": tree_loso(ctx, group),
            "retrieval": retrieval.choose(ctx, "all"), "retrieval_loso": retrieval_loso(ctx, group, by_id),
        }
        for pol, (choice, why) in deciders.items():
            rows.append({"policy": pol, "case": c["id"], "system": c["system"], "group": group, "split": c["split"],
                         "class": c["class"], "gate": c["values"]["gate"], "code": c["code"], "choice": choice,
                         "label": c["label_of"].get(choice, "invalid"), "dropped_rules": ";".join(sorted(dropped_for(group))),
                         "reason": why})
    with (out / "loso_cases.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    # summary: per policy (all 53) and per held-out group
    summ = []
    pols = ["rules_only", "rules_only_loso", "tree", "tree_loso", "retrieval", "retrieval_loso"]
    groups = sorted(set(GROUP.values()))
    for pol in pols:
        rr = [r for r in rows if r["policy"] == pol]
        for g in ["all"] + groups:
            sub = [r for r in rr if g == "all" or r["group"] == g]
            cnt = Counter(r["label"] for r in sub)
            summ.append({"policy": pol, "held_out": g, "n": len(sub), "correct": cnt["correct"], "safe": cnt["safe"],
                         "harmful": cnt["harmful"], "invalid": cnt["invalid"],
                         "correct_rate": round(cnt["correct"] / len(sub), 4), "harmful_rate": round(cnt["harmful"] / len(sub), 4)})
    with (out / "loso_summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0]))
        w.writeheader()
        w.writerows(summ)
    print(f"{'policy':18s} {'held-out':9s}   n  correct  safe  harmful")
    for s in summ:
        print(f"{s['policy']:18s} {s['held_out']:9s} {s['n']:3d}  {s['correct']:3d} ({s['correct_rate']:.3f})  {s['safe']:3d}  {s['harmful']:3d}")
    print("\ncases whose decision changed under LOSO:")
    base = {(r["policy"], r["case"]): r for r in rows}
    for pol in ("rules_only", "tree", "retrieval"):
        for c in cases:
            a, b = base[(pol, c["id"])], base[(pol + "_loso", c["id"])]
            if a["choice"] != b["choice"] or a["label"] != b["label"]:
                print(f"  {pol:10s} {c['id']} {c['system']:10s} {c['values']['gate']} {c['code']:16s} "
                      f"{a['choice']} ({a['label']}) -> {b['choice']} ({b['label']})   {b['reason']}")
    print(f"\nwritten: {out / 'loso_cases.csv'}, {out / 'loso_summary.csv'}")


if __name__ == "__main__":
    main()
