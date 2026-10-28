#!/bin/bash
set -e

# Run mock server in FHIR-driven Modality Worklist (MWL) generator mode
export GOSMART_MS_WML_GENERATOR_MODE=fhir
export GOSMART_MS_FHIR_PLUGIN_URL="${GOSMART_MS_FHIR_PLUGIN_URL:-http://localhost:8088}"
export GOSMART_MS_FHIR_RAW_COUNT="${GOSMART_MS_FHIR_RAW_COUNT:-200}"

# Start the mock server
exec uv run dicom-py-mock-server "$@"
