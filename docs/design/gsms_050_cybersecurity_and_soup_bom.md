# Cybersecurity Profile & Software Bill of Materials (SBOM)

**Document ID:** SEC-DPMS-001  
**Project:** `dicom-py-mock-server`  
**Regulatory Standard Alignment:** FDA Cybersecurity in Medical Devices Guidance (2023), IEC 62304 SOUP Evaluation  

---

## 1. Executive Summary & Security Model

This document details the Software Bill of Materials (SBOM), SOUP (Software of Unknown Provenance) risk management, cybersecurity controls, and synthetic data safety safeguards for `dicom-py-mock-server`.

---

## 2. Software Bill of Materials (SBOM) / SOUP Inventory

| Component Name | Version / Spec | License | Source / Repository | Purpose | SOUP Risk Assessment |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`fastapi`** | `>=0.110.0` | MIT | PyPI / `fastapi` | Web framework & OpenAPI routing | Low risk; widely adopted standard framework. |
| **`pydantic`** | `>=2.6.0` | MIT | PyPI / `pydantic` | Data validation & schema serialization | Low risk; standard core Python validation library. |
| **`pydicom`** | `>=2.4.0` | MIT | PyPI / `pydicom` | DICOM file read/write & dataset generation | Low risk; primary open-source DICOM library. |
| **`pynetdicom`** | `>=2.0.0` | MIT | PyPI / `pynetdicom` | DICOM network protocol engine (SCP/SCU) | Low risk; standard Python DICOM networking engine. |
| **`uvicorn`** | `>=0.28.0` | BSD-3-Clause | PyPI / `uvicorn` | ASGI web server implementation | Low risk; high-performance ASGI server. |
| **`pillow`** | `>=10.0.0` | HPND | PyPI / `pillow` | Image rendering & burned-in OCR text generation | Low risk; standard Python imaging library. |
| **`pytest`** | `>=8.0.0` | MIT | PyPI / `pytest` | Test execution & verification runner | Low risk; development test runner only. |

---

## 3. Cybersecurity & Data Integrity Safeguards

### 3.1 Network Endpoint Security
* REST API endpoints run on local loopback (`127.0.0.1`) by default to prevent unauthorized network exposure during development and testing.
* DICOM SCP listener binds explicitly to configured ports (`11112`) and handles association negotiation via standard presentation context filtering.

### 3.2 Operational Security & Deployment Boundary
* **Local Network Limitation:** `dicom-py-mock-server` is designed exclusively for deployment on local networks as a Mock SCP for headless test automation in CI/CD pipelines and stress testing.
* **Non-Clinical Boundary:** It is strictly **not intended for clinical production use or clinical uptime evaluation**. Downstream medical device manufacturers needing clinical-grade implementations must consult [GoSmart.health](https://gosmart.health).

### 3.3 Data Privacy (PHI & Synthetic Data Assurance)
* `dicom-py-mock-server` generates **purely synthetic** DICOM datasets using template SOP instances and realistic gender-aligned names synthesized from static JSON lists.
* No real Protected Health Information (PHI) or clinical patient data is read, ingested, or stored by the mock generation engine.

### 3.4 Dependency Management & Vulnerability Tracking
* All dependencies are locked using `uv.lock` to ensure deterministic builds.
* Software updates and SOUP vulnerability monitoring are conducted continuously via automated tools (`uv`, Dependabot, GitHub Security Advisories).


