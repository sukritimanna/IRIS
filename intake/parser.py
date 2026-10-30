"""Rule-based parser for the intake (the stronger deterministic baseline asked for in review).

Built from the same information the models receive and nothing else: the tables of intake/library.py (systems,
transitions with their Hermann-Mauguin labels, analyses, strain policies, profiles with their notes, outputs), the
JSON schema and the system prompt of intake/schema.py, and general crystallographic vocabulary (element names,
crystal systems by space-group number, common phrasings of "fixed cell" or "path"). It was written without
consulting intake/requests.yaml (one request, E01, had been seen in passing by its author while reading the code),
and is frozen with a hash in intake/PARSER.sha256 before scoring. It is scored by intake/run_parser.py with the same
scorer as the models and the keyword baseline.

Every field is filled only when a phrase in the request states it; an unstated field is left null and the build
applies the policy default, as for the models. Two systems named, or none, -> ask; a system with several stored
transitions and no structure information -> the build asks; a space-group pair not in the table -> out of scope; a
material not in the table -> system "new" with its formula.
"""
from __future__ import annotations

import os
import re

from .library import ANALYSES, SYSTEMS, TRANSITIONS, profiles

# ---- vocabulary --------------------------------------------------------------------------------------------------
ELEMENT_WORDS = {  # element symbol -> words a chemist writes for it in a compound name
    "Cs": ["cesium", "caesium"], "Sn": ["tin", "stannate"], "I": ["iodide", "iodine"],
    "Ca": ["calcium"], "Ti": ["titanium", "titanate"], "O": ["oxide", "oxygen"],
    "In": ["indium"], "Mn": ["manganese", "manganite"], "Er": ["erbium"],
    "Bi": ["bismuth"], "Fe": ["iron", "ferrite"], "Hf": ["hafnium", "hafnia"],
}
SYSTEM_WORDS = {  # extra names from the system table itself (library.SYSTEMS text)
    "hfo2": ["hafnia"],
}
CRYSTAL_SYSTEM = [  # space-group number ranges (International Tables)
    ((1, 2), "triclinic"), ((3, 15), "monoclinic"), ((16, 74), "orthorhombic"), ((75, 142), "tetragonal"),
    ((143, 167), "trigonal"), ((168, 194), "hexagonal"), ((195, 230), "cubic"),
]
POLAR_SG = {29, 36, 161, 185}          # polar child groups of the transition table (Pca2_1, A2_1am, R3c, P6_3cm)
ANALYSIS_WORDS = {
    "grid6d": [r"six[- ]component", r"\b6[- ]?d\b", r"6[- ]component", r"three components each", r"invariant[- ]polynomial",
               r"six[- ]dimensional"],
    "joint_fit": [r"\bjoint", r"\bjointly", r"\bhat\b", r"\bbrim\b", r"\bwedge\b", r"mexican"],
    "path": [r"\bpath", r"\bbarrier", r"straight[- ]line", r"\binterpolat\w* (?:path|between)", r"\b10 points"],
    "plane": [r"\bplane\b", r"\b2[- ]?d\b", r"two[- ]dimensional", r"energy surface", r"landscape", r"\bgrid\b",
              r"two[- ]irrep", r"two order parameters"],
}
STRAIN_WORDS = {
    "P4": [r"relaxed anchors?", r"\brelax\w*\b"],
    "P3": [r"strain[- ]interpolat\w*", r"interpolat\w* (?:the )?(?:strain|cell|lattice)", r"(?:cell|lattice) interpolat\w*"],
    "P1": [r"fixed (?:\w+ )?(?:lattice|cell)", r"strain (?:held |set |kept )?(?:at|to) zero", r"zero strain", r"no strain",
           r"\bclamped\b", r"frozen (?:lattice|cell)", r"(?:lattice|cell) (?:held |kept )?fixed", r"unstrained"],
    "P2": [r"stated cell", r"parent cell", r"child cell", r"(?:in|on|at) the (?:parent|child) (?:lattice|cell)"],
    "P5": [r"bias statement"],
}
OUTPUT_WORDS = {
    "d4_secondary_check": [r"\bd4\b", r"secondary", r"held at zero", r"x5\+"],
    "hat_and_brim": [r"\bhat\b", r"\bbrim\b"],
    "barrier": [r"\bbarrier"],
    "landau_coefficients": [r"landau", r"coefficient"],
    "stationary_points": [r"stationary", r"\bminima\b", r"\bminimum\b", r"\bsaddle"],
    "path_network_checks": [r"cross[- ]setting", r"\bclosure\b", r"\bnetwork\b"],
    "energy_surface": [r"energy surface", r"landscape", r"\benergies\b", r"energy (?:along|on|of)"],
}
OUT_OF_SCOPE = [r"molecular dynamics", r"\bmd\b", r"\baimd\b", r"\bphonon", r"quantum espresso", r"\bqe\b", r"\blammps\b",
                r"\bgpaw\b", r"\bcp2k\b", r"\babinit\b", r"\bcastep\b", r"\bsiesta\b", r"machine[- ]learn\w* potential",
                r"\bmlip\b", r"monte carlo", r"finite temperature", r"\bneb\b", r"nudged elastic", r"\bexperiment", r"\bxrd\b",
                r"\bsynthes"]
