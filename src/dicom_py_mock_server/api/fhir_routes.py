"""FastAPI endpoints for ingesting FHIR ServiceRequest Bundles and updating MWL."""

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from dicom_py_mock_server.api.routes import mwl_service
from dicom_py_mock_server.services.fhir_parser import FhirParserService

router = APIRouter(tags=["FHIR"])

fhir_service = FhirParserService(mwl_service=mwl_service)


@router.post("/api/v1/fhir_service_request")
@router.post("/api/v1/fhir/Bundle")
@router.post("/api/v1/fhir/ServiceRequest")
def ingest_fhir_order(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Ingest a FHIR imaging order bundle or ServiceRequest and create MWL entries."""
    if not payload:
        raise HTTPException(status_code=400, detail="Empty FHIR payload")

    try:
        result = fhir_service.process_bundle(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to process FHIR payload: {exc!s}") from exc

    if result.get("rejections") and not result.get("entries_created") and not result.get("entries_removed"):
        # Rejection due to missing modality templates or validation
        raise HTTPException(status_code=422, detail=result["rejections"])

    return result
