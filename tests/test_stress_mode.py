"""Tests for DICOM mock server Stress Mode (GOSMART_MS_STRESS)."""

import os
import tempfile
import time
from unittest.mock import patch

import numpy as np
import pydicom
from fastapi.testclient import TestClient
from pydicom.uid import JPEG2000Lossless, JPEGBaseline8Bit

from dicom_py_mock_server.api.dicomweb_routes import dicomweb_service
from dicom_py_mock_server.api.routes import mwl_service
from dicom_py_mock_server.config import AppConfig, config
from dicom_py_mock_server.main import app
from dicom_py_mock_server.models.dicom import (
    MockDicomRequest,
    PatientModel,
    RawImageGeneratorRequest,
    SeriesModel,
    StudyModel,
)
from dicom_py_mock_server.services.generator import DicomGeneratorService


def test_stress_config_parsing():
    """Verify GOSMART_MS_STRESS environment variable parsing and defaults."""
    cfg_default = AppConfig(_env_file=None)
    assert cfg_default.stress is False

    with patch.dict(os.environ, {"GOSMART_MS_STRESS": "true"}):
        cfg_true = AppConfig(_env_file=None)
        assert cfg_true.stress is True

    with patch.dict(os.environ, {"GOSMART_MS_STRESS": "false"}):
        cfg_false = AppConfig(_env_file=None)
        assert cfg_false.stress is False


def test_burn_metadata_text_slice_overlay_omission():
    """Verify that in stress mode demographics text is burned in but slice number overlay is omitted."""
    # 1. With slice overlay included (normal mode)
    arr_normal_slice1 = DicomGeneratorService.burn_metadata_text(
        rows=512,
        cols=512,
        patient_name="Doe^John",
        patient_id="ID-123",
        study_date="20260902",
        study_time="120000",
        image_number=1,
        include_slice_overlay=True,
    )
    arr_normal_slice2 = DicomGeneratorService.burn_metadata_text(
        rows=512,
        cols=512,
        patient_name="Doe^John",
        patient_id="ID-123",
        study_date="20260902",
        study_time="120000",
        image_number=2,
        include_slice_overlay=True,
    )
    # In normal mode, different image numbers produce different pixel values in the 4th line
    assert not np.array_equal(arr_normal_slice1, arr_normal_slice2)

    # 2. In stress mode (without slice overlay)
    arr_stress_slice1 = DicomGeneratorService.burn_metadata_text(
        rows=512,
        cols=512,
        patient_name="Doe^John",
        patient_id="ID-123",
        study_date="20260902",
        study_time="120000",
        image_number=1,
        include_slice_overlay=False,
    )
    arr_stress_slice2 = DicomGeneratorService.burn_metadata_text(
        rows=512,
        cols=512,
        patient_name="Doe^John",
        patient_id="ID-123",
        study_date="20260902",
        study_time="120000",
        image_number=2,
        include_slice_overlay=False,
    )
    # Demographics are identical, so pixel matrices must be exactly equal
    assert np.array_equal(arr_stress_slice1, arr_stress_slice2)

    # Verify demographics text exists in stress image (top-left text area has high pixel values)
    top_region = arr_stress_slice1[16:80, 16:250]
    assert np.any(top_region >= 4000)


def test_create_dicom_file_stress_mode_flag():
    """Verify create_dicom_file respects stress mode and omits slice number overlay."""
    req = MockDicomRequest(
        patient=PatientModel(patient_id="PID-STRESS-1", patient_name="Stress^Patient"),
        study=StudyModel(study_date="20260902", study_time="120000"),
        series=SeriesModel(modality="CT"),
        num_instances=1,
        rows=512,
        columns=512,
        transfer_syntax="RAW",
    )

    ds_stress1 = DicomGeneratorService.create_dicom_file(req, instance_number=1, stress=True)
    ds_stress2 = DicomGeneratorService.create_dicom_file(req, instance_number=2, stress=True)

    # Both instances have identical pixel data when stress mode is active
    assert ds_stress1.PixelData == ds_stress2.PixelData
    assert ds_stress1.SOPInstanceUID != ds_stress2.SOPInstanceUID
    assert ds_stress1.InstanceNumber == 1
    assert ds_stress2.InstanceNumber == 2


