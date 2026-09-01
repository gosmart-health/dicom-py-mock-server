"""Tests for DICOMweb QIDO-RS, WADO-RS, and WADO-URI interfaces."""

import io
import re

import pydicom
import pytest
from fastapi.testclient import TestClient

from dicom_py_mock_server.api.routes import mwl_service
from dicom_py_mock_server.main import app


@pytest.fixture
def client():
    """Create a FastAPI test client and ensure mock studies exist in mwl_service."""
    mwl_service.purge_expired_entries()
    if len(mwl_service._entries) < 3:
        mwl_service.seed_initial_entries(count=5)
    return TestClient(app)


def test_qido_search_studies_all(client):
    """Verify QIDO-RS search studies returns DICOM JSON list of active studies."""
    response = client.get("/dicomweb/studies")
    assert response.status_code == 200
    assert "application/dicom+json" in response.headers["content-type"]

    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    # Check required DICOM Study-level attributes
    study_0 = data[0]
    assert "0020000D" in study_0  # StudyInstanceUID
    assert "00100020" in study_0  # PatientID
    assert "00100010" in study_0  # PatientName


def test_qido_search_studies_filtering(client):
    """Verify QIDO-RS search studies with PatientID and PatientName filters."""
    # Get all studies first
    all_studies = client.get("/dicomweb/studies").json()
    first_study = all_studies[0]
    patient_id = first_study["00100020"]["Value"][0]

    # Query with exact PatientID
    resp = client.get(f"/dicomweb/studies?PatientID={patient_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    for st in data:
        assert st["00100020"]["Value"][0] == patient_id

    # Query with wildcard
    resp_wildcard = client.get("/dicomweb/studies?PatientID=*")
    assert resp_wildcard.status_code == 200
    assert len(resp_wildcard.json()) >= 1


def test_qido_search_series(client):
    """Verify QIDO-RS search series within a study and across all studies."""
    studies = client.get("/dicomweb/studies").json()
    study_uid = studies[0]["0020000D"]["Value"][0]

    # Search series within study
    resp_series = client.get(f"/dicomweb/studies/{study_uid}/series")
    assert resp_series.status_code == 200
    series_list = resp_series.json()
    assert isinstance(series_list, list)
    assert len(series_list) >= 1

    series_0 = series_list[0]
    assert "0020000E" in series_0  # SeriesInstanceUID
    assert "00080060" in series_0  # Modality

    # Search all series
    resp_all_series = client.get("/dicomweb/series")
    assert resp_all_series.status_code == 200
    assert len(resp_all_series.json()) >= 1


def test_qido_search_instances(client):
    """Verify QIDO-RS search instances within study/series and across all instances."""
    studies = client.get("/dicomweb/studies").json()
    study_uid = studies[0]["0020000D"]["Value"][0]

    series_list = client.get(f"/dicomweb/studies/{study_uid}/series").json()
    series_uid = series_list[0]["0020000E"]["Value"][0]

    # Search instances in series
    resp_inst = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances")
    assert resp_inst.status_code == 200
    instances = resp_inst.json()
    assert isinstance(instances, list)
    assert len(instances) >= 1

    inst_0 = instances[0]
    assert "00080018" in inst_0  # SOPInstanceUID
    assert "00080016" in inst_0  # SOPClassUID
    assert "00200013" in inst_0  # InstanceNumber

    # Search all instances
    resp_all_inst = client.get("/dicomweb/instances")
    assert resp_all_inst.status_code == 200
    assert len(resp_all_inst.json()) >= 1


def test_wado_metadata_endpoints(client):
    """Verify WADO-RS metadata endpoints return DICOM JSON without PixelData."""
    studies = client.get("/dicomweb/studies").json()
    study_uid = studies[0]["0020000D"]["Value"][0]
    series_list = client.get(f"/dicomweb/studies/{study_uid}/series").json()
    series_uid = series_list[0]["0020000E"]["Value"][0]
    instances = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances").json()
    sop_uid = instances[0]["00080018"]["Value"][0]

    # 1. Study metadata
    meta_study = client.get(f"/dicomweb/studies/{study_uid}/metadata")
    assert meta_study.status_code == 200
    data_study = meta_study.json()
    assert isinstance(data_study, list)
    assert len(data_study) >= 1
    # Check that PixelData (7FE00010) is omitted from metadata
    assert "7FE00010" not in data_study[0]
    assert "0020000D" in data_study[0]

    # 2. Series metadata
    meta_series = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/metadata")
    assert meta_series.status_code == 200
    data_series = meta_series.json()
    assert isinstance(data_series, list)
    assert "7FE00010" not in data_series[0]

    # 3. Instance metadata
    meta_inst = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}/metadata")
    assert meta_inst.status_code == 200
    data_inst = meta_inst.json()
    assert isinstance(data_inst, list)
    assert data_inst[0]["00080018"]["Value"][0] == sop_uid
    assert "7FE00010" not in data_inst[0]


