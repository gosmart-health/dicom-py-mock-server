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
2. **DICOM SCP Services**: Built-in DICOM C-FIND, C-MOVE/GET, and MWL (Modality Worklist) SCP network listeners.
3. **Modality Worklist (MWL) Synthesis**: Automated business-hours MWL entry creation and retention window management.
4. **MCP Integration Provisioning**: Exposes server capabilities to AI Assistants (AGY, Claude Desktop, Cursor, etc.) over Server-Sent Events (SSE) transport.

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
| `GOSMART_MS_TRANSFER_SYNTAX` | `TRANSFER_SYNTAX` | `RAW` | Default DICOM Transfer Syntax (`RAW`, `JPEG`, `JPEG2000`, `RLE`). |
| `GOSMART_MS_MOVE_DESTINATIONS` | `MOVE_DESTINATIONS` | `{}` | JSON string mapping C-MOVE destination AE Titles to target host/port objects. |
| `GOSMART_MS_APP_NAME` | `APP_NAME` | `DICOM Mock Server` | Application display name. |
| `GOSMART_MS_APP_VERSION` | `APP_VERSION` | `0.1.0` | Application version string. |

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

## Running Tests

Run unit and integration tests:

```bash
uv run pytest
```
