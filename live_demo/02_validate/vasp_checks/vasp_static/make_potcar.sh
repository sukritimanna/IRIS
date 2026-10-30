#!/usr/bin/env bash
# Builds POTCAR (Ba_sv, Ti_sv, O) in this folder.
# Use the same POTCAR set as the paper's other campaigns (Supplementary Table: DFT settings):
#   PBEsol run -> potpaw_PBE ;  LDA run -> the LDA set (potpaw_LDA), if that is what the paper used.
# Usage: bash make_potcar.sh /path/to/potpaw_dir
PP=${1:?give the potpaw directory}
cat "$PP/Ba_sv/POTCAR" "$PP/Ti_sv/POTCAR" "$PP/O/POTCAR" > POTCAR && grep TITEL POTCAR
