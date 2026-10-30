# Stage 1 — check each piece on its own (nothing is recorded)

| # | Check | How | Pass |
|---|---|---|---|
| 1.1 | VASP by hand | `vasp_static/` (see its README) | normal end; energy + time logged |
| 1.2 | PBS adapter, submit and read | IRIS f₃ reruns the 1.1 static through `engines/pbs.py` | identical energy; job-end event in the audit log |
| 1.3 | PBS adapter, failures | walltime 1 min; NELM = 3 | reported as WALLTIME and SCF-limited; G₄ codes as expected |
| 1.4 | Language model from Carbon | one dummy call through IRIS's LLM wrapper | valid JSON; model ID logged |
| 1.5 | Intake f₀ | the request in `../02_rehearsal_mace/requests.txt`, stop after G₀ | Pm3̄m → P4mm; Materials Project IDs logged |
| 1.6 | Decomposition f₁ | run to G₁ | Γ₄⁻ primary, k = 1, both symmetry engines agree |
| 1.7 | Grid f₂ | run to G₂ with 17 points/axis, D5 | 165 orbits; `python orbit_count.py 17` agrees |
| 1.8 | Lattice scans | `lattice_scan/make_scan.py`, then `fit_bm.py` (PBEsol; MACE too) | smooth E(V); you approve the profile lattice |
| 1.9 | Chat + dashboard | on Carbon: `python ../tools/iris_dashboard/iris_dashboard.py --audit <stored replay>/audit.jsonl --energies <...>/energies.csv`; on the Mac: `ssh -N -L 8765:127.0.0.1:8765 carbon`, open localhost:8765 | both pages fill in from a stored replay log |
| 1.10 | Chat starts IRIS | type the request in the chat, stop after G₀ | IRIS starts; profile question appears; clicking resumes |

Write every result and every fix in `../logs/VALIDATION_LOG.md`.
