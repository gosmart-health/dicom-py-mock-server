"""Tests for DICOM generator service using pydicom."""

import tempfile

import numpy as np
import pydicom
from pydicom.uid import (
    JPEG2000,
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
    JPEG2000Lossless,
    JPEGBaseline8Bit,
    RLELossless,
)

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


def test_ocr_burned_in_text():
    generator = DicomGeneratorService()
    req = RawImageGeneratorRequest(
        patient_name="OCR^TEST",
        patient_id="ID-OCR-999",
        study_date="20260828",
        study_time="143000",
        image_number=1,
        rows=512,
        columns=512,
        transfer_syntax="RAW",
    )
    ds = generator.create_raw_dicom_file(req)
    assert ds.Rows == 512
    assert ds.Columns == 512
    assert ds.BitsAllocated == 16
    assert ds.BitsStored == 12
    assert ds.PixelRepresentation == 0
    assert hasattr(ds, "PixelData")
    assert len(ds.PixelData) == 512 * 512 * 2

    # Verify OCR text area and gradient pattern
    arr = ds.pixel_array
    top_left_region = arr[10:100, 10:300]
    assert np.any(top_left_region >= 4000)
    # Verify bottom half has 4 gradient segments spanning 0 to 4095
    bottom_half = arr[256:512, :]
    assert bottom_half.min() == 0
    assert bottom_half.max() == 4095


def test_transfer_syntax_swapping_raw_jpeg_jpeg2000():
    generator = DicomGeneratorService()

    # 1. RAW (Explicit VR Little Endian)
    req_raw = RawImageGeneratorRequest(transfer_syntax="RAW")
    ds_raw = generator.create_raw_dicom_file(req_raw)
    assert ds_raw.file_meta.TransferSyntaxUID == ExplicitVRLittleEndian
    assert ds_raw.pixel_array.shape == (512, 512)
    assert ds_raw.pixel_array.dtype == np.uint16
    assert ds_raw.pixel_array.max() == 4095
    assert ds_raw.SmallestImagePixelValue == 0
    assert ds_raw.LargestImagePixelValue == 4095
    assert ds_raw.original_encoding == (False, True)

    # 2. JPEG Process 1 (JPEGBaseline8Bit)
    req_jpeg = RawImageGeneratorRequest(transfer_syntax="JPEG")
    ds_jpeg = generator.create_raw_dicom_file(req_jpeg)
    assert ds_jpeg.file_meta.TransferSyntaxUID == JPEGBaseline8Bit
    assert ds_jpeg.PhotometricInterpretation == "MONOCHROME2"
    assert ds_jpeg.SamplesPerPixel == 1
    assert ds_jpeg.PixelRepresentation == 0
    assert ds_jpeg.pixel_array.shape == (512, 512)
    assert ds_jpeg.pixel_array.dtype == np.uint8
    assert ds_jpeg.pixel_array.max() == 255
    assert ds_jpeg.BitsAllocated == 8
    assert ds_jpeg.BitsStored == 8
    assert ds_jpeg.HighBit == 7
    assert ds_jpeg.SmallestImagePixelValue == 0
    assert ds_jpeg.LargestImagePixelValue == 255
    assert ds_jpeg.LossyImageCompression == "01"
    assert ds_jpeg.original_encoding == (False, True)

    # 3. JPEG 2000 Lossless (JPEG2000Lossless)
    req_j2k = RawImageGeneratorRequest(transfer_syntax="JPEG2000")
    ds_j2k = generator.create_raw_dicom_file(req_j2k)
    assert ds_j2k.file_meta.TransferSyntaxUID == JPEG2000Lossless
    assert ds_j2k.pixel_array.shape == (512, 512)
    assert ds_j2k.pixel_array.dtype == np.uint16
    assert ds_j2k.pixel_array.max() == 4095
    assert ds_j2k.LossyImageCompression == "00"
    assert ds_j2k.original_encoding == (False, True)
    # Ensure SOP Instance UID was preserved
    assert ds_j2k.file_meta.MediaStorageSOPInstanceUID == ds_j2k.SOPInstanceUID

    # 4. JPEG 2000 Lossy (JPEG2000)
    req_j2k_lossy = RawImageGeneratorRequest(transfer_syntax="JPEG2000_LOSSY")
    ds_j2k_lossy = generator.create_raw_dicom_file(req_j2k_lossy)
    assert ds_j2k_lossy.file_meta.TransferSyntaxUID == JPEG2000
    assert ds_j2k_lossy.pixel_array.shape == (512, 512)
    assert ds_j2k_lossy.pixel_array.dtype == np.uint16
    assert ds_j2k_lossy.pixel_array.max() == 4095
    assert ds_j2k_lossy.LossyImageCompression == "01"
    assert ds_j2k_lossy.original_encoding == (False, True)

    # 5. RLE Lossless (RLELossless)
    req_rle = RawImageGeneratorRequest(transfer_syntax="RLE")
    ds_rle = generator.create_raw_dicom_file(req_rle)
    assert ds_rle.file_meta.TransferSyntaxUID == RLELossless
    assert ds_rle.pixel_array.shape == (512, 512)
    assert ds_rle.pixel_array.dtype == np.uint16
    assert ds_rle.pixel_array.max() == 4095
    assert ds_rle.LossyImageCompression == "00"
    assert ds_rle.original_encoding == (False, True)
    assert ds_rle.file_meta.MediaStorageSOPInstanceUID == ds_rle.SOPInstanceUID


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


