#!/bin/bash
# study_uid: StudyInstanceUID to retrieve (positional, optional default).
STUDY_UID="2.25.200023691166762661957062275033337349747"
OUTPUT_DIR="./received"
# This is JPEG PROCEESS 1 (8-bit) Transfer Syntax, which is the default for WADO-RS.
TRANSFER_SYNTAX="1.2.840.10008.1.2.4.50"
TRANSFER_SYNTAX="JPEG2000_LOSSLESS"
SERVER="http://localhost:8000"
python3 wado_download_study.py -o "$OUTPUT_DIR" -t "$TRANSFER_SYNTAX" -s"$SERVER" "$STUDY_UID"
