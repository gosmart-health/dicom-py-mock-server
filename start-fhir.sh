#!/bin/bash
set -e

# Run mock server in FHIR-driven Modality Worklist (MWL) generator mode
export GOSMART_MS_WML_GENERATOR_MODE=fhir
export GOSMART_MS_FHIR_PLUGIN_URL="${GOSMART_MS_FHIR_PLUGIN_URL:-http://localhost:8088}"
# Note -200 is not minus 200, :- is the bash expansion operator
export GOSMART_MS_FHIR_RAW_COUNT="${GOSMART_MS_FHIR_RAW_COUNT:-200}"
export GOSMART_MS_FHIR_PATIENT_ID_SYSTEM="${GOSMART_MS_FHIR_PATIENT_ID_SYSTEM:-urn:oid:2.16.840.1.113883.4.3.25}"

# Start the mock server
exec uv run dicom-py-mock-server "$@"