def test_raw_generator_request_stress_mode():
    """Verify RawImageGeneratorRequest correctly handles stress mode."""
    raw_req1 = RawImageGeneratorRequest(
        patient_name="Raw^Stress",
        patient_id="ID-RAW-STRESS",
        study_date="20260902",
        study_time="120000",
        image_number=1,
        rows=512,
        columns=512,
        transfer_syntax="RAW",
        stress=True,
    )
    raw_req2 = RawImageGeneratorRequest(
        patient_name="Raw^Stress",
        patient_id="ID-RAW-STRESS",
        study_date="20260902",
        study_time="120000",
        image_number=2,
        rows=512,
        columns=512,
        transfer_syntax="RAW",
        stress=True,
    )
    ds1 = DicomGeneratorService.create_raw_dicom_file(raw_req1)
    ds2 = DicomGeneratorService.create_raw_dicom_file(raw_req2)
    assert ds1.PixelData == ds2.PixelData


def test_create_instances_from_mwl_stress_mode_reuses_compressed_frame():
    """Verify that in stress mode, create_instances_from_mwl computes the compressed frame once and reuses it."""
    mwl_record = {
        "patient_id": "PID-STRESS-MWL",
        "patient_name": "Mwl^Stress",
        "accession": "ACC-STRESS-001",
        "study_uid": "1.2.826.0.1.3680043.8.498.9999901",
        "series_uid": "1.2.826.0.1.3680043.8.498.9999902",
        "modality": "CT",
        "num_instances": 5,
        "transfer_syntax": "JPEG2000_LOSSLESS",
        "stress": True,
    }

    datasets = DicomGeneratorService.create_instances_from_mwl(mwl_record, num_instances=5, stress=True)
    assert len(datasets) == 5

    # Check that transfer syntax is JPEG 2000 Lossless
    for ds in datasets:
        assert ds.file_meta.TransferSyntaxUID == JPEG2000Lossless
        assert ds.PatientID == "PID-STRESS-MWL"
        assert ds.PatientName == "Mwl^Stress"

    # Verify unique UIDs and sequential instance numbers
    sop_uids = [ds.SOPInstanceUID for ds in datasets]
    assert len(set(sop_uids)) == 5
    assert [ds.InstanceNumber for ds in datasets] == [1, 2, 3, 4, 5]

    # Verify that PixelData bytes are 100% identical across all 5 instances (single frame reuse)
    first_pixel_data = datasets[0].PixelData
    for ds in datasets[1:]:
        assert ds.PixelData == first_pixel_data


def test_generate_and_save_stress_mode():
    """Verify generate_and_save writes valid files with reused compressed frame in stress mode."""
    req = MockDicomRequest(
        patient=PatientModel(patient_id="PID-BATCH-STRESS", patient_name="Batch^Stress"),
        study=StudyModel(study_description="Stress Batch Study"),
        series=SeriesModel(modality="CT"),
        num_instances=4,
        rows=512,
        columns=512,
        transfer_syntax="JPEG",
        stress=True,
    )

    generator = DicomGeneratorService()
    with tempfile.TemporaryDirectory() as tmp_dir:
        res = generator.generate_and_save(req, target_dir=tmp_dir, stress=True)
        assert res.success is True
        assert res.generated_instances == 4

        # Read back all files and verify pixel data reuse
        loaded = [pydicom.dcmread(p) for p in res.file_paths]
        assert len(loaded) == 4

        for ds in loaded:
            assert ds.file_meta.TransferSyntaxUID == JPEGBaseline8Bit
            assert ds.BitsAllocated == 8

        first_px = loaded[0].PixelData
        for ds in loaded[1:]:
            assert ds.PixelData == first_px
            assert ds.SOPInstanceUID != loaded[0].SOPInstanceUID


