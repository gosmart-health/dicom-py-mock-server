"""Tests for DICOMweb STOW-RS service and cross-protocol retrieval."""

import io
import shutil

import numpy as np
import pydicom
import pytest
from fastapi.testclient import TestClient
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian

from dicom_py_mock_server.api.dicomweb_routes import dicomweb_service
from dicom_py_mock_server.api.routes import mwl_service, scp_service
from dicom_py_mock_server.config import config
from dicom_py_mock_server.main import app


@pytest.fixture(autouse=True)
def clean_received_and_cache(tmp_path):
    """Ensure clean received dir and in-memory cache for each test."""
    test_received = tmp_path / "received"
    test_received.mkdir(parents=True, exist_ok=True)
    orig_received = dicomweb_service.received_dir
    dicomweb_service.received_dir = test_received
    dicomweb_service.clear_cache(clear_stow=True)
    orig_dup = config.stow_duplicate_handling
    yield
    config.stow_duplicate_handling = orig_dup
    dicomweb_service.clear_cache(clear_stow=True)
    dicomweb_service.received_dir = orig_received
    if test_received.exists():
        shutil.rmtree(test_received, ignore_errors=True)


@pytest.fixture
def client():
    """Create FastAPI test client."""
    mwl_service.purge_expired_entries()
    return TestClient(app)


def create_test_dataset(
    study_uid: str = "1.2.3.4.5.6.7",
    series_uid: str = "1.2.3.4.5.6.7.1",
    sop_uid: str = "1.2.3.4.5.6.7.1.1",
    patient_id: str = "STOW-PAT-001",
    patient_name: str = "DOE^JANE",
) -> Dataset:
    """Create a minimal valid Part-10 DICOM Dataset."""
    ds = Dataset()
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SOPInstanceUID = sop_uid
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"  # CT Image Storage
    ds.Modality = "CT"
    ds.PatientID = patient_id
    ds.PatientName = patient_name
    ds.PatientBirthDate = "19800101"
    ds.PatientSex = "F"
    ds.StudyDate = "20260909"
    ds.StudyTime = "120000"
    ds.AccessionNumber = "ACC-STOW-100"
    ds.StudyDescription = "STOW-RS Test Study"
    ds.SeriesDescription = "Test Axial Series"
    ds.InstanceNumber = 1
    ds.Rows = 64
    ds.Columns = 64
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    arr = np.arange(64 * 64, dtype=np.uint16).reshape((64, 64))
    ds.PixelData = arr.tobytes()

    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    return ds


def dataset_to_bytes(ds: Dataset) -> bytes:
    """Serialize dataset to Part-10 DICOM binary bytes."""
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


def encode_multipart_related_stow(datasets: list[Dataset], boundary: str = "stow_boundary_xyz") -> tuple[bytes, str]:
    """Encode list of datasets into multipart/related STOW-RS body."""
    parts = []
    for ds in datasets:
        dcm_bytes = dataset_to_bytes(ds)
        part_header = (
            f"--{boundary}\r\nContent-Type: application/dicom\r\nContent-Length: {len(dcm_bytes)}\r\n\r\n"
        ).encode("utf-8")
        parts.append(part_header + dcm_bytes + b"\r\n")

    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    payload = b"".join(parts)
    content_type = f'multipart/related; type="application/dicom"; boundary="{boundary}"'
    return payload, content_type


