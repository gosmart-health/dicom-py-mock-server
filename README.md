# dicom-py-mock-server

Auto generate mock DICOM objects, serve via C-FIND, C-MOVE/GET, MWL SCP, and expose capabilities via Model Context Protocol (MCP) Server-Sent Events (SSE).

> [!WARNING]
> **SECURITY WARNING: NO AUTHENTICATION / AUTHORIZATION**
> 
> This service functions strictly as an **unauthenticated plain access point** for synthetic DICOM object generation, MWL testing, and DICOM SCP network simulation.
> - The REST API and MCP SSE endpoints do **NOT** support authentication (`authn`) or authorization (`authz`).
> - **DO NOT** deploy this mock server in a production environment or expose its endpoints to public networks or untrusted internet interfaces.

> [!CAUTION]
> **TEMPLATE DICOM DE-IDENTIFICATION NOTICE**
> 
> - The generator **does NOT perform de-identification** on template DICOM files.
> - Patient Name, Patient ID, Patient Sex, Study Date and Time, all DICOM UIDs (Study/Series/SOP Instance UIDs), and image pixel data will be generated and replaced.
> - **All other DICOM elements are passed through "as is"**, including any pre-existing private data elements, vendor-specific attributes, and secondary metadata present in template files. Users must ensure templates do not contain sensitive PHI or non-de-identified patient information prior to loading.
>- A full standard compliant DICOM de-identification process is available using [GoSmart.Health DICOM RS Transformer](https://github.com/gosmart-health/dicom-rs-transformer)

---

## Capabilities & Features

1. **Synthetic DICOM Generation**: Generate customizable DICOM P10 objects with specified Patient, Study, Series, and instance metadata.
2. **Deterministic DICOM UID Generation (ITU-T X.667 / ISO/IEC 9834-8)**: Generates standards-compliant `2.25.<u128>` UIDs using SHA-1 (UUIDv5) or MD5 (UUIDv3) over a persistent namespace, preventing PHI exposure while maintaining hierarchical reproducibility (Study -> Series -> Instance).
3. **DICOM SCP Services**: Built-in DICOM C-FIND, C-MOVE/GET, and MWL (Modality Worklist) SCP network listeners.
4. **Modality Worklist (MWL) Synthesis**: Automated business-hours MWL entry creation and retention window management.
5. **MCP Integration Provisioning**: Exposes server capabilities to AI Assistants (AGY, Claude Desktop, Cursor, etc.) over Server-Sent Events (SSE) transport.
6. **Multi-Slice Template Datasets & Synthetic Mode**: Load multi-slice DICOM datasets from subdirectories under `templates/` (e.g. `templates/Toshiba_Aquilion/`, `templates/MR/`) with dynamic modality detection and folder purity validation. In non-synthetic mode (`GOSMART_MS_SYNTHETIC_MODE=false`), the server delivers exact series slice counts with round-robin template picking, preserves the template's original Study Description (without swapping with mock up values), and maintains pixel preservation. In synthetic mode (`GOSMART_MS_SYNTHETIC_MODE=true`), slices rotate cyclically conforming to configurable slice ranges and generate synthetic study descriptions. Supported compression syntaxes include `JPEG2000_LOSSLESS`, `JPEG2000_LOSSY`, `JPEG`, `RLE`, `EXPLICIT_VR_LITTLE_ENDIAN`, and `IMPLICIT_VR_LITTLE_ENDIAN`.
6. **Multi-Slice Template Datasets & Synthetic Mode**: Load multi-slice DICOM datasets from subdirectories under `templates/` (e.g. `templates/sample_ct/`, `templates/sample_mr/`) with dynamic modality detection and folder purity validation. In non-synthetic mode (`GOSMART_MS_SYNTHETIC_MODE=false`), the server delivers exact series slice counts with round-robin template picking, preserves the template's original Study Description (without swapping with mock up values), and maintains pixel preservation. In synthetic mode (`GOSMART_MS_SYNTHETIC_MODE=true`), slices rotate cyclically conforming to configurable slice ranges and generate synthetic study descriptions. Supported compression syntaxes include `JPEG2000_LOSSLESS`, `JPEG2000_LOSSY`, `JPEG`, `RLE`, `EXPLICIT_VR_LITTLE_ENDIAN`, and `IMPLICIT_VR_LITTLE_ENDIAN`.
7. **Template SOP Compression & PACS Verification**: Synthesize valid DICOM Part-10 files directly from templates (such as `templates/sample_ct` and `templates/sample_mr`) with burned metadata text, precomputed background test patterns, and supported compression syntaxes (`JPEG2000_LOSSLESS`, `JPEG2000_LOSSY`, `JPEG`, `RLE`, `EXPLICIT_VR_LITTLE_ENDIAN`, `IMPLICIT_VR_LITTLE_ENDIAN`) saved to `test_output/` for PACS viewer inspection.
8. **Zero-Dependency HL7 v2 MLLP Socket Listener**: Ingests raw `ORM^O01` radiology order messages over TCP/IP via MLLP framing on port `2575`, registers MWL items without demographic alteration/anonymization, handles order cancellation (`ORC-1 = CA`), rejects unsupported modalities without template images, and transmits MLLP-framed `ACK^O01` responses.
9. **FHIR ServiceRequest Bundle Ingestion**: Accepts FHIR R4/R5 imaging order bundles via `POST /api/v1/fhir_service_request` (and aliases `/api/v1/fhir/Bundle` and `/api/v1/fhir/ServiceRequest`), maps patient demographics, procedure codes, and timing directly into MWL entries, and triggers order revocation.

---

## MCP SSE Integration

The MCP SSE server transport provides two endpoints:
- **SSE Stream Endpoint**: `GET /sse` or `GET /api/v1/sse`
- **JSON-RPC Message Endpoint**: `POST /sse/messages` or `POST /api/v1/sse/messages`

### MCP Tools Exposed

| MCP Tool Name | Description |
| :--- | :--- |
| `health_check` | Check service health status and application metadata. |
| `generate_mock_dicom` | Generate synthetic DICOM P10 objects with custom metadata and save to disk. |
| `get_scp_status` | Get DICOM SCP (C-FIND, C-MOVE, MWL) listener status. |
| `start_scp` | Start the DICOM SCP listener service. |
| `stop_scp` | Stop the DICOM SCP listener service. |
| `get_mwl_status` | Get Modality Worklist (MWL) generator status and active entry counts. |
| `list_mwl_entries` | List currently active Modality Worklist (MWL) entries within retention window. |
| `generate_mwl_entry` | Manually generate a new MWL entry with optional custom fields. |
| `start_mwl_auto_generation` | Start background MWL automated entry generation loop. |
| `stop_mwl_auto_generation` | Stop background MWL automated entry generation loop. |
| `move_study` | Move/push DICOM study instances matching Patient ID, Accession Number, or Study UID to a destination DICOM SCP (AE Title, Host, Port). |

---

## AI Agent Integration (AGY, Claude Desktop, Cursor)

To connect an MCP-compatible AI agent to the server via SSE, add the following entry to your MCP configuration:

### AntiGravity / AGY (`~/.gemini/config/mcp_config.json` or `mcp_config.json`)

AntiGravity uses the `serverUrl` field for remote SSE MCP servers:

```json
{
  "mcpServers": {
    "dicom-py-mock-server": {
      "serverUrl": "http://127.0.0.1:8000/sse"
    }
  }
}
```

### Claude Desktop / Cursor (`claude_desktop_config.json`)

Other clients such as Claude Desktop or Cursor use the `url` field:

```json
{
  "mcpServers": {
    "dicom-py-mock-server": {
      "url": "http://127.0.0.1:8000/sse"
    }
  }
}
```

---

## Environment Variables & Configuration

All configuration settings can be defined in a `.env` file in the root workspace or passed as environment variables. Environment variables prefixed with `GOSMART_MS_` (or their supported aliases) are automatically parsed at startup.

| Environment Variable | Supported Aliases | Default | Description |
| :--- | :--- | :--- | :--- |
| `GOSMART_MS_HOST` | `HOST` | `127.0.0.1` | REST API & MCP server HTTP host interface. |
| `GOSMART_MS_PORT` | `PORT` | `8000` | REST API & MCP server HTTP port. |
| `GOSMART_MS_SCP_AE_TITLE` | `GOSMART_MS_AE_TITLE`, `SCP_AE_TITLE`, `AE_TITLE` | `GOSMART_SCP` | Application Entity (AE) Title for the DICOM SCP listener. |
| `GOSMART_MS_SCP_PORT` | `SCP_PORT` | `11112` | DICOM SCP listening port (C-ECHO, C-FIND, C-MOVE, C-STORE, MWL). |
| `GOSMART_MS_STORAGE_DIR` | `STORAGE_DIR` | `./data/dicom_storage` | Local directory path to store generated DICOM files. |
| `GOSMART_MS_RECEIVED_DIR` | `RECEIVED_DIR` | `./received` | Local directory path to store received STOW-RS Part-10 DICOM files. |
| `GOSMART_MS_STOW_DUPLICATE_HANDLING` | `STOW_DUPLICATE_HANDLING` | `accept` | Policy for STOW-RS duplicate SOP instances: `accept` (overwrite), `warn` (overwrite with WarningReason 0xB000), or `reject` (reject with FailureReason 0x0111). |
| `GORMART_MS_CSV_PATH` | `GOSMART_MS_CSV_PATH`, `CSV_PATH` | `./csv` | Local directory path to store C-STORE association audit CSV files (`yyyymmddhhmmss_<AE_Title>.csv`). |
| `GOSMART_TEMPLATES_PATH` | `GOSMART_MS_TEMPLATES_PATH`, `TEMPLATES_PATH` | `./templates` | Directory containing modality subfolders with multi-slice DICOM (`.dcm`, `.dicom`) templates. |
| `GOSMART_MS_LOG_LEVEL` | `LOG_LEVEL` | `INFO` | Logging verbosity level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |
| `GOSMART_MS_LOG_PATH` | `GOSMART_MS_LOG_FILE`, `LOG_PATH`, `LOG_FILE` | `./logs` | Directory or file path for rotated log files (`dicom_mock_server.log`). |
| `GOSMART_MS_LOG_ROTATION_DAYS` | `LOG_ROTATION_DAYS` | `7` | Log file auto-rotation interval in days (`TimedRotatingFileHandler`). |
| `GOSMART_MS_LOG_BACKUP_COUNT` | `LOG_BACKUP_COUNT` | `4` | Number of rotated backup log files to retain on disk. |
| `GOSMART_MS_LOG_JSON_FORMAT` | `LOG_JSON_FORMAT` | `true` | Format log file entries as structured JSON Lines. |
| `GOSMART_MS_MWL_WINDOW_HR` | `MWL_WINDOW_HR` | `24` | Retention window in hours for active Modality Worklist (MWL) entries. |
| `GOSMART_MS_MWL_RATE_PER_HR` | `MWL_RATE_PER_HR` | `12.0` | Base MWL creation rate per hour during business hours (9 AM - 5 PM local; 5% rate off-hours). |
| `GOSMART_MS_MCP_ENABLED` | `MCP_ENABLED` | `true` | Enable Model Context Protocol (MCP) SSE integration endpoints. |
| `GOSMART_MS_MCP_SSE_PATH` | `MCP_SSE_PATH` | `/sse` | Base HTTP endpoint path for MCP SSE streams. |
| `GOSMART_MS_SYNTHETIC_MODE` | `SYNTHETIC_MODE` | `false` | Enable synthetic slice volume generation (slice range bounds and cyclic rotation) instead of non-synthetic mode (exact template slice counts). |
| `GOSMART_MS_MIN_SLICES` | `MIN_SLICES` | `8` | Minimum slice count for synthetic series generation (used when `SYNTHETIC_MODE=true`). |
| `GOSMART_MS_MAX_SLICES` | `MAX_SLICES` | `24` | Maximum slice count for synthetic series volume generation (used when `SYNTHETIC_MODE=true`). |
| `GOSMART_MS_TRANSFER_SYNTAX` | `TRANSFER_SYNTAX` | `JPEG2000_LOSSLESS` | Default DICOM Transfer Syntax (`RAW`, `JPEG`, `JPEG2000`, `JPEG2000_LOSSLESS`, `RLE`). |
| `GOSMART_MS_STRESS` | `STRESS` | `false` | Enable high-throughput stress mode (single compressed frame computation, demographics burned in, slice number overlay omitted, negotiated transfer syntax reuse). |
| `GOSMART_MS_MOVE_DESTINATIONS` | `MOVE_DESTINATIONS` | `{}` | JSON string mapping C-MOVE destination AE Titles to target host/port objects. |
| `GOSMART_MS_PATIENT_SUFFIX` | `PATIENT_SUFFIX` | `_GSH` | Suffix appended to synthetic patient last name to avoid PACS collisions (empty strings permitted). |
| `GOSMART_MS_PN_SUFFIX` | `PN_SUFFIX` | `_GSH` | Suffix appended to generated physician names (Referring, Performing, Reading) to avoid PACS collisions (empty strings permitted). |
| `GORMART_MS_INSTITUTION_NAME` | `GOSMART_MS_INSTITUTION_NAME`, `INSTITUTION_NAME` | `GO SMART CLINIC` | Default Institution Name attribute for synthesized studies and MWL entries. |
| `GOSMART_MS_ID_PREFIX` | `ID_PREFIX` | `GSH-` | Prefix prepended to synthetic Patient ID and Accession number to avoid PACS collisions (empty strings permitted). |
| `GOSMART_MS_NAMESPACE_UUID` | `GOSMART_MS_DICOM_NAMESPACE_UUID`, `NAMESPACE_UUID` | `6ba7b810-9dad-11d1-80b4-00c04fd430c8` | Persistent UUID namespace used for deterministic ITU-T X.667 DICOM UID generation. |
| `GOSMART_MS_UID_VERSION` | `GOSMART_MS_DICOM_UID_VERSION`, `UID_VERSION` | `5` | UUID version for deterministic DICOM UID generation (`5` for SHA-1, `3` for MD5). |
| `GOSMART_MS_HL7_ENABLED` | `HL7_ENABLED` | `true` | Enable HL7 v2 MLLP TCP socket listener. |
| `GOSMART_MS_HL7_HOST` | `HL7_HOST` | `0.0.0.0` | HL7 v2 MLLP listener host address. |
| `GOSMART_MS_HL7_PORT` | `HL7_PORT` | `2575` | HL7 v2 MLLP listener TCP port. |
| `GOSMART_MS_HL7_APP_NAME` | `HL7_APP_NAME` | `GOSMART_MWL` | Receiving Application name for HL7 MSH and ACK segments. |
| `GOSMART_MS_HL7_FACILITY` | `HL7_FACILITY` | `GOSMART_HOSP` | Receiving Facility name for HL7 MSH and ACK segments. |
| `GOSMART_MS_FHIR_ENABLED` | `FHIR_ENABLED` | `true` | Enable FHIR ServiceRequest / Bundle REST endpoints. |
| `GOSMART_MS_APP_NAME` | `APP_NAME` | `DICOM Mock Server` | Application display name. |
| `GOSMART_MS_APP_VERSION` | `APP_VERSION` | `0.3.0` | Application version string. |

---

## Deterministic ITU-T X.667 / ISO/IEC 9834-8 DICOM UID Generation

All synthetic DICOM UIDs are generated under the standard OSI OID root `2.25.` (`2.25.<u128>`) adhering to ITU-T X.667 / ISO/IEC 9834-8 and DICOM PS 3.5 Annex B.2.

- **StudyInstanceUID**: Deterministically computed using UUIDv5 (SHA-1) over combined seed `study:<PatientName>:<PatientID>:<AccessionNumber>`.
- **SeriesInstanceUID**: Deterministically computed from `series:<StudyUID>:<SeriesNumber>`.
- **SOPInstanceUID**: Deterministically computed from `instance:<SeriesUID>:<InstanceNumber>`.

This ensures consistent, reproducible UIDs across test runs without leaking raw patient identifiers or PHI into UID strings while maintaining strict compliance with DICOM VR UI length limits (<= 64 chars) and standard bitfield constraints.

---

## C-STORE Association CSV Audit Logging

When a DICOM C-STORE transfer ends per association (C-MOVE push, SCU direct move/push, or incoming Storage SCP association), an audit CSV file is automatically written to local storage (`GORMART_MS_CSV_PATH`, default `./csv`).

- **File Naming**: `<yyyymmddhhmmss>_<AE_Title>.csv` in UTC timestamps at the start of the C-STORE association.
- **Columns**: `Date,Time,Destination AE,Status,Patient Name,Patient ID,Accession Number,Study UID,Series UID,Instance UID,Transfer Rate kb/s`
- **Date and Time**: UTC timestamps (`YYYYMMDD` date and `HHMMSS` time).
- **Status Values**: `Accepted`, `Rejected`, `No Connection`, `Dropped`.
- **Transfer Rate**: Calculated in `kb/s` (kilobits per second) for each transferred instance.

---

## DICOMweb RESTful Services (PS3.18)

The server exposes standard DICOMweb REST services mounted at `/dicomweb/...` (and aliased at `/api/v1/dicomweb/...` and direct root `/studies`):

### 1. QIDO-RS (Query / Search DICOM Objects)

| Endpoint | Description | Response Type |
| :--- | :--- | :--- |
| `GET /dicomweb/studies` | Search for studies with query filters (`PatientID`, `PatientName`, `AccessionNumber`, `StudyDate`, `ModalitiesInStudy`, `limit`, `offset`) | `application/dicom+json` |
| `GET /dicomweb/studies/{studyUID}/series` | Search for series within a study | `application/dicom+json` |
| `GET /dicomweb/series` | Search for series across all studies | `application/dicom+json` |
| `GET /dicomweb/studies/{studyUID}/series/{seriesUID}/instances` | Search for instances within a series | `application/dicom+json` |
| `GET /dicomweb/instances` | Search for instances across all studies | `application/dicom+json` |

#### Example QIDO-RS Request
```bash
curl -X GET "http://127.0.0.1:8000/dicomweb/studies?PatientID=GSH*&limit=10" \
     -H "Accept: application/dicom+json"
```

---

### 2. WADO-RS (Retrieve DICOM Objects, Metadata & Rendered Previews)

| Endpoint | Description | Response Type |
| :--- | :--- | :--- |
| `GET /dicomweb/studies/{studyUID}` | Retrieve all DICOM instances in a study | `multipart/related; type="application/dicom"` |
| `GET /dicomweb/studies/{studyUID}/series/{seriesUID}` | Retrieve all DICOM instances in a series | `multipart/related; type="application/dicom"` |
| `GET /dicomweb/studies/{studyUID}/series/{seriesUID}/instances/{instanceUID}` | Retrieve a single DICOM instance | `multipart/related; type="application/dicom"` or `application/dicom` |
| `GET /dicomweb/studies/{studyUID}/metadata` | Retrieve study metadata (omitting pixel data) | `application/dicom+json` |
| `GET /dicomweb/studies/{studyUID}/series/{seriesUID}/instances/{instanceUID}/rendered` | Render instance pixel array to image | `image/jpeg` or `image/png` |
| `GET /dicomweb/studies/{studyUID}/series/{seriesUID}/instances/{instanceUID}/frames/{frameList}` | Retrieve raw pixel data for specific frames | `multipart/related; type="application/octet-stream"` |

#### Transfer Syntax Negotiation & Transcoding
WADO-RS endpoints automatically transcode instances on-the-fly to the requested transfer syntax specified in the `Accept` header (`transfer-syntax="..."`), direct request headers (`transfer-syntax`, `X-Transfer-Syntax`), or query parameters (`transferSyntax`, `transfer-syntax`, `transfer_syntax`). Supported values include friendly aliases (`JPEG200`, `JPEG200_LOSSLESS`, `JPEG2000`, `JPEG2000_LOSSLESS`, `RLE`, `RLE_LOSSLESS`, `RAW`, `JPEG`) as well as standard DICOM Transfer Syntax UIDs:

```bash
# Retrieve JPEG 2000 Lossless instances via Accept header alias
curl -X GET "http://127.0.0.1:8000/dicomweb/studies/2.25.12345" \
     -H 'Accept: multipart/related; type="application/dicom"; transfer-syntax="JPEG200"'

# Retrieve JPEG 2000 Lossless instances via UID
curl -X GET "http://127.0.0.1:8000/dicomweb/studies/2.25.12345" \
     -H 'Accept: multipart/related; type="application/dicom"; transfer-syntax="1.2.840.10008.1.2.4.90"'

# Retrieve RLE Lossless instances via query parameter
curl -X GET "http://127.0.0.1:8000/dicomweb/studies/2.25.12345?transferSyntax=RLE"

# Retrieve Explicit VR Little Endian (RAW) instances
curl -X GET "http://127.0.0.1:8000/dicomweb/studies/2.25.12345" \
     -H 'Accept: multipart/related; type="application/dicom"; transfer-syntax="RAW"'

# Retrieve JPEG Baseline 8-bit instances
curl -X GET "http://127.0.0.1:8000/dicomweb/studies/2.25.12345" \
     -H 'Accept: multipart/related; type="application/dicom"; transfer-syntax="1.2.840.10008.1.2.4.50"'
```


---

### 3. STOW-RS (Store Instances)

| Endpoint | Description | Request Type | Response Type |
| :--- | :--- | :--- | :--- |
| `POST /dicomweb/studies` | Store instances across studies | `multipart/related; type="application/dicom"` or `application/dicom` | `application/dicom+json` |
| `POST /dicomweb/studies/{studyUID}` | Store instances to a specific study | `multipart/related; type="application/dicom"` or `application/dicom` | `application/dicom+json` |

- **Storage Destination**: Composes valid Part-10 `.dcm` files into `./received/{StudyInstanceUID}/{SeriesInstanceUID}/{SOPInstanceUID}.dcm`.
- **In-Memory Retention**: Stored instances are indexed in memory immediately, enabling instant discovery and retrieval via QIDO-RS, WADO-RS, and DIMSE C-FIND/C-MOVE.
- **Duplicate Policy**: Configurable via `GOSMART_MS_STOW_DUPLICATE_HANDLING`:
  - `accept` (default): Overwrites existing instances and returns `200 OK` with `ReferencedSOPSequence`.
  - `warn`: Overwrites existing instances and returns `200 OK` with `WarningReason = 0xB000`.
  - `reject`: Rejects duplicate instances and returns `409 Conflict` with `FailureReason = 0x0111`.

#### Example STOW-RS Requests

```bash
# Upload a single DICOM file directly
curl -X POST "http://127.0.0.1:8000/dicomweb/studies" \
     -H "Content-Type: application/dicom" \
     --data-binary "@image.dcm"

# Upload multipart/related DICOM batch
curl -X POST "http://127.0.0.1:8000/dicomweb/studies" \
     -H 'Content-Type: multipart/related; type="application/dicom"; boundary="myboundary"' \
     --data-binary "@stow_batch.mime"
```

---

### 4. WADO-URI (Legacy Single-Object Retrieval)

```bash
curl -X GET "http://127.0.0.1:8000/dicomweb/wado?requestType=WADO&studyUID=2.25.123&seriesUID=2.25.456&objectUID=2.25.789&contentType=application/dicom" \
     -o instance.dcm
```

---

## Multi-Slice Templates & Synthetic Mode

The server supports loading multi-slice DICOM image datasets from dedicated subfolders under `templates/`:

```
templates/
├── sample_ct/                 # Multi-slice CT series folder
│   ├── 1.2.392.200036...dcm
│   └── ... (10 slices)
└── sample_mr/                 # Multi-slice MR series folder
    ├── IM_0001
    └── ... (10 slices)
```

### 1. Template Subfolder Rules & Modality Purity
- **No Standalone Root Files**: Standalone DICOM files placed directly in the `templates/` root directory are strictly prohibited and will raise a `ValueError` on startup. All template images must be housed within a subfolder.
- **Dynamic Modality Discovery**: The server dynamically detects the modality from the DICOM `Modality` tag `(0008, 0060)` within the datasets rather than parsing folder names.
- **Folder Modality Purity**: All DICOM instances within a subfolder must share the same modality. Mixing different modalities (e.g. CT and MR in the same folder) raises a `ValueError`.
- **Non-Image Object Exclusion**: Objects without pixel data, Presentation States (`PR`), Structured Reports (`SR`), and proprietary non-image objects (e.g., Philips private `XX_*` objects) are automatically filtered out.
- **Series Grouping & Slice Ordering**: Slices are grouped by `SeriesInstanceUID` and sorted deterministically by `(InstanceNumber, SliceLocation, ImagePositionPatient[2])`.

### 2. Non-Synthetic Mode (`GOSMART_MS_SYNTHETIC_MODE=false`, Default)
- **Exact Slice Delivery**: The server delivers the complete DICOM series for the exact slice count present in the selected template series.
- **Round-Robin Template Selection**: Available modalities are selected randomly. When multiple template series exist for a modality (e.g. two CT series or multiple MR series), the server sequentially cycles through them in round-robin order for subsequent MWL entries.
- **Pixel Data Preservation & No Burn-In**: Original pixel data and geometry from each slice are preserved untouched without burned-in annotations.
- **Transfer Syntax Transcoding**: If the requested transfer syntax differs from the template series, slices are transcoded on-the-fly without altering image pixels.

### 3. Synthetic Mode (`GOSMART_MS_SYNTHETIC_MODE=true`)
- **Configurable Slice Ranges**: Honors `GOSMART_MS_MIN_SLICES` and `GOSMART_MS_MAX_SLICES` (or custom per-request slice counts).
- **Cyclic Slice Rotation**: When the requested slice count differs from the template slice count, slices cycle sequentially (`slice_index = (i - 1) % M`).
- **Burn-In Metadata Annotations**: Patient demographics and slice indicators are burned into the image pixels.
- **Stress Mode Compatibility**: When combined with `GOSMART_MS_STRESS=true`, the first slice is computed and compressed once, and the precomputed compressed payload is reused across all remaining instances in the series.

---

## High-Throughput Stress Mode (`GOSMART_MS_STRESS`)

For load testing, high-frequency retrieval, or stress testing PACS/viewers, enable **Stress Mode** with `GOSMART_MS_STRESS=true`:
* **Single Frame Compression**: The compressed pixel frame is computed once per study/series rather than re-encoding per slice/instance.
* **Selective Demographics Overlay**: Burns patient and study demographics (`Patient Name`, `Patient ID`, `Study Date Study Time`) into the background image matrix, but omits the per-slice overlay line (`Image: <number>`).
* **Transfer Syntax Selection**:
  - **DIMSE Associations**: The single frame is compressed once directly in the association's negotiated transfer syntax.
  - **WADO-RS**: The transfer syntax of the first image/series/study request establishes the transfer syntax used to deliver the study or series.
* **Standards Compliance**: While pixel data is efficiently reused, each instance retains a unique `SOPInstanceUID` and sequential `InstanceNumber`.

---

## HL7 v2 MLLP Socket Listener (`hl7_*`)

The server runs a built-in, zero-dependency `asyncio` TCP socket listener running the Minimal Lower Layer Protocol (MLLP) on port `2575` (configurable via `GOSMART_MS_HL7_PORT`).

### Features & Workflow
- **Protocol**: Standard MLLP framing with `<SB>` (`0x0B`) and `<EB><CR>` (`0x1C 0x0D`).
- **Demographic Integrity**: Ingests `ORM^O01` messages and transfers patient demographics (`PatientName`, `PatientID`, `PatientBirthDate`, `PatientSex`, `AccessionNumber`, `Modality`, `Physicians`) directly into active MWL entries without altering or anonymizing values.
- **Modality Validation**: Checks requested modality against available template images (`templates/sample_ct`, `templates/sample_mr`). Orders requesting unsupported modalities are rejected with an MLLP `ACK^O01` containing `MSA|AE|<MsgID>|Rejected: No template images available for modality '<MOD>'`.
- **Order Cancellation**: Messages with `ORC-1` set to `CA`, `OC`, or `DC` automatically locate and remove matching MWL entries.
- **Downstream Retrieval**: Once an order is ingested into MWL, requesting the study via DICOM C-MOVE (`movescu`) or DICOMweb WADO-RS dynamically synthesizes instances carrying the order's exact demographics.

### HL7 Message Pusher CLI Utility (`push_hl7`)

To test the HL7 listener and generate ad-hoc Modality Worklist (MWL) entries, a lightweight, zero-dependency command line utility `push_hl7` and sample `ORM^O01` message file (`util/orm.txt`) are provided:

```bash
# Push sample util/orm.txt to default port 2575
python util/push_hl7.py

# Or via package script
uv run push-hl7
```

Options:
```bash
uv run push-hl7 [-h] [-H HOST] [-p PORT] [-t TIMEOUT] [-v] [file]

# Examples:
uv run push-hl7 -v util/orm.txt                    # Verbose mode showing raw ACK
uv run push-hl7 -H 127.0.0.1 -p 2575 custom.txt    # Custom host and port
```

---

## FHIR ServiceRequest & Bundle Ingestion (`fhir_*`)

The server provides zero-dependency REST endpoints to ingest FHIR R4/R5 imaging order bundles:
- `POST /api/v1/fhir_service_request`
- `POST /api/v1/fhir/Bundle`
- `POST /api/v1/fhir/ServiceRequest`

### Example FHIR Bundle Ingest
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/fhir_service_request" \
     -H "Content-Type: application/json" \
     -d '{
       "resourceType": "Bundle",
       "type": "collection",
       "entry": [
         {
           "resource": {
             "resourceType": "Patient",
             "id": "pat-01",
             "identifier": [{"value": "MRN-FHIR-7788"}],
             "name": [{"family": "SMITH", "given": ["ALICE"]}],
             "gender": "female",
             "birthDate": "1992-04-10"
           }
         },
         {
           "resource": {
             "resourceType": "ServiceRequest",
             "id": "sr-01",
             "status": "active",
             "identifier": [{"value": "ACC-FHIR-001"}],
             "code": {"text": "CT Abdomen Pelvis with Contrast"},
             "subject": {"reference": "Patient/pat-01"},
             "occurrenceDateTime": "2026-09-07T14:00:00"
           }
         }
       ]
     }'
