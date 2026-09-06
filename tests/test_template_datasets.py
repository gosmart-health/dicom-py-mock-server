"""Unit and integration tests for multi-slice template datasets, purity checks,
non-image filtering, and synthetic vs non-synthetic mode behaviors.
"""

from pathlib import Path

import numpy as np
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, MRImageStorage, generate_uid

from dicom_py_mock_server.config import AppConfig
from dicom_py_mock_server.services.generator import DicomGeneratorService
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService


def _create_mock_dicom_slice(
    path: Path,
    modality: str = "CT",
    sop_class_uid: str = CTImageStorage,
    series_uid: str = "1.2.3.4.5",
    series_number: int = 1,
    instance_number: int = 1,
    slice_location: float = 0.0,
    has_pixel_data: bool = True,
    rows: int = 64,
    cols: int = 64,
) -> FileDataset:
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = sop_class_uid
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.Modality = modality
    ds.SOPClassUID = sop_class_uid
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.InstanceNumber = instance_number
    ds.SliceLocation = slice_location
    ds.ImagePositionPatient = [0.0, 0.0, float(slice_location)]
    ds.Rows = rows
    ds.Columns = cols
    if has_pixel_data:
        arr = (np.ones((rows, cols), dtype=np.uint16) * instance_number * 100).astype(np.uint16)
        ds.PixelData = arr.tobytes()
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
    ds.save_as(path, enforce_file_format=True)
    return ds


def test_standalone_root_files_raise_value_error(tmp_path):
    """Verify that placing standalone DICOM or template files directly in templates/ raises ValueError."""
    (tmp_path / "standalone.dcm").write_bytes(b"\x00" * 200)

    cfg = AppConfig(templates_path=str(tmp_path))
    with pytest.raises(ValueError, match="Standalone files in root template directory"):
        MwlGeneratorService(app_config=cfg)


def test_mixed_modalities_in_folder_raise_value_error(tmp_path):
    """Verify that mixing different modalities in the same folder raises ValueError."""
    mixed_folder = tmp_path / "mixed_series"
    mixed_folder.mkdir()

    _create_mock_dicom_slice(mixed_folder / "slice_ct.dcm", modality="CT", sop_class_uid=CTImageStorage)
    _create_mock_dicom_slice(mixed_folder / "slice_mr.dcm", modality="MR", sop_class_uid=MRImageStorage)

    cfg = AppConfig(templates_path=str(tmp_path))
    with pytest.raises(ValueError, match="Mixed modalities detected in template folder 'mixed_series'"):
        MwlGeneratorService(app_config=cfg)


def test_non_image_exclusion(tmp_path):
    """Verify that PR, SR, and non-PixelData files are skipped during scanning."""
    ct_folder = tmp_path / "ct_series"
    ct_folder.mkdir()

    # Valid image slice
    _create_mock_dicom_slice(ct_folder / "slice_valid.dcm", modality="CT", sop_class_uid=CTImageStorage)

    # Missing PixelData
    _create_mock_dicom_slice(
        ct_folder / "slice_no_pixels.dcm",
        modality="CT",
        sop_class_uid=CTImageStorage,
        has_pixel_data=False,
    )

    # PR modality
    _create_mock_dicom_slice(
        ct_folder / "slice_pr.dcm",
        modality="PR",
        sop_class_uid="1.2.840.10008.5.1.4.1.1.11.1",
        has_pixel_data=False,
    )

    # SR modality
    _create_mock_dicom_slice(
        ct_folder / "slice_sr.dcm",
        modality="SR",
        sop_class_uid="1.2.840.10008.5.1.4.1.1.88.22",
        has_pixel_data=False,
    )

    cfg = AppConfig(templates_path=str(tmp_path))
    service = MwlGeneratorService(app_config=cfg)

    # Only 1 valid image slice should be loaded
    ct_datasets = service.get_template_datasets_by_modality("CT")
    assert len(ct_datasets) == 1
    assert ct_datasets[0].slice_count == 1


def test_multi_series_grouping_and_slice_sorting(tmp_path):
    """Verify multiple series in a folder are grouped separately and sorted by (InstanceNumber, SliceLocation, z)."""
    mr_folder = tmp_path / "mr_study"
    mr_folder.mkdir()

    # Create Series 1 with 3 slices out of order
    _create_mock_dicom_slice(
        mr_folder / "mr_s1_i3.dcm",
        modality="MR",
        sop_class_uid=MRImageStorage,
        series_uid="1.2.840.1.1",
        series_number=101,
        instance_number=3,
        slice_location=30.0,
    )
    _create_mock_dicom_slice(
        mr_folder / "mr_s1_i1.dcm",
        modality="MR",
        sop_class_uid=MRImageStorage,
        series_uid="1.2.840.1.1",
        series_number=101,
        instance_number=1,
        slice_location=10.0,
    )
    _create_mock_dicom_slice(
        mr_folder / "mr_s1_i2.dcm",
        modality="MR",
        sop_class_uid=MRImageStorage,
        series_uid="1.2.840.1.1",
        series_number=101,
        instance_number=2,
        slice_location=20.0,
    )

    # Create Series 2 with 2 slices
    _create_mock_dicom_slice(
        mr_folder / "mr_s2_i2.dcm",
        modality="MR",
        sop_class_uid=MRImageStorage,
        series_uid="1.2.840.1.2",
        series_number=201,
        instance_number=2,
        slice_location=20.0,
    )
    _create_mock_dicom_slice(
        mr_folder / "mr_s2_i1.dcm",
        modality="MR",
        sop_class_uid=MRImageStorage,
        series_uid="1.2.840.1.2",
        series_number=201,
        instance_number=1,
        slice_location=10.0,
    )

    cfg = AppConfig(templates_path=str(tmp_path))
    service = MwlGeneratorService(app_config=cfg)

    mr_datasets = service.get_template_datasets_by_modality("MR")
    assert len(mr_datasets) == 2

    # Verify series 101 slices are sorted 1, 2, 3
    s101 = next(ts for ts in mr_datasets if ts.series_number == 101)
    assert [int(s.InstanceNumber) for s in s101.slices] == [1, 2, 3]
    assert s101.slice_count == 3

    # Verify series 201 slices are sorted 1, 2
    s201 = next(ts for ts in mr_datasets if ts.series_number == 201)
    assert [int(s.InstanceNumber) for s in s201.slices] == [1, 2]
    assert s201.slice_count == 2


