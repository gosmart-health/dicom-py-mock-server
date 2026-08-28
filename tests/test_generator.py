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


def test_template_sop_synthesis():
    """Test generating DICOM SOP instances using ./templates/CT_small.dcm as base template."""
    template_ds = pydicom.dcmread("templates/CT_small.dcm")
    assert template_ds.Modality == "CT"
    assert template_ds.Rows == 128
    assert template_ds.Columns == 128

    generator = DicomGeneratorService()
    request = MockDicomRequest(
        patient=PatientModel(patient_id="TEMPLATE-PAT-001", patient_name="Template^Synthesized"),
        study=StudyModel(study_description="Synthesized from CT_small template"),
        series=SeriesModel(modality=str(template_ds.Modality)),
        num_instances=2,
        rows=int(template_ds.Rows),
        columns=int(template_ds.Columns),
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        res = generator.generate_and_save(request, target_dir=tmp_dir)
        assert res.success is True
        assert res.generated_instances == 2
        assert len(res.file_paths) == 2

        ds = pydicom.dcmread(res.file_paths[0])
        assert ds.PatientID == "TEMPLATE-PAT-001"
        assert ds.PatientName == "Template^Synthesized"
        assert ds.Modality == "CT"
        assert ds.Rows == 128
        assert ds.Columns == 128


def test_template_sop_mwl():
    """Test instance synthesis matching MWL record created with CT_small.dcm template."""
    from dicom_py_mock_server.config import AppConfig
    from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService

    mwl_service = MwlGeneratorService(AppConfig(templates_path="./templates"))
    assert mwl_service.get_template_modalities() == ["CT"]

    record = mwl_service.add_entry()
    assert record["modality"] == "CT"

    datasets = DicomGeneratorService.create_instances_from_mwl(record, num_instances=3)
    assert len(datasets) == 3
    for i, ds in enumerate(datasets, 1):
        assert ds.Modality == "CT"
        assert ds.PatientID == record["patient_id"]
        assert ds.PatientName == record["patient_name"]
        assert ds.StudyInstanceUID == record["study_uid"]
        assert ds.InstanceNumber == i


def test_modality_study_descriptions_completeness_and_selection():
    """Verify each key modality has at least 12 unique, aligned study descriptions."""
    from dicom_py_mock_server.services.generator import (
        MODALITY_STUDY_DESCRIPTIONS,
        get_modality_study_descriptions,
        get_random_study_description,
    )

    key_modalities = ["CT", "MR", "DX", "CR", "US", "MG", "NM", "PT", "PET", "XA", "RF", "OT"]
    for modality in key_modalities:
        descriptions = get_modality_study_descriptions(modality)
        assert len(descriptions) >= 12, f"Modality {modality} should have at least 12 descriptions"
        assert len(set(descriptions)) == len(descriptions), f"Descriptions for {modality} should be unique"

        selected = get_random_study_description(modality)
        assert selected in descriptions


def test_generator_auto_modality_aligned_study_description():
    """Verify create_dicom_file generates modality-appropriate StudyDescription when omitted."""
    from dicom_py_mock_server.services.generator import MODALITY_STUDY_DESCRIPTIONS

    generator = DicomGeneratorService()
    for mod in ["CT", "MR", "US", "MG", "DX"]:
        req = MockDicomRequest(
            patient=PatientModel(patient_id=f"PAT-{mod}-1"),
            study=StudyModel(),
            series=SeriesModel(modality=mod),
            num_instances=1,
        )
        ds = generator.create_dicom_file(req, instance_number=1)
        assert ds.StudyDescription in MODALITY_STUDY_DESCRIPTIONS[mod]

