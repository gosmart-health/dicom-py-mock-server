#!/usr/bin/env bash
#
# synthea_loader.sh - Load Synthea FHIR JSON files into the DICOM mock server.
#
set -euo pipefail

usage() {
    cat <<EOF
Usage: $(basename "$0") [FOLDER] [EXTRA_ARGS...]

Load Synthea-generated FHIR R4 JSON bundles into the DICOM mock server.

Arguments:
  FOLDER        Path to folder containing Synthea FHIR JSON files
                (default: ../synthea/output/fhir)
  EXTRA_ARGS    Additional arguments forwarded to util/synthea_loader.py
                (e.g., --url http://127.0.0.1:8000 --chunk-size 25)

Options:
  -h, --help    Show this help message and exit

Examples:
  $(basename "$0")
  $(basename "$0") ../synthea/output/fhir
  $(basename "$0") tests/synthea/fhir --url http://127.0.0.1:8000
EOF
    exit 0
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
fi

FOLDER="${1:-../synthea/output/fhir}"

echo "Starting Synthea FHIR loader for DICOM mock server..."
echo "  Folder : ${FOLDER}"
echo ""

if [[ $# -gt 0 ]]; then
    shift
fi

uv run ./util/synthea_loader.py --folder "$FOLDER" "$@"
