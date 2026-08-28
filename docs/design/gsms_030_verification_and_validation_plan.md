# Software Verification & Validation (V&V) Plan

**Document ID:** VVP-DPMS-001  
**Project:** `dicom-py-mock-server`  
**Regulatory Standard Alignment:** IEC 62304 Clause 5.5 / 5.6 / 5.7, FDA 21 CFR 820.30  

---

## 1. Introduction & Strategy

This document outlines the Verification & Validation strategy for `dicom-py-mock-server`. The goal is to verify that all functional, performance, safety, and regulatory DICOM requirements defined in the SRS are satisfied without defect.

---

## 2. Testing Levels & Protocol Scope

### 2.1 Unit Testing (Level 1)
* **Scope:** Pydantic models (`dicom.py`), `DicomGeneratorService` dataset creation, JSON gender name synthesizer, OCR burned-in text renderer, and config loading.
* **Framework:** `pytest`.
* **Verification Methods:**
  - Verify Pydantic validation rules and field constraint enforcement.
  - Verify `pydicom` dataset tag population, transfer syntax setting, and pixel array generation.
  - Verify template SOP parsing and gender-aligned patient name synthesis using JSON first/last name lists (`PatientSex` = `M`/`F`).
  - Verify OCR text renderer injects clear burned-in text (image number, patient name, patient ID) into pixel data.

### 2.2 API & Integration Testing (Level 2)
* **Scope:** FastAPI route handlers, Uvicorn app initialization, auto-push scheduler, and endpoint responses.
* **Framework:** `starlette.testclient.TestClient` / `pytest`.
* **Verification Methods:**
  - Execute REST requests against `/health`, `/api/v1/generate`, `/api/v1/worklist/generate`, `/api/v1/autopush/start`, `/api/v1/scp/status`.
  - Validate JSON response schemas and status codes.
  - Verify 9-5 peak vs off-peak push scheduler configuration and lifecycle control.

### 2.3 DICOM Protocol Interop & System Testing (Level 3)
* **Scope:** `pynetdicom` Application Entity background server initialization, presentation context negotiation, Query/Retrieve (C-FIND, C-MOVE, C-GET), Modality Worklist (MWL C-FIND), C-STORE, headless CI/CD operation, and stress testing.
* **Verification Methods:**
  - Validate C-ECHO verification, C-FIND query, C-MOVE/C-GET retrieve, and MWL C-FIND service context handlers.
  - Execute headless CI/CD automated test suite without manual UI interactions.
  - Run high-concurrency stress tests verifying ephemeral on-the-fly DICOM generation does not saturate local disk storage.

---

## 3. Automated Test Protocols & Commands

| Test Suite | Execution Command | Description |
| :--- | :--- | :--- |
| **Code Linting & Formatting** | `uv run ruff check .` | Enforces zero linting/formatting errors. |
| **Unit & Integration Test Suite** | `uv run pytest` | Executes complete pytest suite across models, generator, API, scheduler, and main app. |
| **Headless CI/CD Automation** | `uv run pytest tests/test_headless_scp.py` | Verifies headless Mock SCP interop protocols for CI/CD pipelines. |
| **Stress & Ephemeral Storage Test** | `uv run pytest tests/test_stress.py` | Verifies high-throughput stress generation on the fly with low disk footprint. |
| **CLI Application Verification** | `uv run dicom-py-mock-server` | Verifies installed CLI entry point and Uvicorn server startup. |

---

## 4. Acceptance Criteria

1. All automated test suites (`uv run ruff check .`, `uv run pytest`) pass with **0 failures**.
2. Generated `.dcm` files parse cleanly using `pydicom.dcmread` with correct Patient, Study, Series, and PixelData elements containing OCR-readable burned-in text.
3. Gender-aligned patient names accurately match template SOP `PatientSex` inputs.
4. Ephemeral on-the-fly generation completes stress tests with modest memory usage and zero persistent disk overload.
5. No thread locking or server port leakage occurs during DICOM SCP lifecycle start/stop or background 9-5 auto-push calls.


