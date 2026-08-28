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

To connect an MCP-compatible AI agent (such as Antigravity / AGY, Claude Desktop, or Cursor) to the server via SSE, add the following entry to your MCP configuration file (`mcp_config.json` / `claude_desktop_config.json`):

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
