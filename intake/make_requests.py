"""Experiment E test requests (draft for approval; frozen with a hash only after approval).

  python -m intake.make_requests      # -> intake/requests.yaml, results/E/E_requests.csv

Per request: id, style, text, optional attachments (CIF names / MP ids), the reference config (an E1 config) and, per
field, the acceptable set. A field the text does not state is acceptable as null (code fills the policy default) or as
the default itself; a stated field must match. Underspecified requests: the correct answer is a clarifying question
(G0 AMBIGUOUS); out-of-scope ones: refuse (G0 OUT_OF_SCOPE) or ask.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intake.library import template_intent  # noqa: E402

CRITICAL = ["structures", "transition", "analysis", "strain_policy", "system_profile", "budget"]
FIELDS = ["system", "parent_sg", "child_sg", "transition", "analysis", "strain_policy", "system_profile", "budget",
          "outputs"]
ALL = set(FIELDS)
S_STRUCT = {"system", "parent_sg", "child_sg", "transition"}

# (id, config, style, text, attachments, fields stated in the text)
P = [
    ("E01", "cssni3", "expert", "CsSnI3 Pm-3m (#221) -> Pnma (#62): M3+ (+) R4+ tilt plane, fixed cubic cell with strain at zero, "
     "cssni3 profile, Landau fit, at most 1100 runs.", ["mp-614013", "mp-568570"], ALL - {"outputs"}),
    ("E02", "cssni3", "terse", "map the CsSnI3 octahedral-tilt landscape", [], {"system"}),
    ("E03", "cssni3", "non-specialist", "Why does cubic CsSnI3 distort into its orthorhombic low-temperature phase? "
     "Compute the energy surface of the tilting.", [], {"system"}),
    ("E04", "cssni3_d4", "expert", "CsSnI3 #221 -> #62, M3+/R4+ plane at fixed cubic cell, cssni3 profile, <= 1100 runs, plus the "
     "D4 hard-secondary check: X5+ scans at the origin, on the ring and near the child (0.8 of the child primaries).", [], ALL),
    ("E05", "cssni3_d4", "terse", "CsSnI3 tilt landscape + check the X5+ held at zero", [], {"system", "outputs"}),
    ("E06", "cssni3_d4", "non-specialist", "Compute the tilting energy map of CsSnI3, and check whether a distortion we "
     "leave out (kept at zero) would lower the energy if we let it in.", [], {"system", "outputs"}),
    ("E07", "ca3ti2o7", "expert", "Ca3Ti2O7 I4/mmm (#139) -> A2_1am (#36): X3- rotation x X2+ tilt energy surface, fixed cell, "
     "GM5- held at zero, ca3ti2o7 profile, <= 1400 runs.", ["mp-4163"], ALL - {"outputs"}),
    ("E08", "ca3ti2o7", "terse", "map the Ca3Ti2O7 rotation-tilt energy surface", [], {"system"}),
    ("E09", "ca3ti2o7", "non-specialist", "Ca3Ti2O7 is said to be a hybrid improper ferroelectric. Compute the energy map of "
     "the two octahedral rotations that make it polar.", [], {"system"}),
    ("E10", "inmno3", "expert", "P6_3/mmc -> P6_3cm InMnO3, K3-GM2- plane at Phi = 0, fixed (child) lattice, LDA+U A-AFM profile, "
     "Meier-form fit, <= 230 runs.", [], ALL - {"outputs"}),
    ("E11", "inmno3", "terse", "map the InMnO3 trimerization landscape", [], {"system"}),
    ("E12", "inmno3", "non-specialist", "How does InMnO3 become ferroelectric? Compute the energy surface.", [], {"system"}),
    ("E13", "inmno3_joint", "expert", "InMnO3 #194 -> #185: joint fit of the K3-GM2- plane (Phi = 0) and the hat wedge "
     "(Phi 0-30 deg), fixed child cell, LDA+U A-AFM profile, <= 420 runs; report the hat height and brim barrier.",
     [], ALL),
    ("E14", "inmno3_joint", "terse", "InMnO3 joint plane + hat fit", [], {"system", "analysis"}),
    ("E15", "inmno3_joint", "non-specialist", "For InMnO3, fit one energy model to both the flat trimerization-polarization "
     "map and the energies at different trimerization angles, and tell me how high the Mexican hat is.", [],
     {"system", "analysis", "outputs"}),
    ("E16", "ermno3", "expert", "P6_3/mmc -> P6_3cm ErMnO3, K3-GM2- plane at Phi = 0 plus the GM2- axis, fixed child lattice, "
     "LDA+U A-AFM profile (ermno3_aafm), Meier-form fit, <= 240 runs.", [], ALL - {"outputs"}),
    ("E17", "ermno3", "terse", "map the ErMnO3 trimerization landscape", [], {"system"}),
    ("E18", "ermno3", "non-specialist", "How does ErMnO3 become ferroelectric? Compute the energy surface.", [], {"system"}),
    ("E19", "ermno3_joint", "expert", "ErMnO3 #194 -> #185: joint fit of the K3-GM2- plane (Phi = 0, with the GM2- axis) and the "
     "hat wedge, fixed child cell, ermno3_aafm profile, <= 420 runs; hat height and brim barrier.", [], ALL),
    ("E20", "ermno3_joint", "terse", "ErMnO3 joint plane + hat fit", [], {"system", "analysis"}),
    ("E21", "ermno3_joint", "non-specialist", "For ErMnO3, fit one energy model to both the flat trimerization-polarization map "
     "and the energies at different trimerization angles, and tell me how high the Mexican hat is.", [],
     {"system", "analysis", "outputs"}),
    ("E22", "bifeo3", "expert", "BiFeO3 Pm-3m (#221) -> R3c (#161): six-component GM4- (+) R5- grid on the 10-atom fcc(2a_c) "
     "cell, fixed cubic lattice at the child volume, PBEsol+U G-AFM profile, invariant-polynomial fit, <= 10400 runs.",
     [], ALL - {"outputs"}),
    ("E23", "bifeo3", "terse", "full 6D polarization-rotation energy grid for BiFeO3", [], {"system", "analysis"}),
    ("E24", "bifeo3", "non-specialist", "In BiFeO3 the polarization and the rotation of the oxygen octahedra can each point "
     "in three directions. Compute the energy as a function of all six and find the stable phases.", [],
     {"system", "analysis", "outputs"}),
]
HF = [("T1", "hfo2_T1", "#29", "Pca2_1", "the ferroelectric orthorhombic phase", "tetragonal", "polar orthorhombic"),
      ("T2", "hfo2_T2", "#60", "Pbcn", "its non-polar orthorhombic (Pbcn) phase", "tetragonal", "Pbcn"),
      ("T3", "hfo2_T3", "#14", "P2_1/c", "the monoclinic ground state", "tetragonal", "monoclinic"),
      ("T4", "hfo2_T4", "#29", "Pca2_1", "the ferroelectric orthorhombic phase", "Pbcn", "polar orthorhombic"),
      ("T5", "hfo2_T5", "#14", "P2_1/c", "the monoclinic ground state", "Pbcn", "monoclinic")]
n = 25
for t, cfg, csg, cname, plain, pfrom, tto in HF:
    psg, pname, pplain = ("#137", "P4_2/nmc", "tetragonal hafnia") if pfrom == "tetragonal" else \
        ("#60", "Pbcn", "the non-polar orthorhombic (Pbcn) phase of hafnia")
    P += [(f"E{n:02d}", cfg, "expert", f"HfO2 {pname} ({psg}) -> {cname} ({csg}): straight-line irrep path, amplitudes and "
           f"strain scaled together, 10 points, hfo2 (PBE) profile, <= 20 runs.", [], ALL - {"outputs"}),
          (f"E{n + 1:02d}", cfg, "terse", f"{pfrom} -> {tto} HfO2 path", [], {"system", "transition", "analysis"}),
          (f"E{n + 2:02d}", cfg, "non-specialist", f"How much energy does it take for {pplain} to turn into {plain}? "
           f"Compute the energy along the way.", [], {"system", "transition", "analysis"})]
    n += 3

U = [("U01", "map the BiFeO3 landscape", "which order parameters / analysis (only the six-component GM4- (+) R5- grid "
      "is stored)", ["bifeo3"]),
     ("U02", "hafnia transition", "which of the five stored hafnia transitions (137->29, 137->60, 137->14, 60->29, "
      "60->14) and what to compute", []),
     ("U03", "compute the energy barrier for HfO2 going to the monoclinic phase", "from which phase: tetragonal #137 "
      "(137->14) or Pbcn #60 (60->14)", ["hfo2_T3", "hfo2_T5"]),
     ("U04", "map the octahedral tilt landscape of the perovskite", "which system (CsSnI3, Ca3Ti2O7 or BiFeO3)",
      ["cssni3", "ca3ti2o7", "bifeo3"]),
     ("U05", "ErMnO3, please", "what to compute: the K3-GM2- plane or the joint plane + hat fit",
      ["ermno3", "ermno3_joint"])]
O = [("O01", "Compute the group-subgroup path from monoclinic HfO2 (P2_1/c, #14) up to tetragonal P4_2/nmc (#137), with "
      "#14 as the parent.", "no group-subgroup route: #137 is not a subgroup of #14 (the stored path runs 137 -> 14)"),
     ("O02", "Map the CsSnI3 tilt plane with Quantum ESPRESSO and a hybrid functional.",
      "unsupported engine / settings: the build runs VASP DFT profiles only (replay here)"),
     ("O03", "Run 20 ps of NVT molecular dynamics on BiFeO3 at 600 K and give me the polarization autocorrelation.",
      "MD is not an IRIS analysis")]


EXTRA_ACCEPT = {r: {"analysis": ["joint_fit"]} for r in ("E11", "E12", "E17", "E18")}   # user 2026-10-18: {plane, joint}
STATED_CELL = ("cssni3", "ca3ti2o7", "inmno3", "ermno3", "bifeo3")   # user: P1 or P2 (stated cell) for every fixed lattice
ACCEPT_CONFIGS = {"E02": ["cssni3", "cssni3_d4"], "E03": ["cssni3", "cssni3_d4"],
                  "E11": ["inmno3", "inmno3_joint"], "E12": ["inmno3", "inmno3_joint"],
                  "E17": ["ermno3", "ermno3_joint"], "E18": ["ermno3", "ermno3_joint"]}
N = [("N01", "PbTiO3 Pm-3m (#221) -> P4mm (#99): polar GM4- landscape, energy surface of two polarization components "
      "(P_z vs P_x) on a fixed cubic cell.", {"formula": "PbTiO3", "parent_sg": 221, "child_sg": 99, "analysis": ["plane"],
                                              "system_profile": [None]}),
     ("N02", "YInO3 P6_3/mmc -> P6_3cm: K3-GM2- plane at Phi = 0, fixed child cell.",
      {"formula": "YInO3", "parent_sg": 194, "child_sg": 185, "analysis": ["plane"], "system_profile": [None, "yino3"]}),
     ("N03", "Ca3Mn2O7 I4/mmm (#139) -> A2_1am (#36): X3- rotation x X2+ tilt energy surface, fixed cell.",
      {"formula": "Ca3Mn2O7", "parent_sg": 139, "child_sg": 36, "analysis": ["plane"], "system_profile": [None]})]
DEFENSIBLE = {"E10": {"system_profile": ["inmno3_aafm_v2_lt1"]}, "E13": {"system_profile": ["inmno3_aafm_v2_lt1"]}}
# inmno3_aafm_v2_lt1 = the same LDA+U A-AFM profile with LDAUTYPE 1 instead of 2: defensible for "LDA+U A-AFM"; it is
# scored as right (flag defensible_different) and end to end as "would need new DFT (profile)"


def main():
    reqs = []
    for rid, cfg, style, text, att, stated in P:
        ref = template_intent(cfg)
        acc = {}
        for f in FIELDS:
            if f == "outputs" or f in S_STRUCT or f in stated:   # every paraphrase names the system (+ the hafnia transition)
                acc[f] = [ref[f]] if f != "outputs" else ref[f]
            else:
                acc[f] = [ref[f], None]                          # unstated: null (policy default) or the default itself
        if cfg.startswith(STATED_CELL):
            acc["strain_policy"] = acc["strain_policy"][:1] + ["P2"] + acc["strain_policy"][1:]
        for f, extra in EXTRA_ACCEPT.get(rid, {}).items():
            acc[f] = acc[f][:1] + extra + acc[f][1:]
        reqs.append({"id": rid, "kind": "paraphrase", "style": style, "text": text, "attachments": att,
                     "reference_config": cfg, "reference": ref, "acceptable": acc,
                     "expected_outcome": "config", "stated": sorted(stated), "defensible": DEFENSIBLE.get(rid, {}),
                     "accept_configs": ACCEPT_CONFIGS.get(rid, [cfg])})
    for rid, text, q, defensible in U:
        reqs.append({"id": rid, "kind": "underspecified", "style": "underspecified", "text": text, "attachments": [],
                     "reference_config": None, "expected_outcome": "ask",
                     "acceptable": {"outcome": ["ask (G0 AMBIGUOUS)"], "question_about": q},
                     "defensible_guesses": defensible, "accept_configs": ["bifeo3"] if rid == "U01" else []})
    for rid, text, why in O:
        reqs.append({"id": rid, "kind": "out_of_scope", "style": "out_of_scope", "text": text, "attachments": [],
                     "reference_config": None, "expected_outcome": "refuse_or_ask",
                     "acceptable": {"outcome": ["refuse (G0 OUT_OF_SCOPE)", "ask (G0 AMBIGUOUS)"], "why": why}})
    for rid, text, acc in N:
        reqs.append({"id": rid, "kind": "new_material", "style": "new_material", "text": text, "attachments": [],
                     "reference_config": None, "expected_outcome": "needs_new_dft",
                     "acceptable": {**{k: (v if isinstance(v, list) else [v]) for k, v in acc.items()},
                                    "strain_policy": [None, "P1", "P2", "P5"],
                                    "outcome": ["valid config, G0 NEEDS_NEW_DFT (no stored data), no borrowed profile"]}})
    out = ROOT / "intake" / "requests.yaml"
    out.write_text("# Experiment E test requests -- DRAFT, not frozen (intake/make_requests.py)\n"
                   + yaml.safe_dump({"version": 1, "critical_fields": CRITICAL, "requests": reqs}, sort_keys=False,
                                    allow_unicode=True, width=140))
    (ROOT / "results" / "E").mkdir(parents=True, exist_ok=True)
    with open(ROOT / "results" / "E" / "E_requests.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "kind", "style", "text", "attachments", "reference_config", "reference", "acceptable",
                    "expected_outcome", "defensible_guesses"])
        for r in reqs:
            w.writerow([r["id"], r["kind"], r["style"], r["text"], ";".join(r["attachments"]), r["reference_config"] or "",
                        json.dumps(r.get("reference")) if r.get("reference") else "", json.dumps(r["acceptable"]),
                        r["expected_outcome"], ";".join(r.get("defensible_guesses", []))])
    print(out, len(reqs), "requests")


if __name__ == "__main__":
    main()