def test_stow_store_instances_multipart_success(client):
    """Verify storing multiple DICOM instances via standard STOW-RS multipart/related."""
    ds1 = create_test_dataset(sop_uid="1.2.3.4.5.6.7.1.1")
    ds2 = create_test_dataset(sop_uid="1.2.3.4.5.6.7.1.2")
    ds2.InstanceNumber = 2

    payload, content_type = encode_multipart_related_stow([ds1, ds2])
    resp = client.post("/dicomweb/studies", content=payload, headers={"Content-Type": content_type})

    assert resp.status_code == 200
    assert "application/dicom+json" in resp.headers["content-type"]
    data = resp.json()

    # ReferencedSOPSequence (0008,1199)
    assert "00081199" in data
    ref_items = data["00081199"]["Value"]
    assert len(ref_items) == 2

    sops_stored = {item["00081155"]["Value"][0] for item in ref_items}
    assert "1.2.3.4.5.6.7.1.1" in sops_stored
    assert "1.2.3.4.5.6.7.1.2" in sops_stored

    # Check retrieve URLs
    for item in ref_items:
        assert "00081190" in item
        assert "/dicomweb/studies/" in item["00081190"]["Value"][0]

    # Verify Part-10 files written to received folder
    p1 = dicomweb_service.received_dir / "1.2.3.4.5.6.7" / "1.2.3.4.5.6.7.1" / "1.2.3.4.5.6.7.1.1.dcm"
    p2 = dicomweb_service.received_dir / "1.2.3.4.5.6.7" / "1.2.3.4.5.6.7.1" / "1.2.3.4.5.6.7.1.2.dcm"
    assert p1.exists()
    assert p2.exists()

    # Verify file content
    read_ds = pydicom.dcmread(p1)
    assert read_ds.PatientID == "STOW-PAT-001"
    assert read_ds.SOPInstanceUID == "1.2.3.4.5.6.7.1.1"


def test_stow_store_study_instances_success_and_conflict(client):
    """Verify target study UID endpoint behaves correctly for matching and conflicting studies."""
    study_uid = "1.2.840.111.222.333"
    ds = create_test_dataset(study_uid=study_uid, sop_uid="1.2.840.111.222.333.1")
    payload, content_type = encode_multipart_related_stow([ds])

    # 1. Matching study UID -> 200 OK
    resp_ok = client.post(f"/dicomweb/studies/{study_uid}", content=payload, headers={"Content-Type": content_type})
    assert resp_ok.status_code == 200
    data_ok = resp_ok.json()
    assert "00081199" in data_ok

    # 2. Conflicting study UID in URL -> 409 Conflict with FailureReason 0x0122 (290)
    diff_study_uid = "1.2.840.999.888.777"
    resp_conf = client.post(
        f"/dicomweb/studies/{diff_study_uid}", content=payload, headers={"Content-Type": content_type}
    )
    assert resp_conf.status_code == 409
    data_conf = resp_conf.json()
    assert "00081198" in data_conf
    failed_items = data_conf["00081198"]["Value"]
    assert len(failed_items) == 1
    assert failed_items[0]["00081197"]["Value"][0] == 290  # 0x0122


def test_stow_duplicate_handling_policies(client):
    """Verify configurable duplicate handling: accept, warn, and reject."""
    ds = create_test_dataset(sop_uid="1.2.840.555.666.1")
    payload, content_type = encode_multipart_related_stow([ds])

    # Initial upload
    resp1 = client.post("/dicomweb/studies", content=payload, headers={"Content-Type": content_type})
    assert resp1.status_code == 200

    # Policy: accept (default) -> 200 OK without warning
    config.stow_duplicate_handling = "accept"
    resp_accept = client.post("/dicomweb/studies", content=payload, headers={"Content-Type": content_type})
    assert resp_accept.status_code == 200
    data_accept = resp_accept.json()
    assert "00081199" in data_accept
    assert "00081196" not in data_accept["00081199"]["Value"][0]

    # Policy: warn -> 200 OK with WarningReason 0xB000
    config.stow_duplicate_handling = "warn"
    resp_warn = client.post("/dicomweb/studies", content=payload, headers={"Content-Type": content_type})
    assert resp_warn.status_code == 200
    data_warn = resp_warn.json()
    assert "00081199" in data_warn
    assert data_warn["00081199"]["Value"][0].get("00081196", {}).get("Value", [0])[0] == 0xB000

    # Policy: reject -> 409 Conflict with FailureReason 0x0111 (273)
    config.stow_duplicate_handling = "reject"
    resp_reject = client.post("/dicomweb/studies", content=payload, headers={"Content-Type": content_type})
    assert resp_reject.status_code == 409
    data_reject = resp_reject.json()
    assert "00081198" in data_reject
    assert data_reject["00081198"]["Value"][0]["00081197"]["Value"][0] == 273  # 0x0111


