#!/usr/bin/env bash
#
# hapi_fhir_loader.sh - Bulk load Synthea FHIR R4 JSON files to HAPI FHIR server.
#
set -euo pipefail

usage() {
    cat <<EOF
Usage: $(basename "$0") [FOLDER] [EXTRA_ARGS...]

Bulk load Synthea-generated FHIR R4 JSON bundles into a HAPI FHIR server.
Prerequisite bundles (hospitals, practitioners) are posted first, followed by
individual patient transaction bundles.

Arguments:
  FOLDER        Path to folder containing Synthea FHIR JSON files
                (default: ../synthea/output/fhir)
  EXTRA_ARGS    Additional arguments forwarded to util/synthea_loader.py
                (e.g., --url http://10.200.0.103:8087/fhir)

Environment Variables:
  HAPI_FHIR_URL Target HAPI FHIR server base URL
                (default: http://10.200.0.103:8087/fhir)

Options:
  -h, --help    Show this help message and exit

Examples:
  $(basename "$0")
  $(basename "$0") ../synthea/output/fhir
  $(basename "$0") tests/synthea/fhir --url http://10.200.0.103:8087/fhir
EOF
    exit 0
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
fi

FOLDER="${1:-../synthea/output/fhir}"
URL="${HAPI_FHIR_URL:-http://10.200.0.103:8087/fhir}"

echo "Starting Synthea FHIR loader for HAPI FHIR server..."
echo "  Folder : ${FOLDER}"
echo "  Server : ${URL}"
echo ""

if [[ $# -gt 0 ]]; then
    shift
fi

uv run ./util/synthea_loader.py --folder "$FOLDER" --hapi-fhir --url "$URL" "$@"
