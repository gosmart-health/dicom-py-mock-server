# Design Controls & Regulatory Documentation

This directory contains the FDA 510(k) and IEC 62304 / ISO 14971 / ISO 13485 aligned Design Controls documentation suite for `dicom-py-mock-server`.

The documents are prefixed with `gsms_XXX` in recommended reading order (from requirements to design, risk, V&V, traceability, and cybersecurity).

---

> [!IMPORTANT]
> **Regulatory Intent & Quality Management Scope**
> 
> While this project closely follows best quality control and design control management practices (aligned with IEC 62304, ISO 14971, ISO 13485, and FDA 21 CFR 820.30), the existence and structure of these documents do **not** claim or certify that this open-source software has been developed under an audited or certified Quality Management System (QMS).
> 
> These artifacts are provided to **minimize regulatory friction and accelerate technical documentation** for downstream medical device manufacturers, system integrators, and healthcare organizations who are adopting, extending, and validating this mock DICOM server software within their own accredited QMS.

---

## Document Walkthrough Index

| Document | Regulatory Standard | Description |
| :--- | :--- | :--- |
| **[gsms_000_software_requirements_spec.md](./gsms_000_software_requirements_spec.md)** | IEC 62304 Cl. 5.2 | **Software Requirements Specification (SRS)**: Functional specifications for template SOP synthesis, MWL generation with gender-aligned patient names, OCR burned-in text rendering, 9-5 auto-push scheduling, headless CI/CD mock SCP operations, stress testing, low-disk ephemeral generation, and local network non-clinical scope disclaimers. |
| **[gsms_010_system_design_specification.md](./gsms_010_system_design_specification.md)** | IEC 62304 Cl. 5.3 / 5.4 | **System Design Specification (SDS / SAD)**: Subsystem decomposition (`api`, `models`, `services`), template SOP generator, JSON name synthesizer, OCR text engine, 9-5 auto-push scheduler, and non-blocking `pynetdicom` SCP listener (C-ECHO, C-FIND, C-MOVE, C-GET, MWL, C-STORE). |
| **[gsms_020_hazard_analysis_risk_management.md](./gsms_020_hazard_analysis_risk_management.md)** | ISO 14971:2019 / IEC 62304 Cl. 7 | **Hazard Analysis & Risk Management**: Software Risk Matrix identifying technical hazards (template parsing failures, OCR unreadability, auto-push backpressure, disk exhaustion during stress testing, clinical deployment misuse) and design risk controls. |
| **[gsms_030_verification_and_validation_plan.md](./gsms_030_verification_and_validation_plan.md)** | IEC 62304 Cl. 5.5 - 5.7 | **Verification & Validation Plan**: Test protocols across unit tests (`pytest`), template & OCR verification, 9-5 scheduler tests, headless CI/CD interop, and stress testing. |
| **[gsms_040_traceability_matrix.md](./gsms_040_traceability_matrix.md)** | FDA Design Controls | **Requirements Traceability Matrix (RTM)**: Bi-directional matrix mapping **Requirements (SRS) <-> System Design (SDS) <-> Hazards (ISO 14971) <-> Verification Tests (V&V)** across all features. |
| **[gsms_050_cybersecurity_and_soup_bom.md](./gsms_050_cybersecurity_and_soup_bom.md)** | FDA Cybersecurity Guidance | **Cybersecurity & SOUP BOM**: Software Bill of Materials (SBOM) for SOUP components (`fastapi`, `pydantic`, `pydicom`, `pynetdicom`, `uvicorn`, `pillow`), local network security model, non-clinical disclaimers, and synthetic data safety. |


