"""FastAPI endpoints for HL7 MLLP service lifecycle and simulation."""

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Response

from dicom_py_mock_server.api.routes import mwl_service
from dicom_py_mock_server.config import config
from dicom_py_mock_server.services.hl7_server import Hl7MllpServer

router = APIRouter(prefix="/api/v1/hl7", tags=["HL7"])

hl7_server = Hl7MllpServer(mwl_service=mwl_service, app_config=config)


@router.get("/status")
def get_hl7_status() -> dict[str, Any]:
    """Get HL7 MLLP listener status and statistics."""
    return hl7_server.get_status()


@router.post("/start")
async def start_hl7_server() -> dict[str, Any]:
    """Start HL7 MLLP listener."""
    try:
        return await hl7_server.start()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start HL7 listener: {exc!s}") from exc


@router.post("/stop")
async def stop_hl7_server() -> dict[str, Any]:
    """Stop HL7 MLLP listener."""
    try:
        return await hl7_server.stop()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to stop HL7 listener: {exc!s}") from exc


@router.post("/simulate")
def simulate_hl7_message(
    payload: str = Body(..., media_type="text/plain"),
) -> Response:
    """Simulate receiving an HL7 message via HTTP POST and return ACK in response body."""
    if not payload or not payload.strip():
        raise HTTPException(status_code=400, detail="Empty HL7 payload")

    summary, ack_str = hl7_server.process_raw_message(payload)
    status_code = 200 if summary.get("status") in ("created", "cancelled") else 422
    return Response(
        content=ack_str,
        status_code=status_code,
        media_type="text/plain",
        headers={
            "X-HL7-Status": summary.get("status", "unknown"),
            "X-HL7-Message-ID": summary.get("fields", {}).get("message_control_id", "UNKNOWN"),
        },
    )