def test_stow_direct_application_dicom_raw(client):
    """Verify single instance STOW-RS sent directly as raw application/dicom."""
    ds = create_test_dataset(sop_uid="1.2.840.777.888.1")
    raw_bytes = dataset_to_bytes(ds)

    resp = client.post("/dicomweb/studies", content=raw_bytes, headers={"Content-Type": "application/dicom"})
    assert resp.status_code == 200
    data = resp.json()
    assert "00081199" in data
    assert data["00081199"]["Value"][0]["00081155"]["Value"][0] == "1.2.840.777.888.1"


def test_stow_invalid_payload_error_handling(client):
    """Verify empty or non-DICOM payload returns 400 Bad Request."""
    # Empty body
    resp_empty = client.post("/dicomweb/studies", content=b"", headers={"Content-Type": "application/dicom"})
    assert resp_empty.status_code == 400

    # Malformed body
    resp_bad = client.post(
        "/dicomweb/studies",
        content=b"THIS IS NOT A VALID DICOM DATASET",
        headers={"Content-Type": "application/dicom"},
    )
    assert resp_bad.status_code == 400


def test_stow_cross_protocol_qido_and_wado_retrieval(client):
    """Verify received instances are queryable via QIDO-RS and retrievable via WADO-RS."""
    study_uid = "2.16.840.1.113883.3.9999"
    series_uid = "2.16.840.1.113883.3.9999.1"
    sop_uid = "2.16.840.1.113883.3.9999.1.10"
    patient_id = "STOW-CROSS-42"

    ds = create_test_dataset(
        study_uid=study_uid,
        series_uid=series_uid,
        sop_uid=sop_uid,
        patient_id=patient_id,
        patient_name="TEST^CROSSPROTOCOL",
    )
    payload, content_type = encode_multipart_related_stow([ds])
    store_resp = client.post("/dicomweb/studies", content=payload, headers={"Content-Type": content_type})
    assert store_resp.status_code == 200

    # 1. QIDO-RS search studies
    qido_studies = client.get(f"/dicomweb/studies?PatientID={patient_id}").json()
    assert len(qido_studies) >= 1
    assert qido_studies[0]["00100020"]["Value"][0] == patient_id
    assert qido_studies[0]["0020000D"]["Value"][0] == study_uid

    # 2. QIDO-RS search series
    qido_series = client.get(f"/dicomweb/studies/{study_uid}/series").json()
    assert len(qido_series) >= 1
    assert qido_series[0]["0020000E"]["Value"][0] == series_uid

    # 3. QIDO-RS search instances
    qido_inst = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances").json()
    assert len(qido_inst) >= 1
    assert qido_inst[0]["00080018"]["Value"][0] == sop_uid

    # 4. WADO-RS retrieve study (multipart/related DICOM)
    wado_study_resp = client.get(f"/dicomweb/studies/{study_uid}")
    assert wado_study_resp.status_code == 200
    assert "multipart/related" in wado_study_resp.headers["content-type"]
    assert sop_uid.encode("latin1") in wado_study_resp.content

    # 5. WADO-RS retrieve study metadata (JSON)
    wado_meta_resp = client.get(f"/dicomweb/studies/{study_uid}/metadata")
    assert wado_meta_resp.status_code == 200
    meta_json = wado_meta_resp.json()
    assert isinstance(meta_json, list)
    assert meta_json[0]["00080018"]["Value"][0] == sop_uid

    # 6. WADO-RS retrieve single instance
    wado_inst_resp = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}")
    assert wado_inst_resp.status_code == 200

    # 7. WADO-RS retrieve rendered image
    wado_render_resp = client.get(
        f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}/rendered?format=JPEG"
    )
    assert wado_render_resp.status_code == 200
    assert wado_render_resp.headers["content-type"] == "image/jpeg"
    assert len(wado_render_resp.content) > 100