def test_non_synthetic_mode_sequential_mwl_and_exact_slice_delivery(tmp_path):
    """Verify non-synthetic mode sequentially assigns template datasets per modality and delivers exact slice count."""
    # Create two CT template series in separate folders
    ct1_dir = tmp_path / "ct_head"
    ct1_dir.mkdir()
    for i in range(1, 4):  # 3 slices
        _create_mock_dicom_slice(
            ct1_dir / f"s{i}.dcm",
            modality="CT",
            series_uid="1.2.1",
            series_number=1,
            instance_number=i,
            slice_location=float(i * 5),
        )

    ct2_dir = tmp_path / "ct_chest"
    ct2_dir.mkdir()
    for i in range(1, 6):  # 5 slices
        _create_mock_dicom_slice(
            ct2_dir / f"s{i}.dcm",
            modality="CT",
            series_uid="1.2.2",
            series_number=2,
            instance_number=i,
            slice_location=float(i * 5),
        )

    cfg = AppConfig(templates_path=str(tmp_path), synthetic_mode=False)
    service = MwlGeneratorService(app_config=cfg)

    # 1. First CT study should pick ct_chest (5 slices)
    e1 = service.add_entry(custom={"modality": "CT"})
    assert e1["num_instances"] == 5
    assert e1["template_series"].name == "ct_chest"
    assert e1["series_number"] == 2

    # 2. Second CT study should pick ct_head (3 slices)
    e2 = service.add_entry(custom={"modality": "CT"})
    assert e2["num_instances"] == 3
    assert e2["template_series"].name == "ct_head"
    assert e2["series_number"] == 1

    # 3. Third CT study should cycle back to ct_chest (5 slices)
    e3 = service.add_entry(custom={"modality": "CT"})
    assert e3["num_instances"] == 5
    assert e3["template_series"].name == "ct_chest"

    # Test delivery of exact slices
    datasets_e1 = DicomGeneratorService.create_instances_from_mwl(e1)
    assert len(datasets_e1) == 5
    assert [int(d.InstanceNumber) for d in datasets_e1] == [1, 2, 3, 4, 5]

    datasets_e2 = DicomGeneratorService.create_instances_from_mwl(e2)
    assert len(datasets_e2) == 3
    assert [int(d.InstanceNumber) for d in datasets_e2] == [1, 2, 3]


def test_synthetic_mode_cyclic_rotation_and_stress(tmp_path):
    """Verify synthetic mode cyclically rotates template slices and clones in stress mode."""
    ct_dir = tmp_path / "ct_template"
    ct_dir.mkdir()
    # 3 slices in template
    for i in range(1, 4):
        _create_mock_dicom_slice(
            ct_dir / f"s{i}.dcm",
            modality="CT",
            series_uid="1.2.1",
            series_number=1,
            instance_number=i,
            slice_location=float(i * 10),
        )

    cfg = AppConfig(templates_path=str(tmp_path), synthetic_mode=True, min_slices=8, max_slices=8)
    service = MwlGeneratorService(app_config=cfg)

    # 1. Synthetic mode with 7 requested instances (more than 3 template slices)
    entry = service.add_entry(custom={"modality": "CT", "num_instances": 7})
    assert entry["num_instances"] == 7

    datasets = DicomGeneratorService.create_instances_from_mwl(entry)
    assert len(datasets) == 7
    # Instances should be 1..7
    assert [int(d.InstanceNumber) for d in datasets] == list(range(1, 8))
    # Slice locations should rotate cyclically: 10.0, 20.0, 30.0, 10.0, 20.0, 30.0, 10.0
    locations = [float(d.SliceLocation) for d in datasets]
    assert locations == [10.0, 20.0, 30.0, 10.0, 20.0, 30.0, 10.0]

    # 2. Stress mode in synthetic mode
    entry_stress = service.add_entry(custom={"modality": "CT", "num_instances": 5})
    datasets_stress = DicomGeneratorService.create_instances_from_mwl(entry_stress, stress=True)
    assert len(datasets_stress) == 5
    # PixelData of instances 2..5 should match instance 1 (cloned frame 0)
    for d in datasets_stress[1:]:
        assert d.PixelData == datasets_stress[0].PixelData
        assert int(d.NumberOfSeriesRelatedInstances) == 5
