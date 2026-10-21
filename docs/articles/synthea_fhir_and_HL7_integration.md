# Bridging the Clinical-Imaging Divide: Synthea, FHIR, and HL7 Integration with dicom-py-mock-server

*A developer and DevOps guide to closing the loop between EHR clinical workflows and PACS/VNA DICOM imaging using synthetic data.*

---

## Introduction: Why We Needed This

In modern healthcare IT architectures, clinical data and medical imaging inhabit two distinct operational domains that must constantly synchronize:

1. **The Electronic Health Record (EHR)**: Governed by standards like **HL7 v2** (e.g., `ORM^O01` orders, `ORU^R01` observation results) and modern **HL7 FHIR** RESTful resources (`Patient`, `ServiceRequest`, `Encounter`, `DiagnosticReport`). This is where ordering physicians place imaging requests, track patient clinical journeys, and review signed radiology reports.
2. **The Picture Archiving and Communication System (PACS) & Modality Fleet**: Governed by **DICOM** (DIMSE over TCP such as C-FIND, C-MOVE, C-STORE, Modality Worklist / MWL, and DICOMweb RESTful services like QIDO-RS, WADO-RS, STOW-RS). Modalities pull scheduled procedures from the worklist, acquire pixels, and push series back to the PACS or Vendor Neutral Archive (VNA).

For engineering, QA, and DevOps teams building healthcare integration pipelines, ML inference engines, or clinical decision support platforms, setting up an end-to-end sandbox has traditionally been painful:

- **Fragmented Test Harnesses**: You can run an open-source FHIR server (e.g., HAPI FHIR) and a DICOM SCP (e.g., Orthanc or DCM4CHEE), but synchronizing patient demographics, order numbers (Accession Numbers), scheduled procedure steps, and image instances across both systems usually requires complex custom glue code.
- **Heavyweight Deployments**: Enterprise simulator stacks often require heavy virtual machines, proprietary databases, or convoluted multi-container orchestrations that are difficult to automate in CI/CD pipelines or spin up locally for fast feature development.
- **The "Missing Pixels" Problem**: Tools that generate synthetic clinical records don't generate DICOM studies, while DICOM test tools rarely understand the patient's longitudinal EHR narrative.

We designed `dicom-py-mock-server` to be lightweight, modular, and developer-friendly—allowing developers and DevOps engineers to boot a complete mock server in seconds, ingest clinical orders or synthetic EHR bundles, and immediately interact via standard DICOM network protocols and DICOMweb.

With our latest release, we've introduced native integration with **Synthea™**, enabling teams to generate entire synthetic health systems and instantly bring their imaging histories to life in DICOM.

---

## Where Does Synthea Fit Into This Goal?