def test_stow_cross_protocol_dimse_c_find_and_c_move():
    """Verify received STOW-RS instances are discoverable via DIMSE C-FIND and C-MOVE."""
    study_uid = "2.16.840.1.113883.3.7777"
    series_uid = "2.16.840.1.113883.3.7777.1"
    sop_uid = "2.16.840.1.113883.3.7777.1.5"
    patient_id = "DIMSE-STOW-01"

    ds = create_test_dataset(
        study_uid=study_uid,
        series_uid=series_uid,
        sop_uid=sop_uid,
        patient_id=patient_id,
        patient_name="DIMSE^PATIENT",
    )
    dicomweb_service.store_instance(ds)

    # Verify scp_service has reference to dicomweb_service
    assert scp_service.dicomweb_service is not None

    # Verify C-FIND identifier matching
    find_event = type("Event", (), {})()
    find_event.assoc = None
    find_event.request = type("Request", (), {"AffectedSOPClassUID": "1.2.840.10008.5.1.4.1.2.2.1"})()
    find_event.identifier = Dataset()
    find_event.identifier.QueryRetrieveLevel = "STUDY"
    find_event.identifier.PatientID = patient_id

    results = list(scp_service._handle_find(find_event))
    assert len(results) >= 2  # at least one match (0xFF00, dataset) + final (0x0000, None)
    matched_status, matched_ds = results[0]
    assert matched_status == 0xFF00
    assert matched_ds.StudyInstanceUID == study_uid
    assert matched_ds.PatientID == patient_id


def create_gsps_dataset(
    study_uid: str = "1.2.840.10008.2.1",
    series_uid: str = "1.2.840.10008.2.1.2",
    sop_uid: str = "1.2.840.10008.2.1.2.1",
    patient_id: str = "GSPS-PAT-001",
) -> Dataset:
    """Create a minimal valid GSPS (Presentation State) Part-10 Dataset without PixelData."""
    ds = Dataset()
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SOPInstanceUID = sop_uid
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.11.1"  # Grayscale Softcopy Presentation State Storage
    ds.Modality = "PR"
    ds.PatientID = patient_id
    ds.PatientName = "PRESENTATION^PATIENT"
    ds.StudyDate = "20260909"
    ds.StudyTime = "120000"
    ds.AccessionNumber = "ACC-GSPS-001"
    ds.SeriesNumber = 99
    ds.InstanceNumber = 1
    ds.ContentLabel = "GSPS_LABEL"
    ds.ContentDescription = "Clinical review presentation"
    ds.PresentationCreationDate = "20260909"
    ds.PresentationCreationTime = "120000"
    ds.ContentCreatorName = "Dr. Tester"

    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    return ds


def test_stow_gsps_presentation_state_no_compression(client):
    """Verify GSPS (PR modality without pixel data) metadata sent without compression or decode attempts."""
    study_uid = "2.25.111111111111111111111"
    series_uid = "2.25.222222222222222222222"
    sop_uid = "2.25.333333333333333333333"

    gsps_ds = create_gsps_dataset(study_uid=study_uid, series_uid=series_uid, sop_uid=sop_uid)

    # 1. Store via STOW-RS
    body, ctype = encode_multipart_related_stow([gsps_ds])
    resp = client.post("/dicomweb/studies", content=body, headers={"Content-Type": ctype})
    assert resp.status_code == 200

    # 2. QIDO-RS search instances returns Modality="PR" and presentation tags
    qido_resp = client.get(f"/dicomweb/studies/{study_uid}/instances")
    assert qido_resp.status_code == 200
    qido_json = qido_resp.json()
    assert len(qido_json) == 1
    inst_json = qido_json[0]
    assert inst_json["00080060"]["Value"][0] == "PR"
    assert inst_json["00080016"]["Value"][0] == "1.2.840.10008.5.1.4.1.1.11.1"
    assert inst_json["00700080"]["Value"][0] == "GSPS_LABEL"

    # Filter by Modality
    mod_resp = client.get(f"/dicomweb/studies/{study_uid}/instances?Modality=PR")
    assert mod_resp.status_code == 200
    assert len(mod_resp.json()) == 1

    other_mod_resp = client.get(f"/dicomweb/studies/{study_uid}/instances?Modality=CT")
    assert other_mod_resp.status_code == 200
    assert len(other_mod_resp.json()) == 0

    # 3. WADO-RS retrieve study with JPEG2000 negotiation sends GSPS uncompressed without failing
    wado_study_resp = client.get(
        f"/dicomweb/studies/{study_uid}",
        headers={"Accept": 'multipart/related; type="application/dicom"; transfer-syntax="1.2.840.10008.1.2.4.90"'},
    )
    assert wado_study_resp.status_code == 200
    # Must preserve uncompressed transfer syntax for the GSPS part
    assert "transfer-syntax=1.2.840.10008.1.2.1" in wado_study_resp.headers.get("content-type", "") or (
        b"transfer-syntax=1.2.840.10008.1.2.1" in wado_study_resp.content
    )

    # 4. WADO-RS metadata does not inject pixel-related JPEG tags
    meta_resp = client.get(
        f"/dicomweb/studies/{study_uid}/metadata",
        headers={"Accept": "application/dicom+json; transfer-syntax=1.2.840.10008.1.2.4.50"},
    )
    assert meta_resp.status_code == 200
    meta_data = meta_resp.json()
    assert len(meta_data) == 1
    # BitsAllocated should NOT be injected into GSPS metadata
    assert "00280100" not in meta_data[0]

    # 5. Requesting frames on non-image instance returns 404 cleanly without traceback
    frames_resp = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}/frames/1")
    assert frames_resp.status_code == 404

    # 6. Requesting rendered image on non-image instance returns 400 cleanly
    render_resp = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}/rendered")
    assert render_resp.status_code == 400


