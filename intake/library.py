"""What f0's language-model step may choose from (build step 6). Everything here is read from existing files:
the 13 E1 configs (policy defaults), the system profiles in demo/staged_walkthrough/systems/ and the stored structures.
The model never sets a DFT parameter or a number other than the budget; it picks ids from these tables.
"""
from __future__ import annotations

from pathlib import Path

import yaml

AGENT = Path(__file__).resolve().parents[1]
def _cfg_dir() -> Path:
    """The E1 configs (= every policy default the build has): $IRIS_CONFIGS, else IRIS_AGENT/configs (Mac), else the
    cloud copy. The repository root comes from those configs (paths.repo_root), so no path is hard-coded here."""
    import os
    for c in (os.environ.get("IRIS_CONFIGS"), AGENT / "configs", "/tmp/claude-0/cfgs"):
        f = Path(c) / "cssni3.yaml" if c else None
        if f and f.is_file() and Path(yaml.safe_load(f.read_text())["paths"]["repo_root"]).expanduser().is_dir():
            return Path(c)
    raise FileNotFoundError("no E1 configs found (set IRIS_CONFIGS)")


CFG_DIR = _cfg_dir()
REPO = Path(yaml.safe_load((CFG_DIR / "cssni3.yaml").read_text())["paths"]["repo_root"]).expanduser()

SYSTEMS = {         # materials with a stored campaign (any other material: system "new" + its formula)
    "cssni3":   "CsSnI3, ABX3 halide perovskite",
    "ca3ti2o7": "Ca3Ti2O7, n = 2 Ruddlesden-Popper layered perovskite",
    "inmno3":   "InMnO3, hexagonal manganite (YMnO3-type)",
    "ermno3":   "ErMnO3, hexagonal manganite (YMnO3-type)",
    "bifeo3":   "BiFeO3, ABO3 perovskite multiferroic",
    "hfo2":     "HfO2 (hafnia), fluorite-derived oxide",
}

# transition table: id -> system, parent / child space group, order parameters (what the stored campaigns map)
TRANSITIONS = {
    "cssni3_221_62":   {"system": "cssni3",   "parent_sg": 221, "child_sg": 62,  "label": "Pm-3m -> Pnma, tilts M3+ (+) R4+"},
    "ca3ti2o7_139_36": {"system": "ca3ti2o7", "parent_sg": 139, "child_sg": 36,  "label": "I4/mmm -> A2_1am, rotations X3- (+) X2+ (GM5- induced)"},
    "inmno3_194_185":  {"system": "inmno3",   "parent_sg": 194, "child_sg": 185, "label": "P6_3/mmc -> P6_3cm, trimerization K3 (+) polar GM2-"},
    "ermno3_194_185":  {"system": "ermno3",   "parent_sg": 194, "child_sg": 185, "label": "P6_3/mmc -> P6_3cm, trimerization K3 (+) polar GM2-"},
    "bifeo3_221_161":  {"system": "bifeo3",   "parent_sg": 221, "child_sg": 161, "label": "Pm-3m -> R3c, polar GM4- (+) rotation R5- (six components)"},
    "hfo2_137_29":     {"system": "hfo2",     "parent_sg": 137, "child_sg": 29,  "label": "P4_2/nmc (tetragonal) -> Pca2_1 (polar orthorhombic)"},
    "hfo2_137_60":     {"system": "hfo2",     "parent_sg": 137, "child_sg": 60,  "label": "P4_2/nmc (tetragonal) -> Pbcn (non-polar orthorhombic)"},
    "hfo2_137_14":     {"system": "hfo2",     "parent_sg": 137, "child_sg": 14,  "label": "P4_2/nmc (tetragonal) -> P2_1/c (monoclinic)"},
    "hfo2_60_29":      {"system": "hfo2",     "parent_sg": 60,  "child_sg": 29,  "label": "Pbcn (non-polar orthorhombic) -> Pca2_1 (polar orthorhombic)"},
    "hfo2_60_14":      {"system": "hfo2",     "parent_sg": 60,  "child_sg": 14,  "label": "Pbcn (non-polar orthorhombic) -> P2_1/c (monoclinic)"},
}

ANALYSES = {
    "plane": "2D energy surface of two order parameters on a grid (+ Landau fit where the system has one)",
    "joint_fit": "one Landau model fitted jointly to the plane and the polar (hat) wedge",
    "grid6d": "six-component grid (polar + rotation, 3 components each), invariant-polynomial fit",
    "path": "straight-line irrep path between the two structures (10 points)",
}
# Strain policies by the PAPER's names (Methods). The E1 configs carry older code labels (policy.strain_policy: P2 for
# every fixed-lattice campaign, P5 for the hafnia paths); the label is not read by any node (the construction comes
# from policy.grid / policy.path), so the intake maps paper name -> code label and records both.
STRAIN_POLICIES = {     # the paper's names (user, 2026-10-18); notes on this build in brackets
    "P1": "fixed lattice",
    "P2": "stated cell [the stored campaigns state it: parent cell for CsSnI3, Ca3Ti2O7, BiFeO3; child cell for the manganites]",
    "P3": "strain-interpolated",
    "P4": "relaxed anchors [not implemented in this build]",
    "P5": "fixed-lattice bias statement [always applied with a fixed lattice, not a separate construction]",
}
PAPER_TO_CODE = {"P1": "P2", "P2": "P2", "P3": "P5", "P5": "P2"}   # the code labels the E1 configs use
STRAIN_OK = {"plane": {"P1", "P2", "P5"}, "joint_fit": {"P1", "P2", "P5"}, "grid6d": {"P1", "P2", "P5"}, "path": {"P3"}}
OUTPUTS = {
    "energy_surface": "the energies on the grid / path",
    "landau_coefficients": "fitted Landau / invariant coefficients",
    "stationary_points": "minima and saddles of the fitted model",
    "barrier": "path barrier and end energy",
    "d4_secondary_check": "D4: 1D scans of a secondary held at zero, to check it would not lower the energy",
    "hat_and_brim": "Mexican-hat height and brim barrier (joint fit)",
    "path_network_checks": "cross-setting and closure checks against the other stored hafnia paths",
}

