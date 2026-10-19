"""FastAPI endpoints for ingesting FHIR ServiceRequest Bundles, Synthea FHIR R4 Bundles, and updating MWL."""

import json
import urllib.parse
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

from dicom_py_mock_server.api.routes import generator_service, mwl_service
from dicom_py_mock_server.config import config
from dicom_py_mock_server.services.fhir_parser import FhirParserService
from dicom_py_mock_server.services.synthea_utils import SyntheaUtils

router = APIRouter(tags=["FHIR"])

fhir_service = FhirParserService(mwl_service=mwl_service)
synthea_utils = SyntheaUtils(synthea_output_folder="", mwl_service=mwl_service)


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


@router.post("/api/v1/synthea/load", response_model=list[dict[str, Any]])
def load_synthea_bundles(payload: list[dict[str, Any]] | dict[str, Any] = Body(...)) -> list[dict[str, Any]]:
    """Load Synthea FHIR R4 bundles from raw JSON arrays, update MWL, and generate DICOM files."""
    if not payload:
        raise HTTPException(status_code=400, detail="A non-empty list of FHIR Bundles is required.")

    bundles_input = [payload] if isinstance(payload, dict) else payload
    if not isinstance(bundles_input, list) or len(bundles_input) == 0:
        raise HTTPException(status_code=400, detail="A non-empty list of FHIR Bundles is required.")

    try:
        results = synthea_utils.load_and_generate_from_raw_bundles(
            bundles=bundles_input,
            mwl_service=mwl_service,
            generator_service=generator_service,
            target_dir=config.storage_dir,
        )
        return [json.loads(b.model_dump_json(exclude_none=True)) for b in results]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load Synthea bundles: {exc!s}") from exc


@router.get("/api/v1/synthea/practitioner")
@router.get("/api/v1/synthea/practitioners", include_in_schema=False)
def get_synthea_practitioners(
    reference: str = Query(default="", description="Optional Practitioner reference, ID, or NPI filter"),
) -> list[dict[str, Any]]:
    """Retrieve memory-resident Synthea FHIR Practitioner resources."""
    practitioners = synthea_utils.get_practitioner_information(reference=reference)
    return [json.loads(p.model_dump_json(exclude_none=True)) for p in practitioners]


@router.get("/api/v1/synthea/hospitals")
@router.get("/api/v1/hospitals")
@router.get("/api/vi/hospitals", include_in_schema=False)
def get_synthea_hospitals(
    reference: str = Query(default="", description="Optional Organization reference or ID filter"),
) -> list[dict[str, Any]]:
    """Retrieve memory-resident Synthea FHIR Organization (hospital) resources."""
    hospitals = synthea_utils.get_hospital_information(reference=reference)
    return [json.loads(h.model_dump_json(exclude_none=True)) for h in hospitals]


@router.get("/api/v1/synthea/patient-bundle")
@router.get("/api/v1/syntha/patient-bundle", include_in_schema=False)
def get_synthea_patient_bundle(
    request: Request,
    patient_id: str | None = Query(default=None, alias="patient-id", description="Patient ID to look up"),
    patient_id_alt: str | None = Query(default=None, alias="patient_id", include_in_schema=False),
) -> dict[str, Any]:
    """Retrieve a memory-resident Synthea patient FHIR Bundle by patient-id."""
    resolved_id = patient_id or patient_id_alt
    if not resolved_id and request.url.query:
        raw_query = urllib.parse.unquote(request.url.query)
        for part in raw_query.split("&"):
            if part.startswith("patient-id:"):
                resolved_id = part.split("patient-id:", 1)[1].strip()
                break
            if part.startswith("patient_id:"):
                resolved_id = part.split("patient_id:", 1)[1].strip()
                break

    if not resolved_id:
        raise HTTPException(status_code=400, detail="Missing required query parameter 'patient-id'.")

    bundle = synthea_utils.get_patient_bundle_by_id(resolved_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"Patient bundle not found for patient-id '{resolved_id}'.")

    return json.loads(bundle.model_dump_json(exclude_none=True))


@router.get("/api/v1/synthea/patients")
def get_synthea_patients(
    patient_id: str | None = Query(default=None, alias="patient-id", description="Optional PatientID filter"),
    patient_id_alt: str | None = Query(default=None, alias="patient_id", include_in_schema=False),
    patient_name: str | None = Query(default=None, alias="patient-name", description="Optional PatientName filter"),
    patient_name_alt: str | None = Query(default=None, alias="patient_name", include_in_schema=False),
) -> list[dict[str, Any]]:
    """Retrieve memory-resident DICOM Patient models extracted from Synthea bundles."""
    patients = synthea_utils.get_patients(
        patient_id=patient_id or patient_id_alt,
        patient_name=patient_name or patient_name_alt,
    )
    return [json.loads(p.model_dump_json(exclude_none=True)) for p in patients]


@router.get("/api/v1/synthea/studies")
def get_synthea_studies(
    patient_id: str | None = Query(default=None, alias="patient-id", description="Optional PatientID filter"),
    patient_id_alt: str | None = Query(default=None, alias="patient_id", include_in_schema=False),
    study_uid: str | None = Query(default=None, alias="study-uid", description="Optional StudyInstanceUID filter"),
    study_uid_alt: str | None = Query(default=None, alias="study_uid", include_in_schema=False),
    accession: str | None = Query(default=None, description="Optional AccessionNumber filter"),
) -> list[dict[str, Any]]:
    """Retrieve memory-resident DICOM Study models extracted from Synthea bundles."""
    studies = synthea_utils.get_studies(
        patient_id=patient_id or patient_id_alt,
        study_uid=study_uid or study_uid_alt,
        accession=accession,
    )
    study_to_patient = {
        str(r.get("study_uid", "")): r.get("patient_id") for r in synthea_utils.patient_study_series_records
    }
    out: list[dict[str, Any]] = []
    for s in studies:
        d = json.loads(s.model_dump_json(exclude_none=True))
        if s.study_instance_uid and s.study_instance_uid in study_to_patient:
            d.setdefault("patient_id", study_to_patient[s.study_instance_uid])
        out.append(d)
    return out


@router.get("/api/v1/synthea/series")
def get_synthea_series(
    study_uid: str | None = Query(default=None, alias="study-uid", description="Optional StudyInstanceUID filter"),
    study_uid_alt: str | None = Query(default=None, alias="study_uid", include_in_schema=False),
    series_uid: str | None = Query(default=None, alias="series-uid", description="Optional SeriesInstanceUID filter"),
    series_uid_alt: str | None = Query(default=None, alias="series_uid", include_in_schema=False),
    modality: str | None = Query(default=None, description="Optional Modality filter"),
) -> list[dict[str, Any]]:
    """Retrieve memory-resident DICOM Series models extracted from Synthea bundles."""
    series_list = synthea_utils.get_series(
        study_uid=study_uid or study_uid_alt,
        series_uid=series_uid or series_uid_alt,
        modality=modality,
    )
    series_to_meta = {
        str(r.get("series_uid", "")): (r.get("study_uid"), r.get("patient_id"))
        for r in synthea_utils.patient_study_series_records
    }
    out: list[dict[str, Any]] = []
    for s in series_list:
        d = json.loads(s.model_dump_json(exclude_none=True))
        if s.series_instance_uid and s.series_instance_uid in series_to_meta:
            st_uid, pat_id = series_to_meta[s.series_instance_uid]
            if st_uid:
                d.setdefault("study_instance_uid", st_uid)
            if pat_id:
                d.setdefault("patient_id", pat_id)
        out.append(d)
    return out
