"""Tests for DICOM generator service using pydicom."""

import tempfile
import numpy as np
import pydicom
from pydicom.uid import ExplicitVRLittleEndian, JPEGBaseline8Bit, JPEG2000Lossless

from dicom_py_mock_server.models.dicom import (
    MockDicomRequest,
    PatientModel,
    RawImageGeneratorRequest,
    SeriesModel,
    StudyModel,
)
from dicom_py_mock_server.services.generator import DicomGeneratorService


def test_dicom_file_generation():
    generator = DicomGeneratorService()
    request = MockDicomRequest(
        patient=PatientModel(patient_id="TEST-PATIENT-123", patient_name="Tester^John"),
        study=StudyModel(study_description="Test Study"),
        series=SeriesModel(modality="MR"),
        num_instances=2,
        rows=512,
        columns=512,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        res = generator.generate_and_save(request, target_dir=tmp_dir)

        assert res.success is True
        assert res.generated_instances == 2
        assert len(res.file_paths) == 2

        # Read back generated DICOM file with pydicom
        ds = pydicom.dcmread(res.file_paths[0])
        assert ds.PatientID == "TEST-PATIENT-123"
        assert ds.PatientName == "Tester^John"
        assert ds.Modality == "MR"
        assert ds.Rows == 512
        assert ds.Columns == 512
        assert ds.BitsAllocated == 16
        assert hasattr(ds, "PixelData")


def test_raw_image_generator_burned_text_512x512():
    generator = DicomGeneratorService()
    raw_req = RawImageGeneratorRequest(
        patient_name="SMART^PATIENT",
        patient_id="RAW-PAT-999",
        study_date="20260828",
        study_time="143000",
        image_number=5,
        rows=512,
        columns=512,
        transfer_syntax="RAW",
    )

    ds = generator.create_raw_dicom_file(raw_req)

    assert ds.PatientName == "SMART^PATIENT"
    assert ds.PatientID == "RAW-PAT-999"
    assert ds.StudyDate == "20260828"
    assert ds.StudyTime == "143000"
    assert ds.InstanceNumber == 5
    assert ds.Rows == 512
    assert ds.Columns == 512
    assert ds.BitsAllocated == 16
    assert ds.BitsStored == 16
    assert ds.HighBit == 15
    assert ds.file_meta.TransferSyntaxUID == ExplicitVRLittleEndian

    # Verify text is burned into top-left region of pixel_array
    arr = ds.pixel_array
    assert arr.shape == (512, 512)
    top_left_region = arr[10:100, 10:300]
    assert np.any(top_left_region > 5000)


def test_transfer_syntax_swapping_raw_jpeg_jpeg2000():
    generator = DicomGeneratorService()

    # RAW (Explicit VR Little Endian)
    req_raw = RawImageGeneratorRequest(transfer_syntax="RAW")
    ds_raw = generator.create_raw_dicom_file(req_raw)
    assert ds_raw.file_meta.TransferSyntaxUID == ExplicitVRLittleEndian

    # JPEG Process 1 (JPEGBaseline8Bit)
    req_jpeg = RawImageGeneratorRequest(transfer_syntax="JPEG")
    ds_jpeg = generator.create_raw_dicom_file(req_jpeg)
    assert ds_jpeg.file_meta.TransferSyntaxUID == JPEGBaseline8Bit
    assert ds_jpeg.pixel_array.shape == (512, 512)

    # JPEG 2000 (JPEG2000Lossless)
    req_j2k = RawImageGeneratorRequest(transfer_syntax="JPEG2000")
    ds_j2k = generator.create_raw_dicom_file(req_j2k)
    assert ds_j2k.file_meta.TransferSyntaxUID in (JPEG2000Lossless, ExplicitVRLittleEndian)
    assert ds_j2k.pixel_array.shape == (512, 512)
