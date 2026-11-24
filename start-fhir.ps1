$ErrorActionPreference = "Stop"
$env:GOSMART_MS_AUTO_PUSH_HOST = "m5.local."
if (-not $env:GOSMART_MS_HOST) { $env:GOSMART_MS_HOST = "127.0.0.1" }

# Run mock server in FHIR-driven Modality Worklist (MWL) generator mode
if (-not $env:GOSMART_MS_WML_GENERATOR_MODE) { $env:GOSMART_MS_WML_GENERATOR_MODE = "fhir" }
if (-not $env:GOSMART_MS_MWL_RATE_PER_HR) { $env:GOSMART_MS_MWL_RATE_PER_HR = "100" }
if (-not $env:GOSMART_MS_FHIR_PLUGIN_URL) { $env:GOSMART_MS_FHIR_PLUGIN_URL = "http://localhost:8088" }
if (-not $env:GOSMART_MS_FHIR_PATIENT_COUNT) { $env:GOSMART_MS_FHIR_PATIENT_COUNT = "1000" }
if (-not $env:GOSMART_MS_FHIR_PATIENT_ID_SYSTEM) { $env:GOSMART_MS_FHIR_PATIENT_ID_SYSTEM = "urn:oid:2.16.840.1.113883.4.3.25" }
if (-not $env:GOSMART_MS_AUTO_PUSH_AE) { $env:GOSMART_MS_AUTO_PUSH_AE = "GOSMART_GRAPHITE" }
if (-not $env:GOSMART_MS_AUTO_PUSH_HOST) { $env:GOSMART_MS_AUTO_PUSH_HOST = "m5.local." }
if (-not $env:GOSMART_MS_AUTO_PUSH_PORT) { $env:GOSMART_MS_AUTO_PUSH_PORT = "11112" }
if (-not $env:GOSMART_MS_AUTO_PUSH_SEC) { $env:GOSMART_MS_AUTO_PUSH_SEC = "60" }

# Start the mock server
uv run dicom-py-mock-server @args
