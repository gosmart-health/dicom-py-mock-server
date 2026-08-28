"""MCP Service handling JSON-RPC protocol over SSE for DICOM Mock Server capabilities."""

import asyncio
import json
import uuid
from typing import Any

from dicom_py_mock_server.config import AppConfig, config
from dicom_py_mock_server.logging_config import get_logger
from dicom_py_mock_server.models.dicom import MockDicomRequest, MwlGenerateRequest, RawImageGeneratorRequest
from dicom_py_mock_server.services.generator import DicomGeneratorService
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService
from dicom_py_mock_server.services.scp import DicomScpService

logger = get_logger(__name__)


class McpService:
    """MCP Protocol and Session Handler exposing DICOM mock services as MCP tools."""

    def __init__(
        self,
        app_config: AppConfig = config,
        generator_service: DicomGeneratorService | None = None,
        mwl_service: MwlGeneratorService | None = None,
        scp_service: DicomScpService | None = None,
    ):
        self.config = app_config
        self.generator_service = generator_service or DicomGeneratorService()
        self.mwl_service = mwl_service or MwlGeneratorService(self.config)
        self.scp_service = scp_service or DicomScpService(
            ae_title=self.config.ae_title,
            port=self.config.scp_port,
            mwl_service=self.mwl_service,
        )
        self._sessions: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}

    def create_session(self) -> str:
        """Create a new SSE session and return unique session ID."""
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = asyncio.Queue()
        logger.info("mcp_session_created", session_id=session_id)
        return session_id

    def remove_session(self, session_id: str) -> None:
        """Remove session and unblock any waiting listener."""
        if session_id in self._sessions:
            queue = self._sessions.pop(session_id)
            queue.put_nowait(None)
            logger.info("mcp_session_removed", session_id=session_id)

    def get_session_queue(self, session_id: str) -> asyncio.Queue[dict[str, Any] | None] | None:
        """Get message queue for session ID."""
        return self._sessions.get(session_id)

    def push_session_event(self, session_id: str, data: dict[str, Any]) -> bool:
        """Push a JSON-RPC message event into session's SSE queue."""
        queue = self._sessions.get(session_id)
        if queue is not None:
            queue.put_nowait(data)
            return True
        return False


    def list_tools(self) -> list[dict[str, Any]]:
        """Return MCP tools definitions representing REST API capabilities."""
        return [
            {
                "name": "health_check",
                "description": "Check service health status and application metadata.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "generate_mock_dicom",
                "description": "Generate synthetic DICOM P10 objects with custom metadata and save to disk.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "patient": {
                            "type": "object",
                            "properties": {
                                "patient_id": {"type": "string", "default": "MOCK-PATIENT-001"},
                                "patient_name": {"type": "string", "default": "Doe^John"},
                                "patient_birth_date": {"type": "string", "default": "19800101"},
                                "patient_sex": {"type": "string", "default": "M"},
                            },
                        },
                        "study": {
                            "type": "object",
                            "properties": {
                                "study_instance_uid": {"type": "string"},
                                "study_date": {"type": "string", "default": "20260828"},
                                "study_time": {"type": "string", "default": "120000"},
                                "accession_number": {"type": "string", "default": "ACC-001"},
                                "study_description": {"type": "string", "default": "Mock Chest CT"},
                            },
                        },
                        "series": {
                            "type": "object",
                            "properties": {
                                "series_instance_uid": {"type": "string"},
                                "modality": {"type": "string", "default": "CT"},
                                "series_number": {"type": "integer", "default": 1},
                                "series_description": {"type": "string", "default": "Axial Standard"},
                            },
                        },
                        "num_instances": {"type": "integer", "default": 1, "minimum": 1, "maximum": 100},
                        "rows": {"type": "integer", "default": 512, "minimum": 16, "maximum": 2048},
                        "columns": {"type": "integer", "default": 512, "minimum": 16, "maximum": 2048},
                        "transfer_syntax": {"type": "string"},
                        "burn_in_text": {"type": "boolean", "default": True},
                    },
                },
            },
            {
                "name": "generate_raw_dicom_image",
                "description": "Generate a 16-bit 512x512 raw DICOM image with burned-in patient and study metadata strings.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "patient_name": {"type": "string", "default": "Doe^John"},
                        "patient_id": {"type": "string", "default": "MOCK-PATIENT-001"},
                        "study_date": {"type": "string", "default": "20260828"},
                        "study_time": {"type": "string", "default": "120000"},
                        "image_number": {"type": "integer", "default": 1},
                        "rows": {"type": "integer", "default": 512},
                        "columns": {"type": "integer", "default": 512},
                        "transfer_syntax": {"type": "string"},
                    },
                },
            },
            {
                "name": "get_scp_status",
                "description": "Get DICOM SCP (C-FIND, C-MOVE, MWL) listener status.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "start_scp",
                "description": "Start the DICOM SCP listener service.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "stop_scp",
                "description": "Stop the DICOM SCP listener service.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "get_mwl_status",
                "description": "Get Modality Worklist (MWL) generator status and active entry counts.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "list_mwl_entries",
                "description": "List currently active Modality Worklist (MWL) entries within retention window.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "generate_mwl_entry",
                "description": "Manually generate a new MWL entry with optional custom fields.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "patientName": {"type": "string"},
                        "patientId": {"type": "string"},
                        "mrn": {"type": "string"},
                        "dob": {"type": "string"},
                        "sex": {"type": "string"},
                        "modality": {"type": "string"},
                        "accession": {"type": "string"},
                        "studyUid": {"type": "string"},
                        "reason": {"type": "string"},
                        "studyDescription": {"type": "string"},
                        "department": {"type": "string"},
                    },
                },
            },
            {
                "name": "start_mwl_auto_generation",
                "description": "Start background MWL automated entry generation loop.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "stop_mwl_auto_generation",
                "description": "Stop background MWL automated entry generation loop.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    async def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute tool by name and return result formatted for MCP."""
        try:
            if name == "health_check":
                result = {"status": "ok", "app": self.config.app_name, "version": self.config.app_version}
            elif name == "generate_mock_dicom":
                request_model = MockDicomRequest.model_validate(arguments or {})
                resp = self.generator_service.generate_and_save(request_model, target_dir=self.config.storage_dir)
                result = resp.model_dump()
            elif name == "generate_raw_dicom_image":
                raw_req = RawImageGeneratorRequest.model_validate(arguments or {})
                mock_req = MockDicomRequest(
                    patient={"patient_id": raw_req.patient_id, "patient_name": raw_req.patient_name},
                    study={"study_date": raw_req.study_date, "study_time": raw_req.study_time},
                    num_instances=1,
                    rows=raw_req.rows,
                    columns=raw_req.columns,
                    transfer_syntax=raw_req.transfer_syntax,
                    burn_in_text=True,
                )
                resp = self.generator_service.generate_and_save(mock_req, target_dir=self.config.storage_dir)
                result = resp.model_dump()
            elif name == "get_scp_status":
                result = self.scp_service.get_status().model_dump()
            elif name == "start_scp":
                result = self.scp_service.start().model_dump()
            elif name == "stop_scp":
                result = self.scp_service.stop().model_dump()
            elif name == "get_mwl_status":
                result = self.mwl_service.get_status().model_dump()
            elif name == "list_mwl_entries":
                result = [entry for entry in self.mwl_service.list_entries()]
            elif name == "generate_mwl_entry":
                request_model = MwlGenerateRequest.model_validate(arguments or {}) if arguments else None
                custom_dict = request_model.model_dump(by_alias=True, exclude_none=True) if request_model else None
                record = self.mwl_service.add_entry(custom=custom_dict)
                result = {
                    "success": True,
                    "patient_id": record["patient_id"],
                    "accession": record["accession"],
                    "modality": record["modality"],
                    "study_uid": record["study_uid"],
                    "json_entry": record["json_entry"],
                }
            elif name == "start_mwl_auto_generation":
                result = self.mwl_service.start_auto_generation().model_dump()
            elif name == "stop_mwl_auto_generation":
                result = self.mwl_service.stop_auto_generation().model_dump()
            else:
                return {
                    "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                    "isError": True,
                }

            return {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": False,
            }
        except Exception as exc:
            logger.error("mcp_tool_execution_failed", tool=name, error=str(exc))
            return {
                "content": [{"type": "text", "text": f"Error executing {name}: {exc!s}"}],
                "isError": True,
            }

    async def handle_jsonrpc_request(self, session_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
        """Process incoming MCP JSON-RPC 2.0 payload and return response or queue it."""
        jsonrpc = body.get("jsonrpc")
        if jsonrpc != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": -32600, "message": "Invalid Request: jsonrpc must be '2.0'"},
            }

        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": self.config.app_name,
                        "version": self.config.app_version,
                    },
                },
            }
        elif method == "notifications/initialized":
            # Client notification, no JSON-RPC response required
            return None
        elif method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.list_tools()},
            }
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            call_result = await self.execute_tool(tool_name, tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": call_result,
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
