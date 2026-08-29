# Hazard Analysis & Software Risk Management Plan

**Document ID:** RMF-DPMS-001  
**Project:** `dicom-py-mock-server`  
**Regulatory Standard Alignment:** ISO 14971:2019, IEC 62304 Clause 7, FDA SaMD Safety Guidance  

---

## 1. Risk Management Framework

This document provides a Software Hazard Analysis for `dicom-py-mock-server`. It identifies potential software hazards associated with synthetic DICOM generation, tag construction, network association handling, and Pydantic validation, along with software design risk control measures implemented in the architecture.

---

## 2. Hazard Analysis Matrix

| Hazard ID | Hazard Description | Cause / Trigger | Potential Severity | Initial Risk | Software Risk Mitigation (Design Control) | Residual Risk | Verification Method |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **HAZ-001** | **Malformed DICOM Dataset** (Missing Mandatory Type 1 Tags) | Generator fails to write mandatory PatientID, StudyInstanceUID, or SOPInstanceUID tags. | High | High | **Design Control:** `DicomGeneratorService` explicitly constructs FileMetaDataset and populates mandatory Type 1 DICOM tags before serialization. | Negligible | Unit test `test_dicom_file_generation` verifies dataset tag integrity with `pydicom.dcmread`. |
| **HAZ-002** | **Transfer Syntax / VR Mismatch** | Encoding implicit VR when transfer syntax specifies Explicit VR Little Endian. | High | Medium | **Design Control:** FileMetaDataset sets `TransferSyntaxUID = ExplicitVRLittleEndian` and `ds.save_as(..., enforce_file_format=True)` strictly enforces syntax compliance. | Negligible | `pytest` validation of written DICOM file headers. |
| **HAZ-003** | **SCP Port Binding Failure** | Network port conflict or duplicate server binding attempt. | Moderate | Medium | **Design Control:** `DicomScpService.start()` checks `is_running` state and handles socket exceptions gracefully without crashing main app. | Negligible | API integration test `test_scp_status_endpoint`. |
| **HAZ-004** | **Invalid API Input Injection** | Malicious or corrupt payload submitted to `/api/v1/generate`. | Moderate | Medium | **Design Control:** Pydantic `MockDicomRequest` validates fields, string formats, bounds (`num_instances`, `rows`, `columns`), and raises 422 Unprocessable Entity. | Negligible | Pydantic schema unit tests and FastAPI endpoint validation. |
| HAZ-005 | Disk / Memory Exhaustion | Client requests generation of unbounded number of DICOM instances. | High | High | Design Control: Pydantic Field(ge=1, le=100) clamps maximum allowed instance count per generation request. | Negligible | Boundary validation tests on num_instances. |
| **HAZ-006** | **Template SOP Parsing Failure** | Corrupt or invalid template SOP instance provided during MWL/instance synthesis. | Moderate | Medium | **Design Control:** `DicomGeneratorService` validates template SOP tags and falls back to a verified built-in template schema with clear error reporting. | Negligible | Unit test `test_template_sop_synthesis`. |
| **HAZ-007** | **Unreadable OCR Burned-In Text** | Rendered text is truncated or low-contrast, failing automated OCR image verification. | Moderate | Medium | **Design Control:** `OCRRenderer` uses standardized high-contrast fonts, fixed bounding boxes, and monochrome pixel scaling for image number, patient name, and patient ID. | Negligible | Visual and OCR reception integration test `test_ocr_burned_in_text`. |
| **HAZ-008** | **Auto-Push Queue Backpressure** | Simulated 9-5 peak pushing overloads target PACS/SCP network sockets. | Moderate | Medium | **Design Control:** `AutoPushSchedulerService` uses non-blocking socket pools with rate-limiting and connection retry backoff. | Negligible | Scheduler integration test `test_autopush_scheduler`. |
| **HAZ-009** | **Disk Storage Saturation During Stress Testing** | Prolonged stress testing or 24/7 background push fills local disk space. | High | High | **Design Control:** Ephemeral on-the-fly streaming generation generates DICOM datasets directly into memory buffers, avoiding local disk writes. | Negligible | Stress test memory and disk usage protocol `test_ephemeral_stress_generation`. |
| **HAZ-010** | **Inappropriate Clinical Deployment** | Software deployed as a clinical uptime evaluation tool or clinical PACS component. | High | Medium | **Design Control:** Startup warning log banner, OpenAPI documentation disclaimers, and SRS/SDS explicit boundaries restricting use to local network test automation (directing clinical inquiries to GoSmart.health). | Negligible | Verification of startup logging and documentation disclaimers. |

---

## 3. Risk Management Conclusion

All identified hazards (HAZ-001 through HAZ-010) have been mitigated through software design controls. The residual risk for `dicom-py-mock-server` components is assessed as **acceptable** for synthetic DICOM data generation, MWL synthesis, OCR-verified image pushing, and mock DICOM network service simulation in local network testing environments.