def _extract_multipart_dicom_parts(content_type: str, body: bytes) -> list[pydicom.Dataset]:
    """Helper to parse multipart/related body and read DICOM datasets."""
    boundary_match = re.search(r'boundary="?([^";,\s]+)"?', content_type)
    assert boundary_match, f"No boundary found in content-type {content_type}"
    boundary = boundary_match.group(1).encode("utf-8")

    delimiter = b"--" + boundary
    raw_parts = body.split(delimiter)
    datasets = []

    for p in raw_parts:
        p_stripped = p.strip()
        if not p_stripped or p_stripped == b"--":
            continue
        # Split header and body by double CRLF
        if b"\r\n\r\n" in p_stripped:
            _, part_body = p_stripped.split(b"\r\n\r\n", 1)
            # Remove trailing CRLF if present
            if part_body.endswith(b"\r\n"):
                part_body = part_body[:-2]
            ds = pydicom.dcmread(io.BytesIO(part_body), force=True)
            datasets.append(ds)
    return datasets


def test_wado_retrieve_study_and_series_multipart(client):
    """Verify WADO-RS retrieve study and series returns valid multipart DICOM files."""
    studies = client.get("/dicomweb/studies").json()
    study_uid = studies[0]["0020000D"]["Value"][0]
    series_list = client.get(f"/dicomweb/studies/{study_uid}/series").json()
    series_uid = series_list[0]["0020000E"]["Value"][0]

    # Retrieve Study
    resp_study = client.get(f"/dicomweb/studies/{study_uid}")
    assert resp_study.status_code == 200
    assert "multipart/related" in resp_study.headers["content-type"]
    study_dsets = _extract_multipart_dicom_parts(resp_study.headers["content-type"], resp_study.content)
    assert len(study_dsets) >= 1
    for ds in study_dsets:
        assert str(ds.StudyInstanceUID) == study_uid

    # Retrieve Series
    resp_series = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}")
    assert resp_series.status_code == 200
    series_dsets = _extract_multipart_dicom_parts(resp_series.headers["content-type"], resp_series.content)
    assert len(series_dsets) >= 1
    for ds in series_dsets:
        assert str(ds.SeriesInstanceUID) == series_uid


def test_wado_retrieve_transfer_syntax_negotiation(client):
    """Verify WADO-RS correctly transcodes datasets to requested transfer syntax across all supported syntaxes."""
    studies = client.get("/dicomweb/studies").json()
    study_uid = studies[0]["0020000D"]["Value"][0]

    transfer_syntaxes_to_test = [
        ("1.2.840.10008.1.2.1", "Explicit VR Little Endian"),
        ("1.2.840.10008.1.2.4.90", "JPEG 2000 Lossless"),
        ("1.2.840.10008.1.2.4.50", "JPEG Baseline 8-Bit"),
        ("1.2.840.10008.1.2.5", "RLE Lossless"),
    ]

    for ts_uid, ts_label in transfer_syntaxes_to_test:
        headers = {"Accept": f'multipart/related; type="application/dicom"; transfer-syntax="{ts_uid}"'}
        resp = client.get(f"/dicomweb/studies/{study_uid}", headers=headers)
        assert resp.status_code == 200, f"Failed for {ts_label} ({ts_uid})"
        dsets = _extract_multipart_dicom_parts(resp.headers["content-type"], resp.content)
        assert len(dsets) >= 1
        for ds in dsets:
            actual_ts = str(ds.file_meta.TransferSyntaxUID)
            assert actual_ts == ts_uid, f"Expected {ts_uid} ({ts_label}), got {actual_ts}"


