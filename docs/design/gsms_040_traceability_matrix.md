# Requirements Traceability Matrix (RTM)

**Document ID:** RTM-DPMS-001  
**Project:** `dicom-py-mock-server`  
**Regulatory Standard Alignment:** IEC 62304 Clause 5.1.1 / 5.2.6, FDA Design Controls  

---

## 1. Bi-Directional Traceability Overview

This matrix establishes complete bi-directional traceability linking **Software Requirements (SRS)** $\leftrightarrow$ **System Design Specs (SDS)** $\leftrightarrow$ **Software Hazards (ISO 14971)** $\leftrightarrow$ **Verification Test Suites (V&V)**.

---

## 2. Traceability Matrix

| Requirement ID | Software Requirement Description | Design Spec Module | Hazard ID | Risk Mitigation | Verification Test Method | Pass Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **REQ-FUN-001** | REST API Generation Endpoint | `src/dicom_py_mock_server/api/routes.py` | HAZ-004 | Pydantic payload validation | Integration test `test_api.py::test_generate_endpoint` | Pass |
| **REQ-FUN-002** | Pydantic Schema Validation | `src/dicom_py_mock_server/models/dicom.py` | HAZ-004 / HAZ-005 | Schema bounds & type validation | Integration test `test_api.py::test_generate_endpoint` | Pass |
| **REQ-FUN-003** | Synthetic DICOM Dataset Creation | `src/dicom_py_mock_server/services/generator.py` | HAZ-001 / HAZ-002 | FileMetaDataset & pydicom formatting | Unit test `test_generator.py::test_dicom_file_generation` | Pass |
| **REQ-FUN-004** | DICOM Verification SCP (C-ECHO) | `src/dicom_py_mock_server/services/scp.py` | HAZ-003 | pynetdicom Verification context handler | Unit test `test_api.py::test_scp_status_endpoint` | Pass |
| **REQ-FUN-005** | DICOM Query SCP (C-FIND) | `src/dicom_py_mock_server/services/scp.py` | HAZ-003 | Patient/Study Root C-FIND context handlers | Unit test `test_api.py::test_scp_status_endpoint` | Pass |
| **REQ-FUN-006** | DICOM Storage SCP (C-STORE) | `src/dicom_py_mock_server/services/scp.py` | HAZ-003 | StoragePresentationContexts registration | Unit test `test_api.py::test_scp_status_endpoint` | Pass |
| **REQ-FUN-007** | Modality Worklist SCP (MWL) | `src/dicom_py_mock_server/services/scp.py` | HAZ-003 | ModalityWorklistInformationFind registration | Unit test `test_api.py::test_scp_status_endpoint` | Pass |
| **REQ-FUN-008** | DICOM SCP Lifecycle Control | `src/dicom_py_mock_server/api/routes.py` | HAZ-003 | Non-blocking thread lifecycle control | Integration test `test_api.py::test_scp_status_endpoint` | Pass |
| **REQ-FUN-009** | Health Check Endpoint | `src/dicom_py_mock_server/api/routes.py` | - | Standard health status payload | Integration test `test_api.py::test_health_endpoint` | Pass |
| **REQ-FUN-010** | Configurable Storage Directory | `src/dicom_py_mock_server/config.py` | HAZ-005 | Target directory override setting | Unit test `test_api.py::test_generate_endpoint` | Pass |
| **REQ-FUN-011** | Template SOP Modality Worklist | `src/dicom_py_mock_server/services/generator.py` | HAZ-006 | Template SOP parsing & gender name JSON synthesizer | Unit test `test_generator.py::test_template_sop_mwl` | Pass |
| **REQ-FUN-012** | Template SOP Instance Synthesis | `src/dicom_py_mock_server/services/generator.py` | HAZ-006 | SOP baseline cloning & tag re-serialization | Unit test `test_generator.py::test_template_sop_synthesis` | Pass |
| **REQ-FUN-013** | OCR Burned-In Text Image Generation | `src/dicom_py_mock_server/services/generator.py` | HAZ-007 | High-contrast OCR text rendering engine | Unit test `test_generator.py::test_ocr_burned_in_text` | Pass |
| **REQ-FUN-014** | REST APIs for Worklist & Image Control | `src/dicom_py_mock_server/api/routes.py` | HAZ-004 | Pydantic payload validation endpoints | Integration test `test_api.py::test_worklist_generate_endpoint` | Pass |
| **REQ-FUN-015** | Query/Retrieve & MWL Scenario Support | `src/dicom_py_mock_server/services/scp.py` | HAZ-003 | C-FIND, C-MOVE, C-GET, MWL SCP handlers | Integration test `test_api.py::test_query_retrieve_scenarios` | Pass |
| **REQ-FUN-016** | Scheduled Auto-Push Delivery | `src/dicom_py_mock_server/services/scheduler.py` | HAZ-008 | 9-5 peak & off-peak background scheduler | Integration test `test_scheduler.py::test_autopush_scheduling` | Pass |
| **REQ-FUN-017** | Headless CI/CD Test Automation | `src/dicom_py_mock_server/services/scp.py` | HAZ-003 | Non-blocking headless execution thread | System test `test_headless_scp.py::test_ci_cd_headless_execution` | Pass |
| **REQ-FUN-018** | Headless Stress Testing | `src/dicom_py_mock_server/services/generator.py` | HAZ-009 | High-concurrency ephemeral synthesis | System test `test_stress.py::test_high_concurrency_stress` | Pass |
| **REQ-FUN-019** | Physician & Institution Demographics Generation | `src/dicom_py_mock_server/services/mwl_generator.py` & `person_generator.py` | HAZ-006 | Startup pool generation & random assignment | Unit test `test_physicians_and_institution.py::test_mwl_generator_initial_physician_pools` | Pass |
| **REQ-FUN-020** | Physician & Institution SOP Instance Propagation | `src/dicom_py_mock_server/services/generator.py` | HAZ-001 | SOP instance dataset attribute propagation | Unit test `test_physicians_and_institution.py::test_sop_instance_generation_attribute_propagation_from_mwl` | Pass |
| **REQ-PERF-004** | Ephemeral On-The-Fly Generation | `src/dicom_py_mock_server/services/generator.py` | HAZ-009 | In-memory byte streaming & low disk usage | System test `test_stress.py::test_ephemeral_disk_footprint` | Pass |
| **REQ-REG-001** | DICOM Part 10 Format | `src/dicom_py_mock_server/services/generator.py` | HAZ-001 / HAZ-002 | `enforce_file_format=True` setting | Unit test `test_generator.py::test_dicom_file_generation` | Pass |
| **REQ-REG-004** | Local Network Intended Use | `src/dicom_py_mock_server/main.py` | HAZ-010 | Non-clinical warning banner & OpenAPI disclaimers | Unit test `test_main.py::test_non_clinical_disclaimer` | Pass |


