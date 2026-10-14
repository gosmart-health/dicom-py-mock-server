# Walkthrough: Automated Study Push (Auto-Push)

## Overview & Goal

Added automated background pushing of synthesized DICOM studies (including all associated series and image instances) to a configured destination Application Entity (AE) at a configurable interval in seconds.

---

## Requirements Implemented

### 1. Environment Variables & Configuration Data Models
- **`GOSMART_MS_AUTO_PUSH_AE`** (alias: `AUTO_PUSH_AE`): Target AE title to push to (default: `""`, disabled).
- **`GOSMART_MS_AUTO_PUSH_HOST`** (alias: `AUTO_PUSH_HOST`): Target host / IP to push to (default: `"127.0.0.1"`).
- **`GOSMART_MS_AUTO_PUSH_PORT`** (alias: `AUTO_PUSH_PORT`): Target DICOM port to push to (default: `11113`).
- **`GOSMART_MS_AUTO_PUSH_SEC`** (alias: `AUTO_PUSH_SEC`): Push interval in seconds (default: `0.0`, disabled when 0 or empty AE).
- Added `auto_push_ae`, `auto_push_host`, `auto_push_port`, and `auto_push_sec` fields to `AppConfig` in `src/dicom_py_mock_server/config.py`.
- Created Pydantic data models in `src/dicom_py_mock_server/models/dicom.py`:
  - `AutoPushRequest`:
    ```json
    {
      "intervalSec": 30,
      "targetAeTitle": "VIEWER_SCP",
      "targetHost": "127.0.0.1",
      "targetPort": 11113
    }
    ```
  - `AutoPushResponse`:
    ```json
    {
      "success": true,
      "message": "string",
      "targetAeTitle": "string",
      "targetHost": "127.0.0.1",
      "targetPort": 11113,
      "intervalSec": 30.0,
      "is_auto_pushing": true
    }
    ```
  - Extended `ScpStatusResponse` with `auto_push_ae`, `auto_push_host`, `auto_push_port`, `auto_push_sec`, and `is_auto_pushing`.

### 2. REST API Endpoints
- **`POST /api/v1/scp/auto-push`**:
  - Activates auto-push when `intervalSec > 0` and `targetAeTitle` is non-empty.
  - Deactivates auto-push when `intervalSec == 0` or `targetAeTitle` is empty string.
  - Passes destination host and port directly to the SCP service.
- **`GET /api/v1/scp/auto-push`**:
  - Returns current auto-push configuration and running state with target AE details.

### 3. MCP (Model Context Protocol) Integration
- Updated tool `auto_push` in MCP SSE service (`src/dicom_py_mock_server/services/mcp.py`):
  - Description: *"Configure auto push of generated studies (associated series and images) to a destination at a configured interval in seconds. Permit auto push to {AE Title} every {interval} seconds. Set intervalSec to 0 to disable auto push."*
  - Arguments: `targetAeTitle` (string), `intervalSec` (number), optional `targetHost` (string, default: "127.0.0.1"), and optional `targetPort` (integer, default: 11113).
- Updated MCP `update_config` tool to allow dynamic runtime configuration of `auto_push_ae`, `auto_push_host`, `auto_push_port`, and `auto_push_sec`.

### 4. Background Service & Lifecycle
- `DicomScpService` (`src/dicom_py_mock_server/services/scp.py`):
  - `configure_auto_push(target_ae_title, interval_sec, target_host, target_port)`
  - `start_auto_push(...)`
  - `stop_auto_push()`
  - `get_auto_push_status()`
  - `_auto_push_worker()`: Background worker thread running on `threading.Thread` and managed by `threading.Event` stop signal, completely decoupling auto-push from asyncio event loops.
  - `_push_one_auto_study()`: Generates complete study, series, and image slices using `DicomGeneratorService.create_instances_from_mwl` and transmits them via DICOM C-STORE.
  - Destination host and port resolution automatically checks `config.move_destinations` for configured AE targets if default `127.0.0.1:11113` is kept.