def test_template_jpeg2000_lossless_generation():
    """Generate JPEG2000 Lossless DICOM Part-10 file based on templates/CT_small.dcm.

    Swaps pixels with burned metadata text on precomputed background and saves
    to test_output/jpeg_2000_lossless.dcm without deletion for PACS viewer verification.
    """
    from pathlib import Path

    out_dir = Path("test_output")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "jpeg_2000_lossless.dcm"

    ds = DicomGeneratorService.create_dicom_from_template(
        template="templates/CT_small.dcm",
        transfer_syntax="JPEG2000_LOSSLESS",
        patient_name="JPEG2000^TEST",
        patient_id="J2K-PAT-001",
        burn_in_text=True,
    )

    ds.save_as(out_file, enforce_file_format=True)

    assert out_file.exists()
    assert out_file.stat().st_size > 0

    read_back = pydicom.dcmread(out_file)
    assert read_back.file_meta.TransferSyntaxUID == JPEG2000Lossless
    assert read_back.PatientName == "JPEG2000^TEST"
    assert read_back.PatientID == "J2K-PAT-001"
    assert read_back.Rows == 512
    assert read_back.Columns == 512
    assert read_back.pixel_array.shape == (512, 512)
    assert read_back.pixel_array.dtype == np.uint16
    assert read_back.pixel_array.max() == 4095


def test_template_all_supported_compressions_generation():
    """Generate Part-10 files for all supported transfer syntaxes based on templates/CT_small.dcm.

    Saves files to test_output/ directory without deleting them post-run.
    """
    from pathlib import Path

    out_dir = Path("test_output")
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = [
        ("jpeg_2000_lossless.dcm", "JPEG2000_LOSSLESS", JPEG2000Lossless, np.uint16),
        ("jpeg_2000_lossy.dcm", "JPEG2000_LOSSY", JPEG2000, np.uint16),
        ("jpeg_baseline.dcm", "JPEG", JPEGBaseline8Bit, np.uint8),
        ("rle_lossless.dcm", "RLE", RLELossless, np.uint16),
        ("explicit_vr_little_endian.dcm", "EXPLICIT_VR_LITTLE_ENDIAN", ExplicitVRLittleEndian, np.uint16),
        ("implicit_vr_little_endian.dcm", "IMPLICIT_VR_LITTLE_ENDIAN", ImplicitVRLittleEndian, np.uint16),
    ]

    for filename, syntax_key, expected_uid, expected_dtype in cases:
        out_file = out_dir / filename

        ds = DicomGeneratorService.create_dicom_from_template(
            template="templates/CT_small.dcm",
            transfer_syntax=syntax_key,
            patient_name=f"SYNTAX^{syntax_key}",
            patient_id=f"ID-{syntax_key}",
            burn_in_text=True,
        )

        ds.save_as(out_file, enforce_file_format=True)

        assert out_file.exists()
        assert out_file.stat().st_size > 0

        read_back = pydicom.dcmread(out_file)
        assert read_back.file_meta.TransferSyntaxUID == expected_uid
        assert read_back.Rows == 512
        assert read_back.Columns == 512
        assert read_back.pixel_array.shape == (512, 512)
        assert read_back.pixel_array.dtype == expected_dtype
