"""Tests for DICOM generator service using pydicom."""

import tempfile

import numpy as np
import pydicom
from pydicom.uid import ExplicitVRLittleEndian, JPEG2000Lossless, JPEGBaseline8Bit

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
    assert ds.BitsStored == 12
    assert ds.HighBit == 11
    assert ds.WindowCenter == 2048
    assert ds.WindowWidth == 4096
    assert ds.file_meta.TransferSyntaxUID == ExplicitVRLittleEndian

    # Verify text is burned into top-left region of pixel_array
    arr = ds.pixel_array
    assert arr.shape == (512, 512)
    top_left_region = arr[10:100, 10:300]
    assert np.any(top_left_region >= 4000)


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


def test_default_models_prefix_and_suffix():
    """Verify that default model instances use config id_prefix and patient_suffix."""
    patient = PatientModel()
    assert patient.patient_id.startswith("GSH-")
    assert patient.patient_name.split("^")[0].endswith("_GSH")

    study = StudyModel()
    assert study.accession_number.startswith("GSH-")

    raw_req = RawImageGeneratorRequest()
    assert raw_req.patient_id.startswith("GSH-")
    assert raw_req.patient_name.split("^")[0].endswith("_GSH")


def test_window_level_gradient_pattern_12bit():
    """Verify 12-bit dynamic range [0, 4095] with 4 gradient squares on bottom half."""
    generator = DicomGeneratorService()
    req = MockDicomRequest(
        patient=PatientModel(patient_id="WL-TEST-12BIT"),
        num_instances=1,
        rows=512,
        columns=512,
        transfer_syntax="RAW",
        burn_in_text=False,
    )
    ds = generator.create_dicom_file(req, instance_number=1)

    assert ds.BitsAllocated == 16
    assert ds.BitsStored == 12
    assert ds.HighBit == 11
    assert ds.WindowCenter == 2048
    assert ds.WindowWidth == 4096
    assert ds.RescaleIntercept == "0"
    assert ds.RescaleSlope == "1"

    arr = ds.pixel_array
    assert arr.shape == (512, 512)
    assert arr.dtype == np.uint16
    assert arr.min() >= 0
    assert arr.max() <= 4095

    # Bottom half (rows 256 to 512) divided into 4 squares of width 128
    bottom_half = arr[256:512, :]
    expected_segments = [
        (0, 128, 0, 1023),
        (128, 256, 1024, 2047),
        (256, 384, 2048, 3071),
        (384, 512, 3072, 4095),
    ]

    for c_start, c_end, v_expected_min, v_expected_max in expected_segments:
        square = bottom_half[:, c_start:c_end]
        # Verify vertical lines are column-constant
        for c_idx in range(square.shape[1]):
            col_vals = square[:, c_idx]
            assert np.all(col_vals == col_vals[0]), f"Column {c_start + c_idx} is not column-constant"

        # Verify gradient endpoints
        assert square[0, 0] == v_expected_min, (
            f"Square starting at col {c_start} expected {v_expected_min} but got {square[0, 0]}"
        )
        assert square[0, -1] == v_expected_max, (
            f"Square ending at col {c_end} expected {v_expected_max} but got {square[0, -1]}"
        )

        # Verify monotonicity from left to right
        row_vals = square[0, :]
        assert np.all(np.diff(row_vals) >= 0), f"Square {c_start}:{c_end} is not monotonic left-to-right"


def test_window_level_gradient_pattern_jpeg_8bit():
    """Verify 8-bit dynamic range [0, 255] for JPEG Process 1 with 4 gradient segments."""
    generator = DicomGeneratorService()
    req = MockDicomRequest(
        patient=PatientModel(patient_id="WL-TEST-8BIT"),
        num_instances=1,
        rows=512,
        columns=512,
        transfer_syntax="JPEG_PROCESS_1",
        burn_in_text=False,
    )
    ds = generator.create_dicom_file(req, instance_number=1)

    assert ds.BitsAllocated == 8
    assert ds.BitsStored == 8
    assert ds.HighBit == 7
    assert ds.WindowCenter == 128
    assert ds.WindowWidth == 256
    assert ds.file_meta.TransferSyntaxUID == JPEGBaseline8Bit

    # Precomputed background direct check for 8-bit
    bg_8bit = generator.create_precomputed_background(512, 512, is_8bit=True)
    assert bg_8bit.shape == (512, 512)
    assert bg_8bit.dtype == np.uint8

    bottom_half = bg_8bit[256:512, :]
    expected_segments_8bit = [
        (0, 128, 0, 63),
        (128, 256, 64, 127),
        (256, 384, 128, 191),
        (384, 512, 192, 255),
    ]

    for c_start, c_end, v_expected_min, v_expected_max in expected_segments_8bit:
        square = bottom_half[:, c_start:c_end]
        for c_idx in range(square.shape[1]):
            col_vals = square[:, c_idx]
            assert np.all(col_vals == col_vals[0])

        assert square[0, 0] == v_expected_min
        assert square[0, -1] == v_expected_max
        row_vals = square[0, :]
        assert np.all(np.diff(row_vals) >= 0)


def test_precomputed_background_caching():
    """Verify precomputed background array is cached and deterministic."""
    bg1 = DicomGeneratorService.create_precomputed_background(512, 512, is_8bit=False)
    bg2 = DicomGeneratorService.create_precomputed_background(512, 512, is_8bit=False)
    assert bg1 is bg2
