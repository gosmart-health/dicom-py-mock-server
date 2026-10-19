# Walkthrough: Synthea FHIR R4 Bundle Ingestion via Raw JSON, Coherent MWL & DICOM Generation, and Resource Queries

## Overview & Goal

Updated `dicom_py_mock_server.api.fhir_routes.load_synthea_bundles` (`POST /api/v1/synthea/load`) to accept raw JSON arrays instead of local `file://` URIs, enabling direct in-memory pushing from Docker containers and remote applications without file-system friction. Enforced prerequisite checking for hospital (`Organization`) and practitioner (`Practitioner`) resources before patient bundles are processed (returning clear error messages), preserved non-error warning handling when patient bundles contain no `ImagingStudy`, generated coherent Modality Worklist (MWL) entries and on-disk DICOM files, and updated the endpoint to return the parsed `FhirBundle` JSON objects in an array.

---

## Requirements Implemented

### 1. Raw JSON Array Ingestion & Prerequisite Checks (`SyntheaUtils`)
- **`SyntheaUtils` (`src/dicom_py_mock_server/services/synthea_utils.py`)**:
  - **`has_hospital_info(self) -> bool`**: Checks if hospital bundles are resident in memory.
  - **`has_practitioner_info(self) -> bool`**: Checks if practitioner bundles are resident in memory.
  - **`has_hospital_and_practitioner_info(self) -> bool`**: Verifies both hospital and practitioner bundles are present.
  - **`load_and_generate_from_raw_bundles(self, bundles, mwl_service, generator_service, target_dir) -> List[FhirBundle]`**:
    - **Pass 1**: Validates raw JSON dicts or `FhirBundle` instances, ingesting hospital (`Organization`) and practitioner (`Practitioner`) bundles into memory first.
    - **Prerequisite Validation**: If patient bundles are queued, verifies that hospital resources are loaded (raising `ValueError("Hospital resources must be sent first.")`) and practitioner resources are loaded (raising `ValueError("Practitioner resources must be sent first.")`).
    - **Pass 2**: Filters patient bundles for supported modalities (`CT`, `US`, `CR`). Valid patient bundles without matching `ImagingStudy` resources log a warning (`synthea_bundle_no_supported_imaging_study`) and continue without error.
    - **MWL & DICOM Generation**: Generates MWL entries and on-disk DICOM instances for matching studies.
    - **Return Value**: Returns the list of parsed and processed patient `FhirBundle` instances.

### 2. REST API Updates (`src/dicom_py_mock_server/api/fhir_routes.py`)
- **`load_synthea_bundles` (`POST /api/v1/synthea/load` & `POST /api/v1/syntha/load`)**:
  - Accepts raw JSON arrays (`list[dict[str, Any]]`) or single JSON objects.
  - Enforces prerequisite checks and maps errors to HTTP `400 Bad Request`.
  - Serializes the processed `FhirBundle` objects to JSON dictionaries and returns them as `list[dict[str, Any]]`.

### 3. REST API Direct Testing Cell in Exploration Notebook
- Added interactive test cells in `notebooks/02_synthea_explorations.ipynb` demonstrating how to load hospital, practitioner, and patient JSON assets from `tests/synthea/fhir` directly against the REST endpoint using `TestClient(app)` and inspect essential bundle details (bundle ID, total entries, resource types, patient ID/name, and imaging study modalities).

---

## Verification & Test Results

### 1. Automated Test Suite
- **SyntheaUtils Unit Tests (`tests/test_synthea_utils.py`)**:
  - `test_synthea_utils_load_and_generate_from_raw_bundles`: Tests empty payload rejection, missing hospital resources error ("Hospital resources must be sent first"), missing practitioner resources error ("Practitioner resources must be sent first"), non-imaging patient bundle warning handling, and successful patient bundle DICOM + MWL generation returning parsed `FhirBundle` instances.
- **Synthea REST API Integration Tests (`tests/test_synthea_api.py`)**:
  - `test_synthea_load_validation_errors`: Verifies HTTP `400` responses for empty payloads and malformed bundles.
  - `test_synthea_load_missing_hospital_and_practitioner_prerequisites`: Verifies HTTP `400` with clear error messages when hospital or practitioner resources are omitted.
  - `test_synthea_additive_lifecycle_and_get_endpoints`: Tests end-to-end additive raw JSON ingestion, non-imaging study warning behavior, parsed `FhirBundle` JSON return structure, MWL and DICOM file verification on disk, and resource queries via `GET /api/v1/synthea/hospitals`, `GET /api/v1/synthea/practitioner`, and `GET /api/v1/synthea/patient-bundle`.

### 2. Test Execution
```bash
uv run pytest tests/test_synthea_utils.py tests/test_synthea_api.py
```
**Result**: `14 passed`.

Full test suite:
```bash
uv run pytest tests/test_synthea_api.py tests/test_synthea_utils.py tests/test_fhir_service_request.py tests/test_api.py
```
**Result**: `32 passed`.

### 3. Code Quality & Linting Gate
```bash
uv run ruff check .
uv run ruff format --check .
```
**Result**: All checks passed!
