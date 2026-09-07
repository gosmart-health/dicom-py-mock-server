#!/usr/bin/env bash
#
# push_fhir.sh - Push a FHIR ServiceRequest bundle to the DICOM mock server REST endpoint.
#

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_BUNDLE="${SCRIPT_DIR}/fhir_order_bundle.json"
DEFAULT_URL="${GOSMART_MS_FHIR_URL:-http://127.0.0.1:8000/api/v1/fhir_service_request}"

usage() {
    cat <<EOF
Usage: $(basename "$0") [BUNDLE_FILE] [ENDPOINT_URL]

Push a FHIR ServiceRequest / Bundle JSON file to the DICOM mock server via HTTP POST.

Arguments:
  BUNDLE_FILE   Path to FHIR Bundle JSON file (default: util/fhir_order_bundle.json)
  ENDPOINT_URL  Target FHIR endpoint URL (default: ${DEFAULT_URL})

Options:
  -h, --help    Show this help message and exit

Examples:
  $(basename "$0")
  $(basename "$0") util/fhir_order_bundle.json
  $(basename "$0") my_order.json http://localhost:8000/api/v1/fhir_service_request
EOF
    exit 0
}

# Check for help flag
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
fi

BUNDLE_FILE="${1:-$DEFAULT_BUNDLE}"
ENDPOINT_URL="${2:-$DEFAULT_URL}"

if [[ ! -f "$BUNDLE_FILE" ]]; then
    echo "Error: FHIR bundle file not found: $BUNDLE_FILE" >&2
    exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "Error: 'curl' command is required but not found in PATH." >&2
    exit 1
fi

echo "Pushing FHIR Bundle..."
echo "  File     : ${BUNDLE_FILE}"
echo "  Endpoint : ${ENDPOINT_URL}"
echo ""

format_json() {
    local raw="$1"
    if command -v jq >/dev/null 2>&1; then
        echo "$raw" | jq .
    elif command -v python3 >/dev/null 2>&1; then
        echo "$raw" | python3 -m json.tool 2>/dev/null || echo "$raw"
    else
        echo "$raw"
    fi
}

# Execute curl request and capture HTTP status code + response body
HTTP_RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST "${ENDPOINT_URL}" \
    -H "Content-Type: application/json" \
    --data-binary @"${BUNDLE_FILE}") || CURL_EXIT=$?

CURL_EXIT="${CURL_EXIT:-0}"

if [[ "$CURL_EXIT" -ne 0 ]]; then
    echo "[ERROR] Connection failed (curl exit code: ${CURL_EXIT})." >&2
    echo "        Could not reach server at ${ENDPOINT_URL}." >&2
    echo "        Ensure the DICOM mock server is running ('uv run dicom-py-mock-server')." >&2
    exit 1
fi

# Separate body from HTTP status code
BODY=$(echo "$HTTP_RESPONSE" | sed '$d')
STATUS_CODE=$(echo "$HTTP_RESPONSE" | tail -n1)

if [[ "$STATUS_CODE" == "200" ]]; then
    echo "[OK] FHIR Bundle accepted (HTTP 200):"
    echo ""
    format_json "$BODY"
    exit 0
elif [[ "$STATUS_CODE" == "422" ]]; then
    echo "[REJECTED] Modality or validation rejected (HTTP 422):" >&2
    echo "" >&2
    format_json "$BODY" >&2
    exit 1
elif [[ "$STATUS_CODE" == "000" ]]; then
    echo "[ERROR] Connection failed. Could not reach server at ${ENDPOINT_URL}." >&2
    echo "        Ensure the DICOM mock server is running ('uv run dicom-py-mock-server')." >&2
    exit 1
else
    echo "[ERROR] Unexpected HTTP response (status code: ${STATUS_CODE}):" >&2
    echo "" >&2
    format_json "$BODY" >&2
    exit 1
fi