- Application lifespan (`src/dicom_py_mock_server/main.py`):
  - Starts auto-push on application launch if environment variables are configured.
  - Cleanly terminates auto-push background tasks during server shutdown.

---

## Verification & Test Results

### 1. Automated Test Suite
- **Configuration Tests** (`tests/test_config.py`):
  - Verified default values (`auto_push_ae=""`, `auto_push_sec=0.0`, `auto_push_host="127.0.0.1"`, `auto_push_port=11113`).
  - Verified environment variables `GOSMART_MS_AUTO_PUSH_AE`, `GOSMART_MS_AUTO_PUSH_HOST`, `GOSMART_MS_AUTO_PUSH_PORT`, and `GOSMART_MS_AUTO_PUSH_SEC`.
  - Verified alias environment variables `AUTO_PUSH_AE`, `AUTO_PUSH_HOST`, `AUTO_PUSH_PORT`, and `AUTO_PUSH_SEC`.
- **API Endpoint Tests** (`tests/test_api.py`):
  - Tested `POST /api/v1/scp/auto-push` with active interval and Target AE schema.
  - Tested `GET /api/v1/scp/auto-push` status query.
  - Tested `POST /api/v1/scp/auto-push` disabling with `intervalSec=0`.
  - Tested `GET /api/v1/scp/status` response schema containing auto-push attributes.
- **End-to-End Workflow Tests** (`tests/test_auto_push.py`):
  - Verified periodic C-STORE transmission of generated study instances to a `MockStorageScp`.
  - Verified received dataset tags (`PatientID`, `StudyInstanceUID`, `SeriesInstanceUID`, `SOPInstanceUID`, `PixelData`).
  - Verified MCP tool `auto_push` enabling and disabling.
  - Verified MCP tool `update_config` synchronization.
  - Verified execution from worker threads with `threading.Thread`.

### 2. Test Execution
```bash
uv run pytest tests/test_config.py tests/test_api.py tests/test_auto_push.py
```
**Result**: 17 passed.

Full suite:
```bash
uv run pytest
```
**Result**: 155 passed, 2 skipped in ~85s.

### 3. Code Quality & Linting Gate
```bash
uv run ruff check .
uv run ruff format --check .
```
**Result**: All checks passed! 68 files already formatted.

---

## Usage Examples

### 1. Environment Variable Setup
```bash
export GOSMART_MS_AUTO_PUSH_AE="VIEWER_SCP"
export GOSMART_MS_AUTO_PUSH_SEC="30"
./start.sh
```

### 2. cURL REST API

#### Enable Auto-Push
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/scp/auto-push" \
     -H "Content-Type: application/json" \
     -d '{
       "ae_title": "VIEWER_SCP",
       "interval_sec": 30
     }'
```

#### Query Status
```bash
curl "http://127.0.0.1:8000/api/v1/scp/auto-push"
```

#### Disable Auto-Push
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/scp/auto-push" \
     -H "Content-Type: application/json" \
     -d '{
       "ae_title": "VIEWER_SCP",
       "interval_sec": 0
     }'
```

### 3. MCP AI Agent Tool Call
```json
{
  "name": "auto_push",
  "arguments": {
    "ae_title": "VIEWER_SCP",
    "interval_sec": 15
  }
}
```

---

## Updated Documentation & Design Artifacts

- `README.md`: Feature list, MCP tools table, environment variables table, and REST API documentation.
- `docs/dicom_conformance_statement.md`: Configuration parameter table and REST endpoint list.
- `docs/design/gsms_000_software_requirements_spec.md`: Added `REQ-FUN-038` and `REQ-FUN-039`.
- `docs/design/gsms_010_system_design_specification.md`: Updated API subsystem routes, models, and SCP subsystem.
- `docs/design/gsms_030_verification_and_validation_plan.md`: Added Auto-Push test suite protocol.
