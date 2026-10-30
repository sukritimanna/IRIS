"""Fit a third-order Birch-Murnaghan equation of state to the scan.
Usage: python fit_bm.py scan_PBEsol      (reads a_*/OUTCAR, prints a0, B0, B0')"""
import sys, glob, re, os, numpy as np
from scipy.optimize import curve_fit
rows = []
for d in sorted(glob.glob(os.path.join(sys.argv[1], 'a_*'))):
    try: E = float(re.findall(r'free  energy   TOTEN\s*=\s*(-?\d+\.\d+)', open(os.path.join(d, 'OUTCAR')).read())[-1])
    except Exception: print('no energy in', d); continue
    a = float(d.split('a_')[-1]); rows.append((a ** 3, E))
V, E = np.array(rows).T
def bm(V, E0, V0, B0, Bp):
    x = (V0 / V) ** (2 / 3)
    return E0 + 9 * V0 * B0 / 16 * ((x - 1) ** 3 * Bp + (x - 1) ** 2 * (6 - 4 * x))
p, _ = curve_fit(bm, V, E, p0=[E.min(), V[np.argmin(E)], 1.0, 4.0])
print(f'points {len(V)}  a0 = {p[1] ** (1 / 3):.4f} A   B0 = {p[2] * 160.2177:.1f} GPa   Bp = {p[3]:.2f}   RMS = {1000 * np.sqrt(np.mean((bm(V, *p) - E) ** 2)):.3f} meV')