```
Orders with `status` set to `revoked` or `entered-in-error` automatically remove the matching MWL item.

### Identifier Parsing Behavior & Enterprise Hospital Note
> [!NOTE]
> **Identifier Extraction Strategy**:
> To maximize developer friendliness and accommodate varied test harnesses, the built-in FHIR parser extracts the **first available identifier** (`patient.identifier[0].value` for Patient ID / MRN, and the first in `serviceRequest.identifier` for Accession Number, falling back to resource `.id` if omitted). It does not enforce specific hospital `system` URIs (such as `http://hospital.org` or `http://gosmart.health`).
>
> In real-world enterprise hospital environments (e.g. Epic, Cerner/Oracle Health), FHIR resources typically carry multiple identifiers (Enterprise Master Patient Index / EMPI, facility-specific MRNs, internal Community IDs, etc.) differentiated by authority OIDs (e.g. `urn:oid:1.2.840.114350...`) or HL7 v2 Table 0203 type codes (`code = "MR"` for Medical Record Number, `code = "ACSN"` for Accession Number). Developers adapting this mock server to simulate complex multi-identifier enterprise workflows can easily customize `FhirParserService` in `src/dicom_py_mock_server/services/fhir_parser.py` to match on specific `system` URIs or `type.coding` elements.

### FHIR Order Bundle Pusher Shell Script (`push_fhir.sh`)

