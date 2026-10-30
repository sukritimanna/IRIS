# CsSnI3 DFT settings: provenance of the stored inputs (2026-10-18; nothing stored was changed)

Confirmed by the user (2026-10-18): the CsSnI3 campaign ran at **ENCUT 350 eV, ISPIN 2** (KSPACING 0.17), as in the
system profile `demo/staged_walkthrough/systems/cssni3.json` (`vasp: {encut: 350, ispin: 2, kspacing: 0.17}`).

Stored files that say otherwise (read only):
| location | files | ENCUT / ISPIN written | outputs next to them |
|---|---|---|---|
| `demo/runs/cssni3_221_to_62__20260912_174105/step4_energy_plane/03_grid/*/point_*/INCAR` | 962 | 600 / 1 | none (no OUTCAR/OSZICAR/vasprun locally) |
| `.../step4_energy_plane/SUMMARY.md`, `step4.log` ("VASP: ENCUT=600 ISPIN=1 KPOINTS=Gamma 5x3x5") | 2 | 600 / 1 | — |
| `.../step4_energy_x5_{origin,ring,child}/03_grid/*/INCAR` and their SUMMARY.md | 3 x 13 | 350 / 2 | none |

Evidence that the stored plane energies were computed at 350 / 2, not with the plane INCARs as written: the cubic parent
(Q = 0) is in both data sets, and its stored energy is identical in both, -62.860443 eV/cell
(`demo/cssni3/energies/B_plane_energies.csv` id 480 = plane origin; `x5_origin_energies.csv` id 6 = X5+ amplitude 0,
written with a 350 / 2 INCAR). A 600 vs 350 eV cutoff would shift the total energy of the same structure by far more
than 1e-6 eV. Most likely the plane INCARs (generated 2026-09-12 by the staged walkthrough's step 4, whose hard-coded
template is ENCUT 600) were written locally and not the ones submitted; the cluster-side inputs are not in the repo
(`demo/cssni3/perlmutter/` holds only collect_energies.py).

Consequences in IRIS_AGENT (recorded, not changed):
- `stored_input_sets` of the CsSnI3 runs hash the 600 / 1 plane INCARs (`INCAR 1872a200cabb2c5d`, 962 frames) and the
  350 / 2 scan INCARs (`INCAR 06fda3370a4388cd`, 39 frames); G4 DFT_INCONSISTENT checks within each group only, so it
  passed. Within the stored files the two groups look inconsistent although the energies show they are not.
- The comment in the D4 config (`policy.d4.settings: own_per_scan  # the stored scans ran at ENCUT 350, ISPIN 2 (plane:
  600, 1)`) repeats the plane INCARs; by the energy identity above, the plane ran at 350 / 2 as well.
- For the manuscript: state 350 eV / ISPIN 2 for CsSnI3; the plane INCARs in the archive are not the submitted ones.
