"""FastAPI routes for DICOMweb QIDO-RS, WADO-RS, and WADO-URI services."""

import io

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from dicom_py_mock_server.api.routes import generator_service, mwl_service
from dicom_py_mock_server.config import config
from dicom_py_mock_server.services.dicomweb import DicomWebService
from dicom_py_mock_server.services.generator import DicomGeneratorService

dicomweb_router = APIRouter()

dicomweb_service = DicomWebService(
    mwl_service=mwl_service,
    generator_service=generator_service,
    storage_dir=config.storage_dir,
)


def get_dicomweb_service() -> DicomWebService:
    """Dependency / accessor for DicomWebService."""
    return dicomweb_service


# ---------------------------------------------------------------------------
# QIDO-RS (Query / Search DICOM Objects)
# ---------------------------------------------------------------------------


@dicomweb_router.get("/studies", response_class=JSONResponse)
@dicomweb_router.get("/api/v1/dicomweb/studies", response_class=JSONResponse)
@dicomweb_router.get("/dicomweb/studies", response_class=JSONResponse)
def qido_search_studies(
    request: Request,
    patient_id: str | None = Query(None, alias="PatientID"),
    patient_name: str | None = Query(None, alias="PatientName"),
    accession: str | None = Query(None, alias="AccessionNumber"),
    study_uid: str | None = Query(None, alias="StudyInstanceUID"),
    study_date: str | None = Query(None, alias="StudyDate"),
    modality: str | None = Query(None, alias="ModalitiesInStudy"),
    study_desc: str | None = Query(None, alias="StudyDescription"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
):
    """QIDO-RS: Search for studies matching query parameters and return standard DICOM JSON."""
    params = dict(request.query_params)
    results = dicomweb_service.search_studies(params)
    return JSONResponse(content=results, media_type="application/dicom+json")


@dicomweb_router.get("/studies/{study_instance_uid}/series", response_class=JSONResponse)
@dicomweb_router.get("/api/v1/dicomweb/studies/{study_instance_uid}/series", response_class=JSONResponse)
@dicomweb_router.get("/dicomweb/studies/{study_instance_uid}/series", response_class=JSONResponse)
def qido_search_study_series(
    study_instance_uid: str,
    request: Request,
    modality: str | None = Query(None, alias="Modality"),
    series_uid: str | None = Query(None, alias="SeriesInstanceUID"),
    series_desc: str | None = Query(None, alias="SeriesDescription"),
    series_num: int | None = Query(None, alias="SeriesNumber"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
):
    """QIDO-RS: Search for series within a specified study and return standard DICOM JSON."""
    params = dict(request.query_params)
    results = dicomweb_service.search_series(study_instance_uid, params)
    return JSONResponse(content=results, media_type="application/dicom+json")


@dicomweb_router.get("/series", response_class=JSONResponse)
@dicomweb_router.get("/api/v1/dicomweb/series", response_class=JSONResponse)
@dicomweb_router.get("/dicomweb/series", response_class=JSONResponse)
def qido_search_series(
    request: Request,
    modality: str | None = Query(None, alias="Modality"),
    series_uid: str | None = Query(None, alias="SeriesInstanceUID"),
    series_desc: str | None = Query(None, alias="SeriesDescription"),
    series_num: int | None = Query(None, alias="SeriesNumber"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
):
    """QIDO-RS: Search for series across all studies and return standard DICOM JSON."""
    params = dict(request.query_params)
    results = dicomweb_service.search_series(None, params)
    return JSONResponse(content=results, media_type="application/dicom+json")


@dicomweb_router.get(
    "/studies/{study_instance_uid}/series/{series_instance_uid}/instances", response_class=JSONResponse
)
@dicomweb_router.get(
    "/api/v1/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/instances", response_class=JSONResponse
)
@dicomweb_router.get(
    "/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/instances", response_class=JSONResponse
)
def qido_search_series_instances(
    study_instance_uid: str,
    series_instance_uid: str,
    request: Request,
    sop_instance_uid: str | None = Query(None, alias="SOPInstanceUID"),
    sop_class_uid: str | None = Query(None, alias="SOPClassUID"),
    instance_number: int | None = Query(None, alias="InstanceNumber"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
):
    """QIDO-RS: Search for instances within a specified study and series."""
    params = dict(request.query_params)
    results = dicomweb_service.search_instances(study_instance_uid, series_instance_uid, params)
    return JSONResponse(content=results, media_type="application/dicom+json")


@dicomweb_router.get("/studies/{study_instance_uid}/instances", response_class=JSONResponse)
@dicomweb_router.get("/api/v1/dicomweb/studies/{study_instance_uid}/instances", response_class=JSONResponse)
@dicomweb_router.get("/dicomweb/studies/{study_instance_uid}/instances", response_class=JSONResponse)
def qido_search_study_instances(
    study_instance_uid: str,
    request: Request,
    sop_instance_uid: str | None = Query(None, alias="SOPInstanceUID"),
    sop_class_uid: str | None = Query(None, alias="SOPClassUID"),
    instance_number: int | None = Query(None, alias="InstanceNumber"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
):
    """QIDO-RS: Search for instances within a specified study across series."""
    params = dict(request.query_params)
    results = dicomweb_service.search_instances(study_instance_uid, None, params)
    return JSONResponse(content=results, media_type="application/dicom+json")


@dicomweb_router.get("/instances", response_class=JSONResponse)
@dicomweb_router.get("/api/v1/dicomweb/instances", response_class=JSONResponse)
@dicomweb_router.get("/dicomweb/instances", response_class=JSONResponse)
def qido_search_all_instances(
    request: Request,
    sop_instance_uid: str | None = Query(None, alias="SOPInstanceUID"),
    sop_class_uid: str | None = Query(None, alias="SOPClassUID"),
    instance_number: int | None = Query(None, alias="InstanceNumber"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
):
    """QIDO-RS: Search for instances across all studies and series."""
    params = dict(request.query_params)
    results = dicomweb_service.search_instances(None, None, params)
    return JSONResponse(content=results, media_type="application/dicom+json")


# ---------------------------------------------------------------------------
# WADO-RS: Metadata Retrieval
# ---------------------------------------------------------------------------


@dicomweb_router.get("/studies/{study_instance_uid}/metadata", response_class=JSONResponse)
@dicomweb_router.get("/api/v1/dicomweb/studies/{study_instance_uid}/metadata", response_class=JSONResponse)
@dicomweb_router.get("/dicomweb/studies/{study_instance_uid}/metadata", response_class=JSONResponse)
def wado_get_study_metadata(study_instance_uid: str):
    """WADO-RS: Retrieve metadata for all instances in a study as DICOM JSON."""
    datasets = dicomweb_service.get_study_datasets(study_instance_uid)
    if not datasets:
        raise HTTPException(status_code=404, detail="Study not found")
    metadata = dicomweb_service.get_metadata(datasets)
    return JSONResponse(content=metadata, media_type="application/dicom+json")


@dicomweb_router.get("/studies/{study_instance_uid}/series/{series_instance_uid}/metadata", response_class=JSONResponse)
@dicomweb_router.get(
    "/api/v1/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/metadata", response_class=JSONResponse
)
@dicomweb_router.get(
    "/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/metadata", response_class=JSONResponse
)
def wado_get_series_metadata(study_instance_uid: str, series_instance_uid: str):
    """WADO-RS: Retrieve metadata for all instances in a series as DICOM JSON."""
    datasets = dicomweb_service.get_series_datasets(study_instance_uid, series_instance_uid)
    if not datasets:
        raise HTTPException(status_code=404, detail="Series not found")
    metadata = dicomweb_service.get_metadata(datasets)
    return JSONResponse(content=metadata, media_type="application/dicom+json")


@dicomweb_router.get(
    "/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}/metadata",
    response_class=JSONResponse,
)
@dicomweb_router.get(
    "/api/v1/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}/metadata",
    response_class=JSONResponse,
)
@dicomweb_router.get(
    "/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}/metadata",
    response_class=JSONResponse,
)
def wado_get_instance_metadata(study_instance_uid: str, series_instance_uid: str, sop_instance_uid: str):
    """WADO-RS: Retrieve metadata for a single instance as DICOM JSON."""
    dataset = dicomweb_service.get_instance_dataset(study_instance_uid, series_instance_uid, sop_instance_uid)
    if not dataset:
        raise HTTPException(status_code=404, detail="Instance not found")
    metadata = dicomweb_service.get_metadata([dataset])
    return JSONResponse(content=metadata, media_type="application/dicom+json")


# ---------------------------------------------------------------------------
# WADO-RS: Object Retrieval with Transfer Syntax Negotiation
# ---------------------------------------------------------------------------


@dicomweb_router.get("/studies/{study_instance_uid}")
@dicomweb_router.get("/api/v1/dicomweb/studies/{study_instance_uid}")
@dicomweb_router.get("/dicomweb/studies/{study_instance_uid}")
def wado_retrieve_study(
    study_instance_uid: str,
    accept: str | None = Header(None),
    transfer_syntax_header: str | None = Header(None, alias="transfer-syntax"),
    x_transfer_syntax_header: str | None = Header(None, alias="X-Transfer-Syntax"),
    transfer_syntax: str | None = Query(None, alias="transferSyntax"),
    transfer_syntax_hyphen: str | None = Query(None, alias="transfer-syntax"),
    transfer_syntax_snake: str | None = Query(None, alias="transfer_syntax"),
):
    """WADO-RS: Retrieve all instances in a study as multipart/related; type=application/dicom."""
    datasets = dicomweb_service.get_study_datasets(study_instance_uid)
    if not datasets:
        raise HTTPException(status_code=404, detail="Study not found")

    req_ts = dicomweb_service.parse_transfer_syntax_header(
        accept_header=accept,
        query_param=transfer_syntax or transfer_syntax_hyphen or transfer_syntax_snake,
        direct_header=transfer_syntax_header or x_transfer_syntax_header,
    )
    payload, content_type = dicomweb_service.encode_multipart_related(datasets, requested_transfer_syntax=req_ts)
    return Response(content=payload, media_type=content_type)


@dicomweb_router.get("/studies/{study_instance_uid}/series/{series_instance_uid}")
@dicomweb_router.get("/api/v1/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}")
@dicomweb_router.get("/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}")
def wado_retrieve_series(
    study_instance_uid: str,
    series_instance_uid: str,
    accept: str | None = Header(None),
    transfer_syntax_header: str | None = Header(None, alias="transfer-syntax"),
    x_transfer_syntax_header: str | None = Header(None, alias="X-Transfer-Syntax"),
    transfer_syntax: str | None = Query(None, alias="transferSyntax"),
    transfer_syntax_hyphen: str | None = Query(None, alias="transfer-syntax"),
    transfer_syntax_snake: str | None = Query(None, alias="transfer_syntax"),
):
    """WADO-RS: Retrieve all instances in a series as multipart/related; type=application/dicom."""
    datasets = dicomweb_service.get_series_datasets(study_instance_uid, series_instance_uid)
    if not datasets:
        raise HTTPException(status_code=404, detail="Series not found")

    req_ts = dicomweb_service.parse_transfer_syntax_header(
        accept_header=accept,
        query_param=transfer_syntax or transfer_syntax_hyphen or transfer_syntax_snake,
        direct_header=transfer_syntax_header or x_transfer_syntax_header,
    )
    payload, content_type = dicomweb_service.encode_multipart_related(datasets, requested_transfer_syntax=req_ts)
    return Response(content=payload, media_type=content_type)


@dicomweb_router.get("/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}")
@dicomweb_router.get(
    "/api/v1/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}"
)
@dicomweb_router.get("/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}")
def wado_retrieve_instance(
    study_instance_uid: str,
    series_instance_uid: str,
    sop_instance_uid: str,
    accept: str | None = Header(None),
    transfer_syntax_header: str | None = Header(None, alias="transfer-syntax"),
    x_transfer_syntax_header: str | None = Header(None, alias="X-Transfer-Syntax"),
    transfer_syntax: str | None = Query(None, alias="transferSyntax"),
    transfer_syntax_hyphen: str | None = Query(None, alias="transfer-syntax"),
    transfer_syntax_snake: str | None = Query(None, alias="transfer_syntax"),
):
    """WADO-RS: Retrieve a single instance as multipart/related or application/dicom."""
    dataset = dicomweb_service.get_instance_dataset(study_instance_uid, series_instance_uid, sop_instance_uid)
    if not dataset:
        raise HTTPException(status_code=404, detail="Instance not found")

    req_ts = dicomweb_service.parse_transfer_syntax_header(
        accept_header=accept,
        query_param=transfer_syntax or transfer_syntax_hyphen or transfer_syntax_snake,
        direct_header=transfer_syntax_header or x_transfer_syntax_header,
    )

    # Check if client explicitly wants a direct non-multipart application/dicom response
    if accept and "multipart" not in accept.lower() and "application/dicom" in accept.lower():
        if req_ts:
            dataset = DicomGeneratorService.apply_transfer_syntax(dataset, req_ts)
        buf = io.BytesIO()
        dataset.save_as(buf, enforce_file_format=True)
        return Response(content=buf.getvalue(), media_type="application/dicom")

    payload, content_type = dicomweb_service.encode_multipart_related([dataset], requested_transfer_syntax=req_ts)
    return Response(content=payload, media_type=content_type)


# ---------------------------------------------------------------------------
# WADO-RS: Rendered Views & Pixel Frames
# ---------------------------------------------------------------------------


@dicomweb_router.get(
    "/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}/rendered",
)
@dicomweb_router.get(
    "/api/v1/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}/rendered",
)
@dicomweb_router.get(
    "/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}/rendered",
)
def wado_retrieve_rendered(
    study_instance_uid: str,
    series_instance_uid: str,
    sop_instance_uid: str,
    frame: int = Query(1, ge=1),
    format: str = Query("JPEG", alias="format"),
    quality: int = Query(85, ge=1, le=100),
):
    """WADO-RS: Render instance pixel data to JPEG or PNG image."""
    dataset = dicomweb_service.get_instance_dataset(study_instance_uid, series_instance_uid, sop_instance_uid)
    if not dataset:
        raise HTTPException(status_code=404, detail="Instance not found")

    img_bytes, media_type = dicomweb_service.render_instance(dataset, frame=frame, image_format=format, quality=quality)
    return Response(content=img_bytes, media_type=media_type)


@dicomweb_router.get(
    "/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}/frames/{frame_list}",
)
@dicomweb_router.get(
    "/api/v1/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}/frames/{frame_list}",
)
@dicomweb_router.get(
    "/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}/frames/{frame_list}",
)
def wado_retrieve_frames(
    study_instance_uid: str,
    series_instance_uid: str,
    sop_instance_uid: str,
    frame_list: str,
):
    """WADO-RS: Retrieve raw pixel frame bytes for specified frame numbers (e.g. '1' or '1,2,3')."""
    dataset = dicomweb_service.get_instance_dataset(study_instance_uid, series_instance_uid, sop_instance_uid)
    if not dataset:
        raise HTTPException(status_code=404, detail="Instance not found")

    try:
        frames = [int(f.strip()) for f in frame_list.split(",") if f.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid frame list '{frame_list}'")

    raw_frames = dicomweb_service.get_frame_bytes(dataset, frames)
    if not raw_frames:
        raise HTTPException(status_code=404, detail="Requested frames not found")

    boundary = "frame_boundary_12345"
    parts = []
    for f_data in raw_frames:
        parts.append(
            f"--{boundary}\r\nContent-Type: application/octet-stream\r\nContent-Length: {len(f_data)}\r\n\r\n".encode(
                "utf-8"
            )
            + f_data
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))

    return Response(
        content=b"".join(parts),
        media_type=f'multipart/related; type="application/octet-stream"; boundary="{boundary}"',
    )


@dicomweb_router.get(
    "/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}/frames/{frame_number}/rendered",
)
@dicomweb_router.get(
    "/api/v1/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}/frames/{frame_number}/rendered",
)
@dicomweb_router.get(
    "/dicomweb/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{sop_instance_uid}/frames/{frame_number}/rendered",
)
def wado_retrieve_frame_rendered(
    study_instance_uid: str,
    series_instance_uid: str,
    sop_instance_uid: str,
    frame_number: int,
    format: str = Query("JPEG", alias="format"),
    quality: int = Query(85, ge=1, le=100),
):
    """WADO-RS: Render specific frame pixel data to JPEG or PNG image."""
    dataset = dicomweb_service.get_instance_dataset(study_instance_uid, series_instance_uid, sop_instance_uid)
    if not dataset:
        raise HTTPException(status_code=404, detail="Instance not found")

    img_bytes, media_type = dicomweb_service.render_instance(
        dataset, frame=frame_number, image_format=format, quality=quality
    )
    return Response(content=img_bytes, media_type=media_type)


# ---------------------------------------------------------------------------
# WADO-URI (Legacy Web Retrieval)
# ---------------------------------------------------------------------------


@dicomweb_router.get("/wado")
@dicomweb_router.get("/api/v1/dicomweb/wado")
@dicomweb_router.get("/dicomweb/wado")
def wado_uri_retrieve(
    request_type: str = Query(..., alias="requestType"),
    study_uid: str = Query(..., alias="studyUID"),
    series_uid: str = Query(..., alias="seriesUID"),
    object_uid: str = Query(..., alias="objectUID"),
    content_type: str = Query("application/dicom", alias="contentType"),
    transfer_syntax: str | None = Query(None, alias="transferSyntax"),
    transfer_syntax_hyphen: str | None = Query(None, alias="transfer-syntax"),
    transfer_syntax_snake: str | None = Query(None, alias="transfer_syntax"),
):
    """WADO-URI: Legacy DICOM object retrieval endpoint."""
    if request_type.upper() != "WADO":
        raise HTTPException(status_code=400, detail="Invalid requestType, must be 'WADO'")

    dataset = dicomweb_service.get_instance_dataset(study_uid, series_uid, object_uid)
    if not dataset:
        raise HTTPException(status_code=404, detail="Requested DICOM object not found")

    if content_type.lower() in ("image/jpeg", "image/png"):
        fmt = "PNG" if "png" in content_type.lower() else "JPEG"
        img_bytes, media_type = dicomweb_service.render_instance(dataset, frame=1, image_format=fmt)
        return Response(content=img_bytes, media_type=media_type)

    target_ts = transfer_syntax or transfer_syntax_hyphen or transfer_syntax_snake
    if target_ts:
        dataset = DicomGeneratorService.apply_transfer_syntax(dataset, target_ts)

    buf = io.BytesIO()
    dataset.save_as(buf, enforce_file_format=True)
    return Response(content=buf.getvalue(), media_type="application/dicom")
