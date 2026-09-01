# Software Requirements Specification (SRS)

**Document ID:** SRS-DPMS-001  
**Project:** `dicom-py-mock-server`  
**Regulatory Standard Alignment:** IEC 62304 Clause 5.2, FDA 21 CFR 820.30  

---

## 1. Scope & Purpose

This document specifies the functional, performance, security, and interface requirements for the `dicom-py-mock-server` application. The software provides a RESTful web service and DICOM SCP network services to generate synthetic DICOM datasets and simulate medical imaging PACS/Modality behaviors for testing and development. 

**Intended Use & Operational Scope:**
- The software is intended to operate as a Mock SCP within local networks for headless test automation in CI/CD pipelines and stress testing.
- **Important Note:** This tool is intended for local network testing only. It is **not** intended even for clinical uptime evaluation (consult [GoSmart.health](https://gosmart.health) for clinical implementations).

---

## 2. Functional Requirements (REQ-FUN)

| Requirement ID | Title | Description | Priority |
| :--- | :--- | :--- | :--- |
| **REQ-FUN-001** | REST API Generation Endpoint | The system SHALL provide a POST `/api/v1/generate` endpoint to trigger synthetic DICOM object creation. | High |
| **REQ-FUN-002** | Pydantic Schema Validation | The system SHALL validate incoming REST payload requests using Pydantic models (`PatientModel`, `StudyModel`, `SeriesModel`, `MockDicomRequest`). | High |
| **REQ-FUN-003** | Synthetic DICOM Dataset Creation | The system SHALL construct valid `pydicom.FileDataset` objects with proper DICOM File Meta Information, Patient/Study/Series tags, and synthetic image pixel data. | High |
| **REQ-FUN-004** | DICOM Verification SCP (C-ECHO) | The system SHALL respond to DICOM C-ECHO verification requests via `pynetdicom`. | High |
| **REQ-FUN-005** | DICOM Query SCP (C-FIND) | The system SHALL respond to C-FIND queries for Patient Root, Study Root, and Modality Worklist information models. | High |
| **REQ-FUN-006** | DICOM Storage SCP (C-STORE) | The system SHALL accept incoming C-STORE requests for standard DICOM Storage SOP classes. | High |
| **REQ-FUN-007** | Modality Worklist SCP (MWL) | The system SHALL provide Modality Worklist C-FIND query service context handlers. | High |
| **REQ-FUN-008** | DICOM SCP Lifecycle Control | The system SHALL allow starting, stopping, and querying the DICOM SCP listener via REST endpoints (`/api/v1/scp/start`, `/api/v1/scp/stop`, `/api/v1/scp/status`). | High |
| **REQ-FUN-009** | Health Check Endpoint | The system SHALL provide a GET `/health` endpoint returning server health, application name, and version. | Medium |
| **REQ-FUN-010** | Configurable Storage Directory | The system SHALL allow configuring target disk storage paths for generated DICOM datasets via `AppConfig`. | Medium |
| **REQ-FUN-011** | Template SOP Modality Worklist | The system SHALL generate synthesized DICOM Modality Worklist (MWL) items based on template SOP instances, populated with realistic gender-aligned patient names (supporting configurable JSON name lists for gender-specific first names and common US last names). | High |
| **REQ-FUN-012** | Template SOP Instance Synthesis | The system SHALL generate synthesized DICOM SOP Instances based on user-supplied template SOP instances. | High |
| **REQ-FUN-013** | OCR Burned-In Text Image Generation | The system SHALL generate pixel data containing clear burned-in text specifying image number, patient name, and patient ID, optimized for basic OCR automated verification of image reception integrity. | High |
| **REQ-FUN-014** | REST APIs for Worklist & Image Control | The system SHALL expose dedicated REST API endpoints to programmatically control and trigger generation of Modality Worklists and synthetic DICOM image series. | High |
| **REQ-FUN-015** | Query/Retrieve & MWL Scenario Support | The system SHALL support comprehensive testing of DICOM Modality Worklist and Query/Retrieve (C-FIND, C-MOVE, C-GET) interaction workflows. | High |
| **REQ-FUN-016** | Scheduled Auto-Push Delivery | The system SHALL support automated background image push capabilities mimicking daily 9-5 peak activity schedules and slower off-peak generation intervals. | High |
| **REQ-FUN-017** | Headless CI/CD Test Automation | The system SHALL support fully headless execution as a Mock SCP for integration into CI/CD test automation pipelines. | High |
| **REQ-FUN-018** | Headless Stress Testing | The system SHALL support high-concurrency stress testing scenarios for DICOM network interactions and generation pipelines. | High |
| **REQ-FUN-019** | Physician & Institution Demographics Generation | The system SHALL generate 3 Referring Physician, 3 Performing Physician, and 3 Reading Physician names with configurable `GOSMART_MS_PN_SUFFIX` (default `_GSH`), support default institution name `GORMART_MS_INSTITUTION_NAME` (default `GO SMART CLINIC`), and randomly assign physicians into synthesized Modality Worklist (MWL) entries. | High |
| **REQ-FUN-020** | Physician & Institution SOP Instance Propagation | The system SHALL propagate Referring Physician (`0008,0090`), Performing Physician (`0008,1050`), Reading Physician (`0008,1060`), and Institution Name (`0008,0080`) attributes to all synthesized DICOM SOP instances and C-MOVE / push operations. | High |
| **REQ-FUN-021** | C-STORE Association CSV Audit Logging | The system SHALL record an audit CSV file on local storage (`GORMART_MS_CSV_PATH`, default `./csv`) upon completion of C-STORE transfers per association, named `<yyyymmddhhmmss>_<AE_Title>.csv` in UTC, with header columns `Date,Time,Destination AE,Status,Patient Name,Patient ID,Accession Number,Study UID,Series UID,Instance UID,Transfer Rate kb/s` and statuses `Accepted, Rejected, No Connection, Dropped`. | High |
| **REQ-FUN-022** | Deterministic ITU-T X.667 2.25 DICOM UID Generation | The system SHALL generate standards-compliant DICOM UIDs under root `2.25.` (`2.25.<u128>`) using SHA-1 (UUIDv5) or MD5 (UUIDv3) over a persistent namespace, hierarchically deriving StudyInstanceUID from `PatientName`, `PatientID`, `AccessionNumber`, SeriesInstanceUID from `StudyUID` + `SeriesNumber`, and SOPInstanceUID from `SeriesUID` + `InstanceNumber`, without exposing PHI. | High |
| **REQ-FUN-023** | Transfer Syntax Encoding & Raw-First Pipeline | The system SHALL construct full raw image matrices with test patterns and burned-in metadata strings before in-place encoding/compression across all supported transfer syntaxes (RAW, JPEG, JPEG2000 Lossless, JPEG2000 Lossy, RLE), retaining deterministic SOPInstanceUIDs and advertising all supported presentation contexts during network SCP/SCU operations. | High |
| **REQ-FUN-024** | DICOMweb QIDO-RS Query Services | The system SHALL provide standard DICOMweb QIDO-RS search endpoints (`/dicomweb/studies`, `/dicomweb/studies/{studyUID}/series`, `/dicomweb/series`, `/dicomweb/studies/{studyUID}/series/{seriesUID}/instances`, `/dicomweb/instances`) returning standard DICOM JSON (`application/dicom+json`) with filtering on PatientID, PatientName, AccessionNumber, StudyDate, ModalitiesInStudy, StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID, limit, and offset across synthesized and stored datasets. | High |
| **REQ-FUN-025** | DICOMweb WADO-RS Retrieve & Transfer Syntax Negotiation | The system SHALL provide standard DICOMweb WADO-RS retrieve endpoints (`/dicomweb/studies/{studyUID}[/series/{seriesUID}[/instances/{instanceUID}]]` and `.../metadata`) returning `multipart/related; type="application/dicom"` or `application/dicom+json` metadata, dynamically transcoding instances into the requested transfer syntax specified via HTTP `Accept` headers or query parameters (RAW, JPEG, JPEG2000 Lossless/Lossy, RLE). | High |
| **REQ-FUN-026** | DICOMweb WADO-RS Rendered Views & WADO-URI | The system SHALL provide standard WADO-RS rendered preview endpoints (`.../rendered`, `.../frames/{frameList}/rendered`) returning JPEG/PNG images, and legacy WADO-URI query retrieve (`/dicomweb/wado?requestType=WADO...`). | High |


---

## 3. Performance Requirements (REQ-PERF)

| Requirement ID | Title | Performance Metric |
| :--- | :--- | :--- |
| **REQ-PERF-001** | Generation Throughput | Synthetic DICOM instance creation and disk serialization SHALL complete in <50ms per instance. |
| **REQ-PERF-002** | REST API Latency | Status and healthcheck REST API requests SHALL respond in <100ms. |
| **REQ-PERF-003** | Non-blocking SCP Server | DICOM SCP listener SHALL run on background threads without blocking FastAPI web requests. |
| **REQ-PERF-004** | Ephemeral On-The-Fly Generation | Synthetic DICOM images SHALL be generated on the fly with modest system resource requirements, ensuring local disk storage is not overloaded during stress testing or continuous auto-pushing. |

---

## 4. Regulatory & Protocol Standards Compliance (REQ-REG)

| Requirement ID | Standard | Requirement Description |
| :--- | :--- | :--- |
| **REQ-REG-001** | DICOM Part 10 Format | Output files SHALL comply with DICOM Part 10 File Format specifications (128-byte preamble, 'DICM' prefix, explicit File Meta Information header). |
| **REQ-REG-002** | DICOM Part 4 Services | DICOM SCP listener SHALL comply with DICOM Service Class Specifications for Verification, Query/Retrieve, and Storage. |
| **REQ-REG-003** | OpenAPI Standard | The REST API SHALL publish OpenAPI 3.0 compatible interactive documentation schemas (`/docs`). |
| **REQ-REG-004** | Local Network Intended Use | The system SHALL be restricted to local network test automation environments. It is strictly non-clinical and NOT intended as a clinical uptime evaluation tool (clinical inquiries must be directed to [GoSmart.health](https://gosmart.health)). |
| **REQ-REG-005** | ITU-T X.667 / ISO/IEC 9834-8 & DICOM PS 3.5 Annex B.2 | Generated DICOM UIDs SHALL comply with ITU-T X.667 / ISO/IEC 9834-8 bitfields and DICOM PS 3.5 Annex B.2 UUID-derived UID decimal formatting rules under root `2.25.` with string length <= 64 characters. |