def test_wado_stress_mode_first_request_transfer_syntax_stickiness():
    """Verify that in WADO, the first image request's transfer syntax is sticky for the rest of the study."""
    client = TestClient(app)
    dicomweb_service.clear_stress_cache()

    # Enable stress mode on config
    with patch.object(config, "stress", True):
        # Create a mock MWL study
        entry = mwl_service.add_entry(
            custom={
                "patientId": "PID-WADO-STRESS",
                "patientName": "Wado^Stress",
                "accession": "ACC-WADO-STRESS",
                "studyDescription": "WADO Stress Protocol",
                "modality": "CT",
                "numInstances": 3,
            }
        )
        study_uid = entry["study_uid"]
        series_uid = entry["series_uid"]

        # 1. First image request: Retrieve study requesting JPEG Baseline (Process 1)
        resp1 = client.get(
            f"/dicomweb/studies/{study_uid}",
            headers={"Accept": 'multipart/related; type="application/dicom"; transfer-syntax="1.2.840.10008.1.2.4.50"'},
        )
        assert resp1.status_code == 200
        assert "1.2.840.10008.1.2.4.50" in resp1.headers["content-type"] or b"1.2.840.10008.1.2.4.50" in resp1.content

        # Verify the study's cached transfer syntax is JPEGBaseline8Bit
        assert dicomweb_service._study_transfer_syntaxes.get(study_uid) == "1.2.840.10008.1.2.4.50"

        # 2. Second request: Retrieve series without transfer-syntax header
        # In stress mode, it must stick to the first request's transfer syntax (JPEG)
        resp2 = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}")
        assert resp2.status_code == 200
        assert "1.2.840.10008.1.2.4.50" in resp2.headers["content-type"] or b"1.2.840.10008.1.2.4.50" in resp2.content

        # 3. Third request: Retrieve instance 1
        instances = client.get(f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances").json()
        sop_uid = instances[0]["00080018"]["Value"][0]

        resp3 = client.get(
            f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}",
            headers={"Accept": "application/dicom"},
        )
        assert resp3.status_code == 200
        dcm_inst = pydicom.dcmread(pydicom.filebase.DicomBytesIO(resp3.content))
        assert dcm_inst.file_meta.TransferSyntaxUID == JPEGBaseline8Bit

    dicomweb_service.clear_stress_cache()


def test_stress_mode_performance_speedup():
    """Verify that stress mode delivers drastic performance speedup by avoiding per-slice compression."""
    num_slices = 10
    mwl_record = {
        "patient_id": "PID-PERF-TEST",
        "patient_name": "Perf^Tester",
        "accession": "ACC-PERF-001",
        "study_uid": "1.2.826.0.1.3680043.8.498.1111111",
        "series_uid": "1.2.826.0.1.3680043.8.498.1111112",
        "modality": "CT",
        "num_instances": num_slices,
        "transfer_syntax": "JPEG2000_LOSSLESS",
    }

    # Time normal mode (compresses all 10 slices individually)
    t0 = time.perf_counter()
    ds_normal = DicomGeneratorService.create_instances_from_mwl(mwl_record, num_instances=num_slices, stress=False)
    t_normal = time.perf_counter() - t0
    assert len(ds_normal) == num_slices

    # Time stress mode (compresses only 1 slice, clones remainder)
    t0 = time.perf_counter()
    ds_stress = DicomGeneratorService.create_instances_from_mwl(mwl_record, num_instances=num_slices, stress=True)
    t_stress = time.perf_counter() - t0
    assert len(ds_stress) == num_slices

    # Stress mode should be significantly faster than normal mode for 10 slices
    assert t_stress < t_normal
    speedup = t_normal / max(t_stress, 0.001)
    assert speedup >= 2.0