# policy templates: (transition, analysis, d4 requested) -> E1 config (the only defaults the build has)
TEMPLATES = {
    ("cssni3_221_62", "plane", False): "cssni3",
    ("cssni3_221_62", "plane", True): "cssni3_d4",
    ("ca3ti2o7_139_36", "plane", False): "ca3ti2o7",
    ("inmno3_194_185", "plane", False): "inmno3",
    ("inmno3_194_185", "joint_fit", False): "inmno3_joint",
    ("ermno3_194_185", "plane", False): "ermno3",
    ("ermno3_194_185", "joint_fit", False): "ermno3_joint",
    ("bifeo3_221_161", "grid6d", False): "bifeo3",
    ("hfo2_137_29", "path", False): "hfo2_T1",
    ("hfo2_137_60", "path", False): "hfo2_T2",
    ("hfo2_137_14", "path", False): "hfo2_T3",
    ("hfo2_60_29", "path", False): "hfo2_T4",
    ("hfo2_60_14", "path", False): "hfo2_T5",
}
CONFIG_OF = {v: k for k, v in TEMPLATES.items()}

# Materials Project ids of the stored structures (the file names carry them where they exist)
MP_IDS = {"mp-614013": ("cssni3", 221), "mp-568570": ("cssni3", 62), "mp-4163": ("ca3ti2o7", 36)}


def _formula(comp: dict) -> str:
    return "".join(f"{el}{'' if n == 1 else n}" for el, n in comp.items())


def describe(d: dict) -> str:
    """Profile description for the prompt (v2, 2026-10-18): functional, magnetic order, U scheme, read from the profile
    file. No DFT numbers (cutoffs, U values, k-points) are shown. (v1 showed only the structure-family fragment, which
    was the same for every InMnO3 profile.)"""
    v = d.get("vasp") or {}
    if isinstance(v, str):
        import ast
        v = ast.literal_eval(v)
    extra = {str(k).upper(): val for k, val in (v.get("extra_incar") or {}).items()}
    fam = d.get("structure_family", "")
    gga = str(extra.get("GGA", "")).upper()
    lda = (d.get("potcar_family") or v.get("potcar_family") or "") == "PAW_LDA"
    func = "PBEsol" if gga == "PS" else "LDA" if gga == "CA" or (lda and not gga) else "PBE"
    if v.get("ldau"):
        func += "+U (" + {1: "Liechtenstein, U and J separately", 2: "Dudarev, U_eff"}.get(v.get("ldautype"), "U") + ")"
    mm = " ".join(str(x) for x in (v.get("magmom") or {}).values())
    if "afm_layers" in mm:
        mag = "G-type AFM" if "G-type" in fam else "A-type AFM (layers)"
    elif "afm_triangle" in mm:
        mag = "frustrated AFM (Mn triangle up-up-down)"
    elif mm.startswith("fm"):
        mag = "ferromagnetic"
    else:
        mag = "spin-polarized, no magnetic order set" if v.get("ispin") == 2 else "non-spin-polarized"
    return f"{func}, {mag}"


def profiles() -> dict:
    """Existing system profiles (demo/staged_walkthrough/systems/*.json): name -> system, formula, one line. A profile
    whose material has no stored campaign (yino3) is listed too: its system is 'new' with that formula."""
    import json
    out = {}
    for f in sorted((REPO / "demo/staged_walkthrough/systems").glob("*.json")):
        d = json.loads(f.read_text())
        sysname = next((s for s in SYSTEMS if f.stem.startswith(s)), "new")
        out[f.stem] = {"system": sysname, "formula": _formula(d.get("composition") or {}), "text": describe(d)}
    return out


def load_config(name: str) -> dict:
    return yaml.safe_load((CFG_DIR / f"{name}.yaml").read_text())


def template_intent(name: str) -> dict:
    """The reference intent of an E1 config (what a perfect intake returns for its expert request)."""
    c = load_config(name)
    tr, an, d4 = CONFIG_OF[name]
    outs = {"cssni3": ["energy_surface", "landau_coefficients", "stationary_points"],
            "cssni3_d4": ["energy_surface", "landau_coefficients", "stationary_points", "d4_secondary_check"],
            "ca3ti2o7": ["energy_surface", "stationary_points"],
            "inmno3": ["energy_surface", "landau_coefficients", "stationary_points"],
            "inmno3_joint": ["energy_surface", "landau_coefficients", "hat_and_brim"],
            "ermno3": ["energy_surface", "landau_coefficients", "stationary_points"],
            "ermno3_joint": ["energy_surface", "landau_coefficients", "hat_and_brim"],
            "bifeo3": ["energy_surface", "landau_coefficients", "stationary_points"]}.get(
        name, ["energy_surface", "barrier", "path_network_checks"])
    return {"system": TRANSITIONS[tr]["system"], "parent_sg": TRANSITIONS[tr]["parent_sg"],
            "child_sg": TRANSITIONS[tr]["child_sg"], "transition": tr, "analysis": an,
            "strain_policy": {"P2": "P1", "P5": "P3"}[c["policy"]["strain_policy"]],     # paper name
            "system_profile": Path(c["paths"]["system_json"]).stem, "budget": c["run"]["budget_runs"],
            "outputs": outs}