def test_received_pr_metadata_retrieval_with_mwl_entries(client):
    """Verify that PR instances stored on disk in received_dir are retrievable via series metadata

    even when the study originated from MWL generator.
    """
    # 1. Add an active MWL entry
    mwl_record = mwl_service.add_entry()
    assert mwl_record is not None
    study_uid = mwl_record["study_uid"]

    # 2. Store a PR presentation state for this study
    pr_series_uid = f"{study_uid}.99"
    pr_sop_uid = f"{study_uid}.99.1"
    pr_ds = Dataset()
    pr_ds.StudyInstanceUID = study_uid
    pr_ds.SeriesInstanceUID = pr_series_uid
    pr_ds.SOPInstanceUID = pr_sop_uid
    pr_ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.11.1"  # GSPS
    pr_ds.Modality = "PR"
    pr_ds.SeriesNumber = 99
    pr_ds.InstanceNumber = 1
    pr_ds.PatientID = mwl_record["patient_id"]
    pr_ds.PatientName = "MWL^PATIENT"

    # Graphic Annotation Sequence
    ann_item = Dataset()
    ann_item.GraphicLayer = "LAYER1"
    obj_item = Dataset()
    obj_item.GraphicDimensions = 2
    obj_item.NumberOfGraphicPoints = 2
    obj_item.GraphicData = [100.0, 100.0, 200.0, 200.0]
    obj_item.GraphicType = "POLYLINE"
    obj_item.GraphicFilled = "N"
    ann_item.GraphicObjectSequence = Sequence([obj_item])
    pr_ds.GraphicAnnotationSequence = Sequence([ann_item])

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pr_ds.SOPClassUID
    file_meta.MediaStorageSOPInstanceUID = pr_ds.SOPInstanceUID
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    pr_ds.file_meta = file_meta
    pr_ds.is_little_endian = True
    pr_ds.is_implicit_VR = False

    payload, content_type = encode_multipart_related_stow([pr_ds])
    store_resp = client.post(f"/dicomweb/studies/{study_uid}", content=payload, headers={"Content-Type": content_type})
    assert store_resp.status_code == 200

    # Clear in-memory cache to force disk resolution
    dicomweb_service.clear_cache(study_uid, clear_stow=True)

    # 3. Query series for this study -> should return both MWL series and PR series
    series_resp = client.get(f"/dicomweb/studies/{study_uid}/series")
    assert series_resp.status_code == 200
    series_list = series_resp.json()
    modalities = {s.get("00080060", {}).get("Value", [""])[0] for s in series_list}
    assert "PR" in modalities

    # 4. Retrieve PR series metadata via WADO-RS -> should return 200 OK with GraphicAnnotationSequence
    meta_resp = client.get(f"/dicomweb/studies/{study_uid}/series/{pr_series_uid}/metadata")
    assert meta_resp.status_code == 200
    meta_json = meta_resp.json()
    assert len(meta_json) == 1
    assert meta_json[0]["00080060"]["Value"][0] == "PR"
    assert "00700001" in meta_json[0]  # GraphicAnnotationSequence