[Synthea™](https://github.com/synthetichealth/synthea) is an open-source synthetic patient generator modeled on real-world epidemiological data. It generates realistic, longitudinal health records for synthetic populations—completely devoid of Protected Health Information (PHI).

With Synthea, you can generate:

- Complete health systems: Hospitals, imaging centers, clinics, and geographic locations (`hospitalInformation*.json`).
- Healthcare providers: Practitioners, referring physicians, and radiologists with realistic NPI identifiers (`practitionerInformation*.json`).
- Patient cohorts: Lifelong medical records including conditions, encounters, medications, observations, care plans, and clinical orders output as standard HL7 FHIR R4 JSON bundles.

### The Missing Link: Imaging Pixels

Crucially, Synthea generates `ImagingStudy` resources and associated diagnostic procedures as part of a patient's history. It defines the modalities (e.g., CT, Ultrasound, Radiography), procedure codes (SNOMED-CT / LOINC), dates, and body sites. 

However, **Synthea does not generate DICOM Part-10 files or DICOM network endpoints**. It outputs purely JSON metadata. An engineer testing a PACS ingestion pipeline, an AI model consuming DICOM series, or a Modality Worklist client cannot point their tools directly at a Synthea FHIR bundle.

This is where `dicom-py-mock-server` steps in. It consumes Synthea's FHIR bundles, extracts the clinical narrative, cross-references practitioners and facilities, maps modalities into coherent DICOM hierarchies, and serves them over real DICOM SCP listeners (C-FIND, C-MOVE, C-STORE, MWL) and DICOMweb endpoints.

---

## Architecture: End-to-End Pipeline

The diagram below illustrates how synthetic data flows from Synthea through `dicom-py-mock-server` and into downstream DICOM clients and workflows:

[Diagram](./Overall-System.png)

*(Architecture Diagram: Synthea FHIR Generator -> dicom-py-mock-server Ingestion Pipeline -> In-Memory Store & DICOM Generator -> DIMSE MWL/C-FIND/C-MOVE & DICOMweb)*



---

## How It Works: Hands-On Walkthrough

Let's walk through how to set up the workflow from synthetic data generation to DICOM query and retrieval.

### Step 1: Generate Synthetic Data with Synthea

Clone and run Synthea according to its documentation. For example, to generate 100 Massachusetts patients with FHIR R4 records:

```bash
git clone https://github.com/synthetichealth/synthea.git
cd synthea
./run_synthea -p 100 Massachusetts
```

Synthea creates an `output/fhir/` directory containing:

- `hospitalInformation*.json`: Healthcare organizations and facilities.
- `practitionerInformation*.json`: Clinicians, referring doctors, and radiologists.
- `<FirstName>_<LastName>_<UUID>.json`: Longitudinal patient records containing `Patient`, `Encounter`, `Condition`, and `ImagingStudy` resources.

### Step 2: Ingest Bundles into `dicom-py-mock-server`

The mock server exposes a dedicated ingestion endpoint:
`POST /api/v1/synthea/load`

Because patient studies link to performing facilities and attending practitioners via FHIR reference URIs, `dicom-py-mock-server` enforces an **additive in-memory lifecycle requirement**:

> [!IMPORTANT]
> **Resource Loading Order**:
> Hospital and practitioner resource bundles must be ingested prior to patient bundles. If a patient bundle is ingested before hospitals or practitioners are loaded, the server responds with HTTP `400 Bad Request` (`"Hospital resources must be sent first."` or `"Practitioner resources must be sent first."`).

To automate this ordering, batching, and fallback logic, the repository includes a Python utility [`util/synthea_loader.py`](file:///Users/manabutokunaga/development/dicom-root/dicom-py-mock-server/util/synthea_loader.py) and a shell wrapper [`synthea_loader.sh`](file:///Users/manabutokunaga/development/dicom-root/dicom-py-mock-server/synthea_loader.sh):

```bash
# Start your mock server instance
./start.sh

# In another terminal, trigger the loader script targeting your Synthea FHIR output directory
./synthea_loader.sh
```

Under the hood, `synthea_loader.py`:
1. Scans the directory and segregates hospital/practitioner bundles from patient files.
2. Posts prerequisite infrastructure resources to `/api/v1/synthea/load`.
3. Streams patient bundles in configurable chunks (default: 25 bundles per request) to prevent memory bottlenecks.
4. If the live server is running (default `http://127.0.0.1:8000`), it delivers via HTTP; if offline, it falls back to in-process testing via FastAPI's `TestClient`.

### Step 3: What Happens Internally During Ingestion?

When a patient bundle arrives at `/api/v1/synthea/load`:

1. **Identifier & Demographics Extraction**: Patient ID, name, birthdate, and sex are extracted.
2. **ImagingStudy & Series Parsing**: The parser scans for supported `ImagingStudy` modalities. For each study:
   - Study attributes (Accession Number, Study Date, Study Description) are mapped.
   - Referring physician, performing physician, and facility names are resolved by dereferencing practitioner and organization references against previously loaded caches.
   - Deterministic UIDs (StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID) are generated under the standard OSI root `2.25.` using UUIDv5/SHA-1 over namespace seeds.
3. **Modality Worklist (MWL) Synchronization**: Corresponding scheduled procedure steps are injected into the active MWL generator so modalities can discover upcoming scans.
4. **DICOM Instance Generation**: Part-10 DICOM instances are generated on disk in the configured storage directory (`./data/dicom_storage`), marrying the patient demographics with multi-slice modality templates.
5. **In-Memory Query Model Indexing**: In-memory models (`PatientModel`, `StudyModel`, `SeriesModel`) are registered in `SyntheaUtils` for ultra-fast query execution.

### Step 4: Querying with Modality Worklist (MWL) and C-FIND

Once loaded, the synthetic patients are immediately accessible across standard DICOM interfaces.

#### Querying Active Worklist (MWL C-FIND)

Modalities (or tools like DCMTK `findscu`) can query the MWL SCP on port `11112`:

```bash
# Query scheduled worklist items for CT modality
findscu -v -W -k "(0008,0060)=CT" 127.0.0.1 11112
```

The response includes the patient demographics, accession number, requested procedure description, and scheduled station AE.

#### Querying Studies via C-FIND
You can execute standard Patient/Study Root C-FIND queries at `PATIENT`, `STUDY`, `SERIES`, or `IMAGE` levels:

```bash
# Search for all studies belonging to a Synthea patient ID
findscu -v -S \
  -k "(0008,0052)=STUDY" \
  -k "(0010,0020)=S99916806" \
  -k "(0020,000D)=" \
  -k "(0008,0061)=" \
  -k "(0008,1030)=" \
  127.0.0.1 11112
```

<!-- TODO: Insert C-FIND Query and Response Screenshots here -->

*(Screenshot Placeholder: Executing C-FIND from a workstation or DCMTK findscu against dicom-py-mock-server, showing populated Patient Name, Study UID, and Modalities)*

#### Querying via Synthea REST & DICOMweb QIDO-RS
If you are developing web frontends or cloud integration services, you can also query the records via HTTP:

```bash
# Using dedicated Synthea inspection endpoints
curl "http://127.0.0.1:8000/api/v1/synthea/patients"
curl "http://127.0.0.1:8000/api/v1/synthea/studies?patient-id=S99916806"
curl "http://127.0.0.1:8000/api/v1/synthea/series?modality=US"

# Using standard DICOMweb QIDO-RS
curl -X GET "http://127.0.0.1:8000/dicomweb/studies?PatientID=S99916806" \
     -H "Accept: application/dicom+json"
```

### Step 5: Retrieving Images via C-MOVE and DICOMweb WADO-RS

DICOM viewers or PACS destinations can issue standard DIMSE C-MOVE requests to retrieve generated image instances:

```bash
# Issue C-MOVE to push study instances to a configured destination AE (e.g., VIEWER_AE)
movescu -v -S \
  -k "(0008,0052)=STUDY" \
  -k "(0020,000D)=2.25.1234567890..." \
  -aem VIEWER_AE \
  127.0.0.1 11112
```

Or retrieve metadata and rendered frames via standard DICOMweb WADO-RS endpoints:
```bash
# Retrieve study metadata
curl "http://127.0.0.1:8000/dicomweb/studies/2.25.1234567890.../metadata"

# Retrieve study Part-10 instances (multipart/related)
curl "http://127.0.0.1:8000/dicomweb/studies/2.25.1234567890..." \
     -H "Accept: multipart/related; type=\"application/dicom\""
```

---

## Broader Ecosystem: HL7 v2 MLLP and FHIR ServiceRequest Support

While Synthea bulk ingestion is ideal for seeding baseline datasets and historical patient records, day-to-day integration testing frequently demands real-time order scheduling events.

`dicom-py-mock-server` includes two companion real-time ingestion channels:

### 1. Zero-Dependency HL7 v2 MLLP Socket Listener

The server runs an asynchronous Minimal Lower Layer Protocol (MLLP) TCP listener on port `2575` (`GOSMART_MS_HL7_PORT`):

- Ingests raw `ORM^O01` imaging order messages over raw sockets.
- Parses PID (Patient Identification), PV1 (Patient Visit), and ORC/OBR (Order Observation) segments.
- Automatically injects the order into the active Modality Worklist (MWL) and generates corresponding DICOM objects.
- Handles order cancellations (`CA` order control codes) by revoking worklist entries.
- Emits standard `ACK^O01` acknowledgement frames.

You can test this using the included CLI utility:

```bash
uv run push-hl7 -v util/orm.txt
```

### 2. Ad-Hoc FHIR ServiceRequest & Order Bundles

For microservices or modern health platforms driving orders via FHIR REST hooks, the server provides:

- `POST /api/v1/fhir_service_request`
- `POST /api/v1/fhir/Bundle`
- `POST /api/v1/fhir/ServiceRequest`

Submitting a FHIR bundle with a `ServiceRequest` and referenced `Patient` dynamically generates an MWL order. If the `ServiceRequest.status` is later submitted as `revoked` or `entered-in-error`, the order is automatically purged from the active worklist.

---

## Technical Limitations & Nuances

When incorporating `dicom-py-mock-server` into your test automation and CI/CD pipelines, keep the following considerations in mind:

- **Synthetic vs. Diagnostic Pixels**: The mock server generates valid, standards-compliant DICOM Part-10 binary objects by stamping clinical metadata and burning identifiers onto multi-slice template datasets (located in `./templates/`). The pixel data is *modality-coherent* (e.g., a CT request produces CT slices, an Ultrasound request produces US frames), but it is **not clinically correlated** to the patient's Synthea pathology. These images must never be used for clinical diagnosis.
- **Modality Scope**: Synthea generates `ImagingStudy` resources across several modalities, notably `CT`, `US` (Ultrasound), `CR` (Computed Radiography), and `DX` (Digital Radiography). In Synthea, `DX` is frequently utilized for dental series. Currently, `dicom-py-mock-server` supports `CT`, `US`, and `CR` templates; unsupported or dental `DX` imaging studies are skipped with an informational log entry (`synthea_bundle_no_supported_imaging_study`).
- **Security & Authorization**: The server is designed as an unauthenticated plain access point intended strictly for development sandboxes, internal test harnesses, and automated CI pipelines. It should **never** be exposed directly to untrusted public networks without an authenticating reverse proxy.

---

## Conclusion

By bridging Synthea's epidemiological clinical modeling with realistic DICOM generation and network services, `dicom-py-mock-server` eliminates the traditional boundary between EHR development and PACS/imaging systems. Developers and DevOps engineers can spin up a fully populated, standards-compliant healthcare environment in minutes.

We invite you to check out the repository, give the Synthea loader a spin, and integrate it into your testing pipelines!

---

*Have questions or feedback? Feel free to open an issue or pull request on our GitHub repository.*
