"""FastAPI routes for DICOM Mock Server."""

from fastapi import APIRouter, HTTPException

from dicom_py_mock_server.config import config
from dicom_py_mock_server.models.dicom import (
    DicomMoveRequest,
    DicomMoveResponse,
    MockDicomRequest,
    MockDicomResponse,
    MwlEntrySummary,
    MwlGenerateRequest,
    MwlStatusResponse,
    RawImageGeneratorRequest,
    ScpStatusResponse,
)
from dicom_py_mock_server.services.generator import DicomGeneratorService
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService
from dicom_py_mock_server.services.scp import DicomScpService

router = APIRouter()
generator_service = DicomGeneratorService()
mwl_service = MwlGeneratorService(config)
scp_service = DicomScpService(ae_title=config.ae_title, port=config.scp_port, mwl_service=mwl_service)


@router.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "app": config.app_name, "version": config.app_version}


@router.post("/api/v1/generate", response_model=MockDicomResponse)
def generate_mock_dicom(request: MockDicomRequest):
    """Generate synthetic DICOM objects using pydicom from Pydantic request specs."""
    try:
        response = generator_service.generate_and_save(request, target_dir=config.storage_dir)
        return response
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate DICOM objects: {exc!s}") from exc


@router.post("/api/v1/generate/raw", response_model=MockDicomResponse)
def generate_raw_dicom_image(request: RawImageGeneratorRequest):
    """Generate a 16-bit 512x512 raw DICOM image with burned-in patient/study metadata strings."""
    try:
        mock_req = MockDicomRequest(
            patient={"patient_id": request.patient_id, "patient_name": request.patient_name},
            study={"study_date": request.study_date, "study_time": request.study_time},
            num_instances=1,
            rows=request.rows,
            columns=request.columns,
            transfer_syntax=request.transfer_syntax,
            burn_in_text=True,
        )
        response = generator_service.generate_and_save(mock_req, target_dir=config.storage_dir)
        return response
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate raw DICOM image: {exc!s}") from exc


@router.get("/api/v1/scp/status", response_model=ScpStatusResponse)
def get_scp_status():
    """Get DICOM SCP listener status."""
    return scp_service.get_status()


@router.post("/api/v1/scp/start", response_model=ScpStatusResponse)
def start_scp():
    """Start DICOM SCP listener using pynetdicom."""
    return scp_service.start()


@router.post("/api/v1/scp/stop", response_model=ScpStatusResponse)
def stop_scp():
    """Stop DICOM SCP listener."""
    return scp_service.stop()


@router.get("/api/v1/mwl/status", response_model=MwlStatusResponse)
def get_mwl_status():
    """Get Modality Worklist generator service status."""
    return mwl_service.get_status()


@router.get("/api/v1/mwl", response_model=list[MwlEntrySummary])
def list_mwl_entries():
    """List active Modality Worklist entries within window."""
    return mwl_service.list_entries()


@router.post("/api/v1/mwl/generate")
def generate_mwl_entry(request: MwlGenerateRequest | None = None):
    """Manually generate a new MWL entry and add it to the active list."""
    custom_dict = request.model_dump(by_alias=True, exclude_none=True) if request else None
    record = mwl_service.add_entry(custom=custom_dict)
    return {
        "success": True,
        "patient_id": record["patient_id"],
        "accession": record["accession"],
        "modality": record["modality"],
        "study_uid": record["study_uid"],
        "json_entry": record["json_entry"],
    }


@router.post("/api/v1/mwl/start", response_model=MwlStatusResponse)
def start_mwl_auto_generation():
    """Start background MWL entry creation loop."""
    return mwl_service.start_auto_generation()


@router.post("/api/v1/mwl/stop", response_model=MwlStatusResponse)
def stop_mwl_auto_generation():
    """Stop background MWL entry creation loop."""
    return mwl_service.stop_auto_generation()


@router.post("/api/v1/move", response_model=DicomMoveResponse)
@router.post("/api/v1/scp/move", response_model=DicomMoveResponse)
def move_study(request: DicomMoveRequest):
    """Move/push a DICOM study (by patient_id, accession, or study_instance_uid) to a target DICOM Storage SCP."""
    res = scp_service.push_study_to_destination(
        target_ae_title=request.target_ae_title,
        target_host=request.target_host,
        target_port=request.target_port,
        patient_id=request.patient_id,
        accession=request.accession_number,
        study_uid=request.study_instance_uid,
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res