PROFILE_WORDS = {  # descriptor -> regex; a profile note must contain the descriptor's canonical token
    "LDA": r"\blda\b", "PBEsol": r"\bpbesol\b", "PBE": r"\bpbe\b(?!sol)", "Dudarev": r"dudarev|u_eff|\bueff\b|effective u",
    "Liechtenstein": r"liechtenstein|u and j\b|separate\w* u and j", "A-type": r"a[- ]type|afm layers|layered afm",
    "G-type": r"g[- ]type", "frustrated": r"frustrat|up[- ]up[- ]down|triangle", "ferromagnetic": r"ferromagnet|\bfm\b",
    "non-spin-polarized": r"non[- ]spin[- ]polari[sz]ed|without spin|no spin", "+U": r"\+\s*u\b|plus u\b|hubbard",
}
BUDGET = [r"(?:at most|up to|budget(?: of)?|no more than|limit(?:ed)? to|maximum(?: of)?|max\.?|≤|<=)\s*(\d[\d,]*(?:\.\d+)?k?)",
          r"(\d[\d,]*(?:\.\d+)?k?)\s*(?:dft\s+)?(?:runs?|calculations?|structures?|jobs?|frames?|points?|scf runs?|energies)\b"]


def _norm(s: str) -> str:
    s = s.replace("₀", "0").replace("₁", "1").replace("₂", "2").replace("₃", "3").replace("₄", "4").replace("₅", "5")
    s = s.replace("₆", "6").replace("₇", "7").replace("→", "->").replace("−", "-").replace("–", "-").replace("—", "-")
    return s


def _crystal_system(sg: int) -> str:
    return next(name for (a, b), name in CRYSTAL_SYSTEM if a <= sg <= b)


def _formula_elements(formula: str) -> list[str]:
    return re.findall(r"[A-Z][a-z]?", formula)


def _system_aliases() -> dict[str, list[str]]:
    """system id -> phrases that name it: formula, table names, and the element-name reading of the formula."""
    out = {}
    for sid, text in SYSTEMS.items():
        formula = text.split(",")[0].split(" ")[0]
        names = {sid, formula.lower()}
        names |= {w.lower() for w in SYSTEM_WORDS.get(sid, [])}
        els = _formula_elements(formula)
        # "cesium tin iodide", "bismuth ferrite", "hafnium oxide": every element word present, in order
        out[sid] = {"names": sorted(names, key=len, reverse=True), "elements": els}
    return out


ALIASES = _system_aliases()


def _hm_table() -> dict[str, tuple[int, str]]:
    """Hermann-Mauguin symbol (normalized) -> space-group number, from the transition labels."""
    sym = {}
    for v in TRANSITIONS.values():
        a, b = v["label"].split(",")[0].split("->")
        for name, sg in ((a, v["parent_sg"]), (b, v["child_sg"])):
            sym[_hm_norm(name.split("(")[0])] = sg
    return sym


def _hm_norm(s: str) -> str:
    return s.strip().lower().replace("_", "").replace(" ", "")


HM = _hm_table()


def _find(patterns, t: str) -> bool:
    return any(re.search(p, t) for p in patterns)


