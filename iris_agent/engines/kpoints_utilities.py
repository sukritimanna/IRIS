"""kpointsUtilities -- KPOINTS from the POSCAR itself, the way writePotcar builds POTCAR.

Verbatim copy of the author's kpointsUtilities.py (Bi4Ti3O12 campaign), kept here so live IRIS writes KPOINTS with
exactly the same rule: Gamma-centred mesh, k_i = ceil(|b_i| / spacing), |b_i| = 2*pi/d_i (VASP KSPACING convention),
default spacing 0.20 1/A. Only the module docstring was changed.
"""
import sys, math
import numpy as np

SPACING = 0.20   # 1/A, the value used for every Bi4Ti3O12 calculation (batch 1 KPOINTS: "KSPACING-equivalent 0.20 1/A")

def read_lattice(poscar="POSCAR"):
    with open(poscar) as f:
        lines = [next(f) for _ in range(5)]
    scale = float(lines[1].split()[0])
    lat = np.array([[float(x) for x in lines[i].split()[:3]] for i in (2, 3, 4)])
    if scale < 0:                                      # negative scale = target volume
        lat *= (abs(scale) / abs(np.linalg.det(lat))) ** (1 / 3)
    else:
        lat *= scale
    return lat

def mesh(poscar="POSCAR", spacing=SPACING):
    lat = read_lattice(poscar)
    rec = 2 * math.pi * np.linalg.inv(lat).T            # rows b_i, with a_i . b_j = 2 pi delta_ij
    return [max(1, int(math.ceil(np.linalg.norm(b) / spacing - 1e-8))) for b in rec]

def writeKpoints(poscar="POSCAR", kpoints="KPOINTS", spacing=SPACING):
    k = mesh(poscar, spacing)
    with open(kpoints, "w") as f:
        f.write(f"Gamma-centred mesh from {poscar}, spacing {spacing:.2f} 1/A (2pi incl.)\n0\nGamma\n{k[0]} {k[1]} {k[2]}\n0 0 0\n")
    return k

def read_kpoints(kpoints="KPOINTS"):
    with open(kpoints) as f:
        lines = f.read().splitlines()
    assert lines[1].strip() == "0" and lines[2].strip()[0].lower() in "gm", f"{kpoints}: not an automatic Gamma/MP mesh"
    return [int(x) for x in lines[3].split()[:3]]

def checkKpoints(poscar="POSCAR", kpoints="KPOINTS", spacing=SPACING):
    want, have = mesh(poscar, spacing), read_kpoints(kpoints)
    if want != have:
        raise ValueError(f"{kpoints} has {have} but {poscar} requires {want} at {spacing} 1/A")
    return have

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sp = SPACING
    if "--spacing" in sys.argv: sp = float(sys.argv[sys.argv.index("--spacing") + 1]); args = [a for a in args if a != str(sp)]
    cmd = args[0] if args else "write"
    if cmd == "write":
        p = args[1] if len(args) > 1 else "POSCAR"; print(p, "->", writeKpoints(p, spacing=sp))
    elif cmd == "check":
        p = args[1] if len(args) > 1 else "POSCAR"; k = args[2] if len(args) > 2 else "KPOINTS"
        print(p, "OK", checkKpoints(p, k, sp))
    elif cmd == "checkall":
        bad = 0
        for d in open(args[1]).read().split():
            try: print(d, "OK", checkKpoints(f"{d}/POSCAR", f"{d}/KPOINTS", sp))
            except Exception as e: print(d, "MISMATCH", e); bad += 1
        sys.exit(1 if bad else 0)
