#!/bin/bash
FOLDER="../../synthea/output/fhir"
uv run ./util/synthea_loader.py --folder "$FOLDER"
