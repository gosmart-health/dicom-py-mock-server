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

---

## Capabilities & Features

1. **Synthetic DICOM Generation**: Generate customizable DICOM P10 objects with specified Patient, Study, Series, and instance metadata.
2. **Deterministic DICOM UID Generation (ITU-T X.667 / ISO/IEC 9834-8)**: Generates standards-compliant `2.25.<u128>` UIDs using SHA-1 (UUIDv5) or MD5 (UUIDv3) over a persistent namespace, preventing PHI exposure while maintaining hierarchical reproducibility (Study -> Series -> Instance).
3. **DICOM SCP Services**: Built-in DICOM C-FIND, C-MOVE/GET, and MWL (Modality Worklist) SCP network listeners.
4. **Modality Worklist (MWL) Synthesis**: Automated business-hours MWL entry creation and retention window management.
5. **MCP Integration Provisioning**: Exposes server capabilities to AI Assistants (AGY, Claude Desktop, Cursor, etc.) over Server-Sent Events (SSE) transport.
6. **Template SOP Compression & PACS Verification**: Synthesize valid DICOM Part-10 files directly from templates (such as `templates/CT_small.dcm`) with burned metadata text, precomputed background test patterns, and supported compression syntaxes (`JPEG2000_LOSSLESS`, `JPEG2000_LOSSY`, `JPEG`, `RLE`, `EXPLICIT_VR_LITTLE_ENDIAN`, `IMPLICIT_VR_LITTLE_ENDIAN`) saved to `test_output/` for PACS viewer inspection.

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
| `GORMART_MS_CSV_PATH` | `GOSMART_MS_CSV_PATH`, `CSV_PATH` | `./csv` | Local directory path to store C-STORE association audit CSV files (`yyyymmddhhmmss_<AE_Title>.csv`). |
| `GOSMART_TEMPLATES_PATH` | `GOSMART_MS_TEMPLATES_PATH`, `TEMPLATES_PATH` | `./templates` | Directory containing DICOM (`.dcm`, `.dicom`) or JSON templates for synthesis. |
| `GOSMART_MS_LOG_LEVEL` | `LOG_LEVEL` | `INFO` | Logging verbosity level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |
| `GOSMART_MS_LOG_PATH` | `GOSMART_MS_LOG_FILE`, `LOG_PATH`, `LOG_FILE` | `./logs` | Directory or file path for rotated log files (`dicom_mock_server.log`). |
| `GOSMART_MS_LOG_ROTATION_DAYS` | `LOG_ROTATION_DAYS` | `7` | Log file auto-rotation interval in days (`TimedRotatingFileHandler`). |
| `GOSMART_MS_LOG_BACKUP_COUNT` | `LOG_BACKUP_COUNT` | `4` | Number of rotated backup log files to retain on disk. |
| `GOSMART_MS_LOG_JSON_FORMAT` | `LOG_JSON_FORMAT` | `true` | Format log file entries as structured JSON Lines. |
| `GOSMART_MS_MWL_WINDOW_HR` | `MWL_WINDOW_HR` | `24` | Retention window in hours for active Modality Worklist (MWL) entries. |
| `GOSMART_MS_MWL_RATE_PER_HR` | `MWL_RATE_PER_HR` | `12.0` | Base MWL creation rate per hour during business hours (9 AM - 5 PM local; 5% rate off-hours). |
| `GOSMART_MS_MCP_ENABLED` | `MCP_ENABLED` | `true` | Enable Model Context Protocol (MCP) SSE integration endpoints. |
| `GOSMART_MS_MCP_SSE_PATH` | `MCP_SSE_PATH` | `/sse` | Base HTTP endpoint path for MCP SSE streams. |
| `GOSMART_MS_MIN_SLICES` | `MIN_SLICES` | `8` | Minimum slice count for synthetic series generation during C-MOVE. |
| `GOSMART_MS_MAX_SLICES` | `MAX_SLICES` | `24` | Maximum slice count for synthetic series volume generation. |
| `GOSMART_MS_TRANSFER_SYNTAX` | `TRANSFER_SYNTAX` | `JPEG2000_LOSSLESS` | Default DICOM Transfer Syntax (`RAW`, `JPEG`, `JPEG2000`, `JPEG2000_LOSSLESS`, `RLE`). |
| `GOSMART_MS_MOVE_DESTINATIONS` | `MOVE_DESTINATIONS` | `{}` | JSON string mapping C-MOVE destination AE Titles to target host/port objects. |
| `GOSMART_MS_PATIENT_SUFFIX` | `PATIENT_SUFFIX` | `_GSH` | Suffix appended to synthetic patient last name to avoid PACS collisions (empty strings permitted). |
| `GOSMART_MS_PN_SUFFIX` | `PN_SUFFIX` | `_GSH` | Suffix appended to generated physician names (Referring, Performing, Reading) to avoid PACS collisions (empty strings permitted). |
| `GORMART_MS_INSTITUTION_NAME` | `GOSMART_MS_INSTITUTION_NAME`, `INSTITUTION_NAME` | `GO SMART CLINIC` | Default Institution Name attribute for synthesized studies and MWL entries. |
| `GOSMART_MS_ID_PREFIX` | `ID_PREFIX` | `GSH-` | Prefix prepended to synthetic Patient ID and Accession number to avoid PACS collisions (empty strings permitted). |
| `GOSMART_MS_NAMESPACE_UUID` | `GOSMART_MS_DICOM_NAMESPACE_UUID`, `NAMESPACE_UUID` | `6ba7b810-9dad-11d1-80b4-00c04fd430c8` | Persistent UUID namespace used for deterministic ITU-T X.667 DICOM UID generation. |
| `GOSMART_MS_UID_VERSION` | `GOSMART_MS_DICOM_UID_VERSION`, `UID_VERSION` | `5` | UUID version for deterministic DICOM UID generation (`5` for SHA-1, `3` for MD5). |
| `GOSMART_MS_APP_NAME` | `APP_NAME` | `DICOM Mock Server` | Application display name. |
| `GOSMART_MS_APP_VERSION` | `APP_VERSION` | `0.1.1` | Application version string. |

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

### 3. WADO-URI (Legacy Single-Object Retrieval)

```bash
curl -X GET "http://127.0.0.1:8000/dicomweb/wado?requestType=WADO&studyUID=2.25.123&seriesUID=2.25.456&objectUID=2.25.789&contentType=application/dicom" \
     -o instance.dcm
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

## Release & Changelog

Releases are distributed strictly as source-code releases. For details on version history, changes, and upgrades, see [CHANGELOG.md](./CHANGELOG.md).

## Contacting the Developer Community

* Join [Discussions](https://github.com/gosmart-health/dicom-py-mock-server/discussions) 
* Add or Inspect [Issues](https://github.com/gosmart-health/dicom-py-mock-server/issues)