# ---- fields ------------------------------------------------------------------------------------------------------
def systems_in(t: str) -> list[str]:
    hits = []
    for sid, a in ALIASES.items():
        if any(re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", t) for n in a["names"]):
            hits.append(sid)
            continue
        # every element of the formula named in words ("indium manganite", "bismuth ferrite", "cesium tin iodide");
        # oxygen is implied by the -ide / -ite / -ate name, so it is not required. "hexagonal manganite" alone is not enough.
        words = [ELEMENT_WORDS.get(e, []) for e in a["elements"] if e != "O"]
        if words and all(any(re.search(rf"\b{w}\b", t) for w in ws) for ws in words if ws):
            hits.append(sid)
    return hits


def new_formula(t_raw: str, known: set[str]) -> str | None:
    """A chemical formula not in the table (PbTiO3, YInO3, Ca3Mn2O7): two or more element symbols with counts."""
    for m in re.finditer(r"\b((?:[A-Z][a-z]?\d*){2,})\b", _norm(t_raw)):
        f = m.group(1)
        els = _formula_elements(f)
        if len(els) >= 2 and f.lower() not in known and re.search(r"\d", f) and all(len(e) <= 2 for e in els):
            if f.lower() in {"pbe", "lda", "scf", "dft", "vasp"}:
                continue
            return f
    return None


def space_groups(t: str, system: str | None) -> list[int]:
    """Space groups in order of mention: #N / No. N / HM symbols / crystal-system words resolved on the system's table."""
    pos = []
    for m in re.finditer(r"(?:#|\bno\.?\s*|\bnumber\s*)\s*(\d{1,3})\b", t):
        pos.append((m.start(), int(m.group(1))))
    tn = t.replace("_", "")
    for name, sg in HM.items():
        for m in re.finditer(rf"(?<![a-z0-9/]){re.escape(name)}(?![a-z0-9/])", tn):
            pos.append((m.start(), sg))
    if system and not pos:                      # "tetragonal to polar orthorhombic", "cubic to the tilted phase"
        cands = {TRANSITIONS[k]["parent_sg"] for k, v in TRANSITIONS.items() if v["system"] == system} | \
                {TRANSITIONS[k]["child_sg"] for k, v in TRANSITIONS.items() if v["system"] == system}
        for m in re.finditer(r"\b(non[- ]polar|polar|ferroelectric|paraelectric)?\s*(cubic|tetragonal|orthorhombic|monoclinic|hexagonal|trigonal|rhombohedral)\b", t):
            cs = {"rhombohedral": "trigonal"}.get(m.group(2), m.group(2))
            hit = [sg for sg in cands if _crystal_system(sg) == cs]
            if len(hit) > 1 and m.group(1):
                polar = m.group(1) in ("polar", "ferroelectric")
                hit = [sg for sg in hit if (sg in POLAR_SG) == polar]
            if len(hit) == 1:
                pos.append((m.start(), hit[0]))
    return list(dict.fromkeys(sg for _, sg in sorted(pos)))


def analysis_in(t: str) -> str | None:
    for a in ("grid6d", "joint_fit", "path", "plane"):   # most specific first
        if _find(ANALYSIS_WORDS[a], t):
            return a
    return None


def strain_in(t: str) -> str | None:
    for p in ("P4", "P3", "P5", "P2", "P1"):
        if _find(STRAIN_WORDS[p], t):
            return p
    return None


def profile_in(t: str, system: str | None) -> tuple[str | None, bool]:
    """(profile id or None, ambiguous). A profile id written out wins; otherwise the stated functional / scheme /
    magnetic order must match exactly one profile of the system."""
    prof = profiles()
    for pid in sorted(prof, key=len, reverse=True):
        if pid in SYSTEMS:
            # v2 (declared rerun): a profile id that is also a system id (cssni3, inmno3, ...) is the material's name,
            # not a profile choice; the build applies the system's default profile. v1 read every "InMnO3" as the
            # profile inmno3 (6 wrong profiles on the InMnO3 requests). Set PARSER_V1=1 to reproduce v1.
            if os.environ.get("PARSER_V1") and re.search(rf"(?<![a-z0-9_]){re.escape(pid)}(?![a-z0-9_])", t):
                return pid, False
            continue
        if re.search(rf"(?<![a-z0-9_]){re.escape(pid)}(?![a-z0-9_])", t):
            return pid, False
    if system is None:
        return None, False
    mine = {k: v for k, v in prof.items() if v["system"] == system}
    said = {d for d, rx in PROFILE_WORDS.items() if re.search(rx, t)}
    if "PBEsol" in said:
        said.discard("PBE")
    said.discard("+U")
    if not said:
        return None, False
    def note_has(note: str, d: str) -> bool:
        n = note.lower()
        return {"LDA": "lda" in n, "PBEsol": "pbesol" in n, "PBE": bool(re.search(r"\bpbe\b(?!sol)", n)),
                "Dudarev": "dudarev" in n, "Liechtenstein": "liechtenstein" in n, "A-type": "a-type" in n,
                "G-type": "g-type" in n, "frustrated": "frustrated" in n, "ferromagnetic": "ferromagnetic" in n,
                "non-spin-polarized": "non-spin-polarized" in n}[d]
    match = [k for k, v in mine.items() if all(note_has(v["text"], d) for d in said)]
    if len(match) == 1:
        return match[0], False
    return None, len(match) > 1


def budget_in(t: str) -> int | None:
    for p in BUDGET:
        m = re.search(p, t)
        if m:
            s = m.group(1).replace(",", "")
            return int(float(s[:-1]) * 1000) if s.endswith("k") else int(float(s))
    return None


def outputs_in(t: str) -> list[str]:
    return [o for o, pats in OUTPUT_WORDS.items() if _find(pats, t)]


# ---- draft -------------------------------------------------------------------------------------------------------
def draft(text: str, attachments: list[str] | None = None) -> dict:
    d = {k: None for k in ("system", "formula", "parent_sg", "child_sg", "transition", "analysis", "strain_policy",
                           "system_profile", "budget", "clarify_field", "question", "out_of_scope_reason")}
    d.update({"outputs": [], "out_of_scope": False})
    t = _norm(text).lower()
    if _find(OUT_OF_SCOPE, t):
        return {**d, "out_of_scope": True, "out_of_scope_reason": "the request asks for something the stored DFT campaigns do not provide"}
    ids = [k for k in TRANSITIONS if k in t]
    hits = systems_in(t)
    if ids:
        d["system"], d["transition"] = TRANSITIONS[ids[0]]["system"], ids[0]
    elif len(hits) == 1:
        d["system"] = hits[0]
    elif len(hits) > 1:
        return {**d, "clarify_field": "system", "question": "Which system: " + ", ".join(hits) + "?"}
    else:
        f = new_formula(text, {s.split(",")[0].split(" ")[0].lower() for s in SYSTEMS.values()} | set(SYSTEMS))
        if f is None:
            return {**d, "clarify_field": "system", "question": "Which material (and which parent and child structures)?"}
        d["system"], d["formula"] = "new", f
    sgs = space_groups(t, d["system"] if d["system"] != "new" else None)
    if len(sgs) >= 2:
        d["parent_sg"], d["child_sg"] = sgs[0], sgs[1]
    elif len(sgs) == 1 and d["system"] not in (None, "new"):
        mine = [k for k, v in TRANSITIONS.items() if v["system"] == d["system"]]
        par = [k for k in mine if TRANSITIONS[k]["parent_sg"] == sgs[0]]
        chi = [k for k in mine if TRANSITIONS[k]["child_sg"] == sgs[0]]
        if len(chi) == 1 and not par:
            d["transition"] = chi[0]
        elif len(par) == 1 and not chi:
            d["transition"] = par[0]
    if d["system"] != "new" and d["parent_sg"] and d["child_sg"] and d["transition"] is None:
        tr = [k for k, v in TRANSITIONS.items() if v["system"] == d["system"]
              and (v["parent_sg"], v["child_sg"]) == (d["parent_sg"], d["child_sg"])]
        if tr:
            d["transition"] = tr[0]
        else:
            return {**d, "out_of_scope": True,
                    "out_of_scope_reason": f"no stored transition #{d['parent_sg']} -> #{d['child_sg']} for {d['system']}"}
    d["analysis"] = analysis_in(t)
    d["strain_policy"] = strain_in(t)
    d["system_profile"], amb = profile_in(t, d["system"] if d["system"] != "new" else None)
    if amb:
        return {**d, "clarify_field": "system_profile", "question": "Which system profile (functional and magnetic order)?"}
    d["budget"] = budget_in(t)
    d["outputs"] = outputs_in(t)
    return d
