# Stage 1.1 — one BaTiO₃ static by hand

1. `bash make_potcar.sh /path/to/potpaw_PBE`
2. Edit the `#PBS` header of `run_static.pbs` to match a job that already works on Carbon.
3. `qsub -v FUNC=PBEsol run_static.pbs`
4. Pass: normal end; write the energy (eV) and the elapsed time into `logs/VALIDATION_LOG.md`.
5. Stage 1.2 later reruns exactly this static through IRIS's PBS adapter; the energy must be identical.

Settings follow the plan: Ba_sv, Ti_sv, O; ENCUT 600 eV; 8×8×8 k-mesh; EDIFF 1e-7; no spin.