def test_wado_single_instance_direct_application_dicom(client):
    """Verify single instance retrieval with Accept: application/dicom returns binary DICOM."""
    studies = client.get("/dicomweb/studies").json()
    study_uid = studies[0]["0020000D"]["Value"][0]
    series_list = client.get(f"/dicomweb/studies/{study_uid}/series").json()
    series_uid = series_list[0]["0020000E"]["Value"][0]
    instances = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances").json()
    sop_uid = instances[0]["00080018"]["Value"][0]

    headers = {"Accept": "application/dicom"}
    resp = client.get(
        f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/dicom"

    ds = pydicom.dcmread(io.BytesIO(resp.content), force=True)
    assert str(ds.SOPInstanceUID) == sop_uid
    assert str(ds.StudyInstanceUID) == study_uid


def test_wado_rendered_jpeg_and_png(client):
    """Verify WADO-RS rendered preview endpoints return valid JPEG and PNG images."""
    studies = client.get("/dicomweb/studies").json()
    study_uid = studies[0]["0020000D"]["Value"][0]
    series_list = client.get(f"/dicomweb/studies/{study_uid}/series").json()
    series_uid = series_list[0]["0020000E"]["Value"][0]
    instances = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances").json()
    sop_uid = instances[0]["00080018"]["Value"][0]

    # 1. Default JPEG
    resp_jpeg = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}/rendered")
    assert resp_jpeg.status_code == 200
    assert resp_jpeg.headers["content-type"] == "image/jpeg"
    assert resp_jpeg.content.startswith(b"\xff\xd8\xff")  # JPEG SOI magic bytes

    # 2. PNG
    resp_png = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}/rendered?format=PNG")
    assert resp_png.status_code == 200
    assert resp_png.headers["content-type"] == "image/png"
    assert resp_png.content.startswith(b"\x89PNG\r\n\x1a\n")  # PNG magic bytes


def test_wado_uri_endpoint(client):
    """Verify legacy WADO-URI endpoint retrieves DICOM and rendered previews."""
    studies = client.get("/dicomweb/studies").json()
    study_uid = studies[0]["0020000D"]["Value"][0]
    series_list = client.get(f"/dicomweb/studies/{study_uid}/series").json()
    series_uid = series_list[0]["0020000E"]["Value"][0]
    instances = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances").json()
    sop_uid = instances[0]["00080018"]["Value"][0]

    # 1. WADO-URI DICOM object
    resp_dcm = client.get(
        f"/dicomweb/wado?requestType=WADO&studyUID={study_uid}&seriesUID={series_uid}&objectUID={sop_uid}&contentType=application/dicom"
    )
    assert resp_dcm.status_code == 200
    ds = pydicom.dcmread(io.BytesIO(resp_dcm.content), force=True)
    assert str(ds.SOPInstanceUID) == sop_uid

    # 2. WADO-URI JPEG preview
    resp_img = client.get(
        f"/dicomweb/wado?requestType=WADO&studyUID={study_uid}&seriesUID={series_uid}&objectUID={sop_uid}&contentType=image/jpeg"
    )
    assert resp_img.status_code == 200
    assert resp_img.headers["content-type"] == "image/jpeg"
    assert resp_img.content.startswith(b"\xff\xd8\xff")


def test_wado_404_and_400_handling(client):
    """Verify proper 404 and 400 status codes for invalid queries."""
    # 404 for non-existent study metadata
    resp_404 = client.get("/dicomweb/studies/1.2.3.4.99999999999.0000/metadata")
    assert resp_404.status_code == 404

    # 400 for invalid WADO-URI requestType
    resp_400 = client.get("/dicomweb/wado?requestType=INVALID&studyUID=1&seriesUID=2&objectUID=3")
    assert resp_400.status_code == 400
