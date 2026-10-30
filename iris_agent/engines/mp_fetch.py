"""f0 live input: fetch the parent and child structures from the Materials Project and write the CIFs IRIS reads.

Nothing stored is used. Each call records where every number came from (material id, MP energy above hull,
retrieval time, sha256 of the file written) in <out>/provenance.json next to the CIFs (parent.cif, child.cif), so the folder is
self-describing. The API key is read from the environment only (MP_API_KEY); it is never written anywhere.

  python -m iris_agent.engines.mp_fetch --formula BaTiO3 --parent 221 --child 99 --out test_runs/<thread>/inputs

CIF convention (same as the stored inputs, e.g. tests/fixtures/cssni3/cubic_mp-614013_sg221.cif): pymatgen
symmetrised CIF of the conventional standard cell, symprec 1e-3. G0 re-reads the space group with spglib.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

MP_URL = "https://api.materialsproject.org/materials/summary/"
FIELDS = "material_id,formula_pretty,symmetry,energy_above_hull,structure,theoretical,is_stable"


def query(formula: str, sg: int, api_key: str, n: int = 20) -> list[dict]:
    """All MP entries of this formula and space group, lowest energy above hull first (plain HTTPS, no mp-api)."""
    import requests
    params = {"formula": formula, "spacegroup_number": sg, "_fields": FIELDS, "_limit": n,
              "_sort_fields": "energy_above_hull"}
    r = requests.get(MP_URL, params=params, headers={"X-API-KEY": api_key, "accept": "application/json"}, timeout=60)
    r.raise_for_status()
    return r.json()["data"]


MP_SYMPREC = 0.1          # the tolerance the Materials Project uses to label symmetry


def classic_id(mp_id: str) -> str:
    """Materials Project AlphaID (database 2026-04-13+, e.g. mp-aaaaaeli) -> the classic numeric id (mp-2998).
    AlphaIDs are base-26 encodings (a = 0 ... z = 25) of the same integer; numeric ids are returned unchanged."""
    pre, _, body = mp_id.partition("-")
    if body.isdigit() or not body.isalpha():
        return mp_id
    n = 0
    for ch in body.lower():
        n = n * 26 + (ord(ch) - 97)
    return f"{pre}-{n}"


def refine(entry: dict, sg: int, symprec: float = 1e-3):
    """Conventional standard cell of the entry, symmetrised at MP's tolerance; None unless it is #sg at `symprec`."""
    from pymatgen.core import Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    s = Structure.from_dict(entry["structure"])
    for tol in (symprec, MP_SYMPREC):              # as stored first; then symmetrised at MP's tolerance
        try:
            conv = SpacegroupAnalyzer(s, symprec=tol).get_refined_structure()
            conv = SpacegroupAnalyzer(conv, symprec=symprec).get_conventional_standard_structure()
        except Exception:
            continue
        if SpacegroupAnalyzer(conv, symprec=symprec).get_space_group_number() == sg:
            return conv, tol
    return None, None


def pick(entries: list[dict], sg: int, prefer: str | None = None):
    """Lowest energy above hull whose cell IS #sg at 1e-3 (MP labels symmetry at 0.1 A; entries can be slightly distorted)."""
    if prefer:
        entries = [e for e in entries if e["material_id"] == prefer] or entries
        if entries[0]["material_id"] != prefer:
            raise SystemExit(f"{prefer} not among the candidates")
    tried = []
    for e in sorted(entries, key=lambda e: (e.get("energy_above_hull") or 0.0)):
        conv, tol = refine(e, sg)
        if conv is not None:
            return e, conv, tol, tried
        tried.append(e["material_id"])
    raise SystemExit(f"no Materials Project entry of space group #{sg} survives symmetrisation at 1e-3 A (tried {tried})")


def write_cif(entry: dict, conv, sg: int, path: Path, tol: float, symprec: float = 1e-3) -> dict:
    from pymatgen.io.cif import CifWriter
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    got = SpacegroupAnalyzer(conv, symprec=symprec).get_space_group_number()
    CifWriter(conv, symprec=symprec).write_file(str(path))
    return {"material_id": classic_id(entry["material_id"]), "material_id_api": entry["material_id"],
            "formula": entry.get("formula_pretty"),
            "mp_space_group": (entry.get("symmetry") or {}).get("number"), "space_group_written": got,
            "symmetrised_at_A": tol, "energy_above_hull_eV_per_atom": entry.get("energy_above_hull"),
            "theoretical": entry.get("theoretical"), "n_atoms_conventional": len(conv),
            "lattice_abc": list(conv.lattice.abc), "lattice_angles": list(conv.lattice.angles), "file": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def fetch(formula: str, parent_sg: int, child_sg: int, out: Path, parent_id: str | None = None,
          child_id: str | None = None, api_key: str | None = None) -> dict:
    key = api_key or os.environ.get("MP_API_KEY")
    if not key:
        raise SystemExit("MP_API_KEY is not set in the environment")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    prov = {"source": "Materials Project (api.materialsproject.org, summary endpoint)",
            "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "formula": formula,
            "roles": {}}
    for role, sg, prefer in (("parent", parent_sg, parent_id), ("child", child_sg, child_id)):
        ents = query(formula, sg, key)
        e, conv, tol, rejected = pick(ents, sg, prefer)
        info = write_cif(e, conv, sg, out / f"{role}.cif", tol)   # fixed names: the configs point at parent.cif / child.cif
        info["candidates"] = [{"material_id": classic_id(x["material_id"]), "material_id_api": x["material_id"],
                               "energy_above_hull": x.get("energy_above_hull")} for x in ents]
        info["rejected_not_sg_at_1e-3"] = [classic_id(x) for x in rejected]
        prov["roles"][role] = info
    (out / "provenance.json").write_text(json.dumps(prov, indent=1))
    return prov


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--formula", required=True)
    ap.add_argument("--parent", type=int, required=True, help="parent space group number")
    ap.add_argument("--child", type=int, required=True, help="child space group number")
    ap.add_argument("--parent-id", default=None, help="pin a Materials Project id (default: lowest E above hull)")
    ap.add_argument("--child-id", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    prov = fetch(a.formula, a.parent, a.child, Path(a.out), a.parent_id, a.child_id)
    for role, i in prov["roles"].items():
        print(f"{role}: {i['material_id']} #{i['space_group_written']} {i['n_atoms_conventional']} atoms "
              f"E_hull {i['energy_above_hull_eV_per_atom']} (symmetrised at {i['symmetrised_at_A']} A) -> {i['file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