A developer utility script and sample bundle are included in the `util/` folder:

```bash
# Push the sample bundle (util/fhir_order_bundle.json) to the default local endpoint
./util/push_fhir.sh

# Or specify a custom bundle JSON and endpoint URL:
./util/push_fhir.sh path/to/order_bundle.json http://127.0.0.1:8000/api/v1/fhir_service_request
```

---

## Running the Server

Start the FastAPI application and DICOM mock services:

```bash
uv run dicom-py-mock-server
```

Or run via python module:

```bash
python -m dicom_py_mock_server.main
```

## Running Tests & Quality Checks

### Run Unit Tests
```bash
uv run pytest
```

### Run Linting & Formatting Checks
```bash
uv run ruff check .
uv run ruff format --check .
```

### Run Package Security Audit
Scan dependencies against known vulnerability databases (PyPI Advisory Database / OSV):
```bash
uv run pip-audit
```

### Generate Software Bill of Materials (SBOM)
Generate and validate a standard CycloneDX 1.6 SBOM JSON file:
```bash
uv run cyclonedx-py environment --pyproject pyproject.toml .venv -o sbom.json --validate
```

---

## Standards Conformance & Technical Documentation

- **[DICOM Conformance Statement](./docs/dicom_conformance_statement.md)**: Full NEMA PS 3.2 Conformance Statement specifying supported DIMSE services (C-ECHO, C-FIND, C-MOVE, C-STORE, MWL), transfer syntaxes (RAW, JPEG Process 1, JPEG 2000, RLE), DICOMweb services (QIDO-RS, WADO-RS, WADO-URI), and order ingestion pipelines.
- **[Design Controls Documentation](./docs/design/README.md)**: Architecture specifications, Hazard Analysis (ISO 14971), V&V Plan, and Requirements Traceability Matrix.

---

## Release & Changelog

Releases are distributed strictly as source-code releases. For details on version history, changes, and upgrades, see [CHANGELOG.md](./CHANGELOG.md).

## Contacting the Developer Community

* Join [Discussions](https://github.com/gosmart-health/dicom-py-mock-server/discussions) 
* Add or Inspect [Issues](https://github.com/gosmart-health/dicom-py-mock-server/issues)
