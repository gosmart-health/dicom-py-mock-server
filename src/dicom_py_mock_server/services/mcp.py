"""MCP Service handling JSON-RPC protocol over SSE for DICOM Mock Server capabilities."""

import asyncio
import json
import uuid
from typing import Any

from dicom_py_mock_server.config import AppConfig, config
from dicom_py_mock_server.logging_config import get_logger
from dicom_py_mock_server.models.dicom import (
    MockDicomRequest,
    MwlGenerateRequest,
    RawImageGeneratorRequest,
    RemoveAccessionRequest,
    ScanningOrderRequest,
)
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
                "name": "get_config",
                "description": (
                    "Get current DICOM Mock Server configuration settings. "
                    "Optionally provide 'keys' array to retrieve specific configuration parameters."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of configuration keys to retrieve (returns all if omitted)",
                        }
                    },
                },
            },
            {
                "name": "update_config",
                "description": (
                    "Dynamically update one or more server configuration settings in AppConfig. "
                    "Supports updating every configuration parameter (e.g. storage_dir, transfer_syntax, "
                    "min_slices, max_slices, stress, synthetic_mode, institution_name, id_prefix, "
                    "patient_suffix, pn_suffix, mwl_window_hr, mwl_rate_per_hr, log_level, scp_ae_title, scp_port, "
                    "received_dir, stow_duplicate_handling, move_destinations, dicom_namespace_uuid, etc.)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "storage_dir": {"type": "string", "description": "Path to store DICOM files"},
                        "received_dir": {"type": "string", "description": "Path to store received STOW-RS files"},
                        "stow_duplicate_handling": {
                            "type": "string",
                            "description": "Policy for duplicates: 'accept', 'warn', 'reject'",
                        },
                        "log_level": {"type": "string", "description": "Logging level (DEBUG, INFO, WARNING, ERROR)"},
                        "templates_path": {"type": "string", "description": "Path to templates directory"},
                        "mwl_window_hr": {"type": "integer", "description": "MWL active retention window in hours"},
                        "mwl_rate_per_hr": {"type": "number", "description": "Creation rate of MWL entries per hour"},
                        "min_slices": {"type": "integer", "description": "Minimum slices for volume image generation"},
                        "max_slices": {"type": "integer", "description": "Maximum slices for volume image generation"},
                        "transfer_syntax": {
                            "type": "string",
                            "description": "Default DICOM Transfer Syntax (RAW, JPEG, JPEG2000, etc.)",
                        },
                        "stress": {"type": "boolean", "description": "Enable stress mode"},
                        "synthetic_mode": {"type": "boolean", "description": "Enable synthetic slice rotation mode"},
                        "institution_name": {"type": "string", "description": "Default Institution Name"},
                        "patient_suffix": {"type": "string", "description": "Suffix appended to patient last name"},
                        "pn_suffix": {"type": "string", "description": "Suffix appended to physician names"},
                        "id_prefix": {"type": "string", "description": "Prefix for patient ID and accession"},
                        "scp_ae_title": {"type": "string", "description": "Application Entity Title for SCP"},
                        "scp_port": {"type": "integer", "description": "DICOM SCP port"},
                        "move_destinations": {"type": "object", "description": "Mapping of destination AE titles"},
                        "dicom_namespace_uuid": {
                            "type": "string",
                            "description": "UUID namespace for deterministic UIDs",
                        },
                        "dicom_uid_version": {
                            "type": "integer",
                            "description": "UUID version (5 for SHA-1, 3 for MD5)",
                        },
                        "settings": {
                            "type": "object",
                            "description": "Optional dictionary of arbitrary configuration key-value pairs to update",
                        },
                    },
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
                                "institution_name": {"type": "string", "default": "GO SMART CLINIC"},
                                "referring_physician_name": {"type": "string"},
                                "reading_physician_name": {"type": "string"},
                                "performing_physician_name": {"type": "string"},
                            },
                        },
                        "series": {
                            "type": "object",
                            "properties": {
                                "series_instance_uid": {"type": "string"},
                                "modality": {"type": "string", "default": "CT"},
                                "series_number": {"type": "integer", "default": 1},
                                "series_description": {"type": "string", "default": "Axial Standard"},
                                "performing_physician_name": {"type": "string"},
                            },
                        },
                        "num_instances": {"type": "integer", "default": 1, "minimum": 1, "maximum": 1024},
                        "rows": {"type": "integer", "default": 512, "minimum": 16, "maximum": 2048},
                        "columns": {"type": "integer", "default": 512, "minimum": 16, "maximum": 2048},
                        "transfer_syntax": {"type": "string"},
                        "burn_in_text": {"type": "boolean", "default": True},
                        "stress": {"type": "boolean"},
                        "include_slice_overlay": {"type": "boolean"},
                        "storage_dir": {"type": "string"},
                    },
                },
            },
            {
                "name": "generate_raw_dicom_image",
                "description": (
                    "Generate a 16-bit 512x512 raw DICOM image with burned-in patient and study metadata strings."
                ),
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
                        "stress": {"type": "boolean"},
                        "include_slice_overlay": {"type": "boolean"},
                        "storage_dir": {"type": "string"},
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
                "name": "get_worklist",
                "description": (
                    "Get or show the current Modality Worklist (MWL) entries. "
                    "Use this tool whenever requested to 'show me current worklist', 'show worklist', "
                    "'list worklist', or 'get active MWL entries'."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "list_mwl_entries",
                "description": (
                    "List or show currently active Modality Worklist (MWL) entries within retention window. "
                    "Use this tool whenever requested to 'show me current worklist' or 'list worklist entries'."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "generate_scanning_order",
                "description": (
                    "Generate a new clinical scanning order (Modality Worklist scheduled procedure step). "
                    "Requires patient name, patient ID, accession number, and modality, with optional "
                    "study description phrase."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "patient_name": {
                            "type": "string",
                            "description": "Patient full name (e.g. 'Doe^John' or 'John Doe')",
                        },
                        "patient_id": {
                            "type": "string",
                            "description": "Patient ID / MRN (e.g. 'GSH-12345' or 'MOCK-PATIENT-001')",
                        },
                        "accession_number": {
                            "type": "string",
                            "description": "Unique accession number for the scanning order (e.g. 'ACC-2026-001')",
                        },
                        "modality": {
                            "type": "string",
                            "description": "Imaging modality (e.g. 'CT', 'MR', 'US', 'CR', 'DX', 'XA', 'NM', 'PT')",
                        },
                        "study_description": {
                            "type": "string",
                            "description": "Optional study description phrase (e.g. 'CT Head without contrast')",
                        },
                        "dob": {
                            "type": "string",
                            "description": "Optional date of birth (YYYYMMDD)",
                        },
                        "sex": {
                            "type": "string",
                            "description": "Optional patient sex ('M', 'F', 'O')",
                        },
                        "institution_name": {
                            "type": "string",
                            "description": "Optional institution / hospital name",
                        },
                        "referring_physician": {
                            "type": "string",
                            "description": "Optional referring physician name",
                        },
                        "performing_physician": {
                            "type": "string",
                            "description": "Optional performing physician / radiologist name",
                        },
                        "reading_physician": {
                            "type": "string",
                            "description": "Optional reading physician name",
                        },
                    },
                    "required": ["patient_name", "patient_id", "accession_number", "modality"],
                },
            },
            {
                "name": "generate_mwl_entry",
                "description": "Manually generate a new MWL entry with optional custom fields.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "patientName": {"type": "string"},
                        "patient_name": {"type": "string"},
                        "patientId": {"type": "string"},
                        "patient_id": {"type": "string"},
                        "mrn": {"type": "string"},
                        "dob": {"type": "string"},
                        "sex": {"type": "string"},
                        "modality": {"type": "string"},
                        "accession": {"type": "string"},
                        "accession_number": {"type": "string"},
                        "studyUid": {"type": "string"},
                        "study_uid": {"type": "string"},
                        "reason": {"type": "string"},
                        "studyDescription": {"type": "string"},
                        "study_description": {"type": "string"},
                        "department": {"type": "string"},
                        "institutionName": {"type": "string"},
                        "institution_name": {"type": "string"},
                        "referringPhysician": {"type": "string"},
                        "performingPhysician": {"type": "string"},
                        "readingPhysician": {"type": "string"},
                    },
                },
            },
            {
                "name": "remove_accession_number",
                "description": (
                    "Remove a scanning order / Modality Worklist (MWL) entry by accession number. "
                    "Use this tool whenever requested to 'remove accession number <value>' or 'cancel order <value>'."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "accession_number": {
                            "type": "string",
                            "description": "Accession number of the scanning order to remove (e.g. 'ACC-001')",
                        },
                        "accession": {
                            "type": "string",
                            "description": "Alias for accession_number",
                        },
                    },
                    "required": ["accession_number"],
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
            {
                "name": "move_study",
                "description": (
                    "Move or push DICOM study instances matching a Patient ID, Accession number, "
                    "or Study Instance UID to a target DICOM Storage SCP (AE Title, Host, and Port). "
                    "Use this tool whenever requested to 'move patient <id> to AE title, host, and port' "
                    "or 'move accession <accession> to AE title, host, and port'."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "patient_id": {
                            "type": "string",
                            "description": "Patient ID of the study to move (e.g. 'PAT-12345')",
                        },
                        "accession": {
                            "type": "string",
                            "description": "Accession number of the study to move (e.g. 'ACC-98765')",
                        },
                        "study_uid": {
                            "type": "string",
                            "description": "Study Instance UID of the study to move",
                        },
                        "target_ae_title": {
                            "type": "string",
                            "description": (
                                "Target DICOM Application Entity (AE) Title (e.g. 'VIEWER_SCP', 'ORTHANC', 'HOROS')"
                            ),
                        },
                        "target_host": {
                            "type": "string",
                            "default": "127.0.0.1",
                            "description": "Target host IP or hostname (default: 127.0.0.1)",
                        },
                        "target_port": {
                            "type": "integer",
                            "default": 11113,
                            "description": "Target DICOM port (e.g. 11113, 104, 4242)",
                        },
                    },
                    "required": ["target_ae_title"],
                },
            },
        ]

    async def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute tool by name and return result formatted for MCP."""
        try:
            if name == "health_check":
                result = {"status": "ok", "app": self.config.app_name, "version": self.config.app_version}
            elif name == "get_config":
                all_cfg = self.config.model_dump()
                keys = (arguments or {}).get("keys")
                if keys and isinstance(keys, list):
                    result = {k: all_cfg[k] for k in keys if k in all_cfg}
                else:
                    result = all_cfg
            elif name in ("update_config", "set_config"):
                args = dict(arguments or {})
                if "settings" in args and isinstance(args["settings"], dict):
                    nested = args.pop("settings")
                    args.update(nested)

                updated = {}
                model_fields = AppConfig.model_fields
                for k, v in args.items():
                    if k in model_fields:
                        setattr(self.config, k, v)
                        setattr(config, k, v)
                        if hasattr(self.mwl_service, "config"):
                            setattr(self.mwl_service.config, k, v)
                        if k == "scp_ae_title" and hasattr(self.scp_service, "ae_title"):
                            self.scp_service.ae_title = v
                        if k == "scp_port" and hasattr(self.scp_service, "port"):
                            self.scp_service.port = int(v)
                        if k == "log_level":
                            import logging

                            lvl = getattr(logging, str(v).upper(), None)
                            if lvl is not None:
                                logging.getLogger().setLevel(lvl)
                        updated[k] = v

                if not updated:
                    return {
                        "content": [{"type": "text", "text": "No valid configuration fields provided to update."}],
                        "isError": True,
                    }
                result = {
                    "success": True,
                    "updated": updated,
                    "message": f"Successfully updated {len(updated)} configuration setting(s).",
                    "current_config": self.config.model_dump(),
                }
            elif name == "generate_mock_dicom":
                request_model = MockDicomRequest.model_validate(arguments or {})
                target_dir = (arguments or {}).get("storage_dir") or self.config.storage_dir
                resp = self.generator_service.generate_and_save(request_model, target_dir=target_dir)
                result = resp.model_dump()
            elif name == "generate_raw_dicom_image":
                raw_req = RawImageGeneratorRequest.model_validate(arguments or {})
                target_dir = (arguments or {}).get("storage_dir") or self.config.storage_dir
                mock_req = MockDicomRequest(
                    patient={"patient_id": raw_req.patient_id, "patient_name": raw_req.patient_name},
                    study={"study_date": raw_req.study_date, "study_time": raw_req.study_time},
                    num_instances=1,
                    rows=raw_req.rows,
                    columns=raw_req.columns,
                    transfer_syntax=raw_req.transfer_syntax,
                    burn_in_text=True,
                    stress=raw_req.stress,
                    include_slice_overlay=raw_req.include_slice_overlay,
                )
                resp = self.generator_service.generate_and_save(mock_req, target_dir=target_dir)
                result = resp.model_dump()
            elif name == "get_scp_status":
                result = self.scp_service.get_status().model_dump()
            elif name == "start_scp":
                result = self.scp_service.start().model_dump()
            elif name == "stop_scp":
                result = self.scp_service.stop().model_dump()
            elif name == "get_mwl_status":
                result = self.mwl_service.get_status().model_dump()
            elif name in ("list_mwl_entries", "get_worklist", "show_worklist"):
                result = [entry for entry in self.mwl_service.list_entries()]
            elif name == "generate_scanning_order":
                order_req = ScanningOrderRequest.model_validate(arguments or {})
                custom_dict = order_req.model_dump(by_alias=True, exclude_none=True)
                # Map accession_number to accession for MWL generator
                if "accession_number" in custom_dict:
                    custom_dict["accession"] = custom_dict["accession_number"]
                record = self.mwl_service.add_entry(custom=custom_dict)
                if not record:
                    return {
                        "content": [{"type": "text", "text": "Failed to generate scanning order MWL entry."}],
                        "isError": True,
                    }
                result = {
                    "success": True,
                    "patient_name": record["patient_name"],
                    "patient_id": record["patient_id"],
                    "accession_number": record["accession"],
                    "modality": record["modality"],
                    "study_description": record.get("study_description"),
                    "study_uid": record["study_uid"],
                    "scheduled_procedure_step_id": str(record.get("series_number", 1)),
                    "json_entry": record["json_entry"],
                }
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
                    "study_description": record.get("study_description"),
                    "json_entry": record["json_entry"],
                }
            elif name in ("remove_accession_number", "remove_mwl_entry", "cancel_order"):
                req = RemoveAccessionRequest.model_validate(arguments or {})
                acc = req.accession_number
                removed_count = self.mwl_service.remove_entry(accession=acc)
                result = {
                    "success": removed_count > 0,
                    "accession_number": acc,
                    "removed_count": removed_count,
                    "message": (
                        f"Successfully removed {removed_count} worklist entry/entries with accession '{acc}'."
                        if removed_count > 0
                        else f"No active worklist entry found with accession '{acc}'."
                    ),
                }
            elif name == "start_mwl_auto_generation":
                result = self.mwl_service.start_auto_generation().model_dump()
            elif name == "stop_mwl_auto_generation":
                result = self.mwl_service.stop_auto_generation().model_dump()
            elif name == "move_study":
                patient_id = (arguments or {}).get("patient_id") or (arguments or {}).get("patientId")
                accession = (
                    (arguments or {}).get("accession")
                    or (arguments or {}).get("accession_number")
                    or (arguments or {}).get("accessionNumber")
                )
                study_uid = (
                    (arguments or {}).get("study_uid")
                    or (arguments or {}).get("studyUid")
                    or (arguments or {}).get("study_instance_uid")
                    or (arguments or {}).get("studyInstanceUid")
                )
                target_ae_title = (
                    (arguments or {}).get("target_ae_title") or (arguments or {}).get("targetAeTitle") or "VIEWER_SCP"
                )
                target_host = (arguments or {}).get("target_host") or (arguments or {}).get("targetHost") or "127.0.0.1"
                target_port = int((arguments or {}).get("target_port") or (arguments or {}).get("targetPort") or 11113)

                result = self.scp_service.push_study_to_destination(
                    target_ae_title=target_ae_title,
                    target_host=target_host,
                    target_port=target_port,
                    patient_id=patient_id,
                    accession=accession,
                    study_uid=study_uid,
                )
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
