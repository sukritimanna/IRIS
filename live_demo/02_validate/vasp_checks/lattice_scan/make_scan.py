"""Stage 1.8 — nine-volume lattice scan of cubic BaTiO3 (one folder per lattice constant).
Usage: python make_scan.py --a0 4.00 --func PBEsol   (writes scan_PBEsol/a_3.880 ... a_4.120)"""
import argparse, os, shutil, numpy as np
p = argparse.ArgumentParser(); p.add_argument('--a0', type=float, default=4.00); p.add_argument('--func', default='PBEsol')
p.add_argument('--span', type=float, default=0.03, help='fractional half-range of a (0.03 = +/-3%%)'); a = p.parse_args()
src = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'vasp_static')
poscar = open(os.path.join(src, 'POSCAR')).read().splitlines()
out = f'scan_{a.func}'; os.makedirs(out, exist_ok=True)
for lat in np.round(np.linspace(a.a0 * (1 - a.span), a.a0 * (1 + a.span), 9), 4):
    d = os.path.join(out, f'a_{lat:.4f}'); os.makedirs(d, exist_ok=True)
    lines = poscar[:]; lines[2] = f'   {lat:.6f}   0.000000000   0.000000000'
    lines[3] = f'   0.000000000   {lat:.6f}   0.000000000'; lines[4] = f'   0.000000000   0.000000000   {lat:.6f}'
    open(os.path.join(d, 'POSCAR'), 'w').write('\n'.join(lines) + '\n')
    for f in ('KPOINTS', f'INCAR.{a.func}', 'run_static.pbs', 'POTCAR'):
        if os.path.exists(os.path.join(src, f)): shutil.copy(os.path.join(src, f), d)
    print(d)
print('submit each:  for d in', out + '/a_*; do (cd $d && qsub -v FUNC=' + a.func, 'run_static.pbs); done')
