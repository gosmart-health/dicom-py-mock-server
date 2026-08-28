"""Unit tests for PersonGenerator and MwlGeneratorService."""

import json
from datetime import datetime, timedelta, date

from dicom_py_mock_server.config import AppConfig
from dicom_py_mock_server.services.person_generator import PersonGenerator
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService


def test_person_generator():
    gen = PersonGenerator()
    person = gen.generate()
    assert "^" in person.name
    assert len(person.mrn) == 8
    assert person.gender in ("M", "F")
    assert isinstance(person.dob, date)


def test_mwl_generator_default_templates(tmp_path):
    # Ensure empty templates directory triggers default fallback modalities
    cfg = AppConfig(templates_path=str(tmp_path))
    service = MwlGeneratorService(app_config=cfg)
    modalities = service.get_template_modalities()
    assert "CT" in modalities
    assert "MR" in modalities
    assert "US" in modalities
    assert "DX" in modalities


def test_mwl_generator_template_file_loading(tmp_path):
    # Create template JSON files
    (tmp_path / "CT.json").write_text(json.dumps({"modality": "CT", "desc": "CT Template"}), encoding="utf-8")
    (tmp_path / "PET.json").write_text(json.dumps({"modality": "PET", "desc": "PET Template"}), encoding="utf-8")

    cfg = AppConfig(templates_path=str(tmp_path))
    service = MwlGeneratorService(app_config=cfg)
    modalities = service.get_template_modalities()

    # When template files exist, ONLY loaded template modalities are present
    assert set(modalities) == {"CT", "PET"}
    assert "MR" not in modalities
    assert "US" not in modalities


def test_mwl_generator_dicom_template_scanning(tmp_path):
    import shutil
    from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

    # Use actual template file ./templates/CT_small.dcm
    shutil.copy("templates/CT_small.dcm", tmp_path / "CT_small.dcm")

    # Create second modality DICOM file (.dcm) for MR
    file_meta_mr = FileMetaDataset()
    file_meta_mr.MediaStorageSOPClassUID = MRImageStorage
    file_meta_mr.MediaStorageSOPInstanceUID = generate_uid()
    file_meta_mr.TransferSyntaxUID = ExplicitVRLittleEndian
    ds_mr = FileDataset(str(tmp_path / "sample_mr.dcm"), {}, file_meta=file_meta_mr, preamble=b"\x00" * 128)
    ds_mr.Modality = "MR"
    ds_mr.SOPClassUID = MRImageStorage
    ds_mr.SOPInstanceUID = file_meta_mr.MediaStorageSOPInstanceUID
    ds_mr.save_as(tmp_path / "sample_mr.dcm", enforce_file_format=True)

    cfg = AppConfig(templates_path=str(tmp_path))
    service = MwlGeneratorService(app_config=cfg)

    modalities = service.get_template_modalities()
    assert set(modalities) == {"CT", "MR"}

    # Check indexed DICOM templates by Modality key
    ct_templates = service.get_dicom_templates_by_modality("CT")
    mr_templates = service.get_dicom_templates_by_modality("MR")

    assert len(ct_templates) == 1
    assert ct_templates[0].Modality == "CT"
    assert ct_templates[0].Rows == 128
    assert ct_templates[0].Columns == 128
    assert getattr(ct_templates[0], "PatientName", "") == "CompressedSamples^CT1"
    assert len(mr_templates) == 1
    assert mr_templates[0].Modality == "MR"


def test_mwl_generator_no_modality_fallback_when_template_present(tmp_path):
    import shutil

    # Copy ONLY the CT_small.dcm template file
    shutil.copy("templates/CT_small.dcm", tmp_path / "CT_small.dcm")

    cfg = AppConfig(templates_path=str(tmp_path))
    service = MwlGeneratorService(app_config=cfg)

    modalities = service.get_template_modalities()
    assert modalities == ["CT"]

    # Generate multiple MWL entries and verify ALL of them have Modality "CT"
    for _ in range(10):
        entry = service.generate_json()
        assert entry["00080060"]["Value"][0] == "CT"


def test_mwl_generator_workspace_template_loading():
    """Verify MwlGeneratorService loads the real workspace ./templates/CT_small.dcm."""
    cfg = AppConfig(templates_path="./templates")
    service = MwlGeneratorService(app_config=cfg)

    modalities = service.get_template_modalities()
    assert modalities == ["CT"]

    ct_templates = service.get_dicom_templates_by_modality("CT")
    assert len(ct_templates) == 1
    ds = ct_templates[0]
    assert ds.Modality == "CT"
    assert ds.Rows == 128
    assert ds.Columns == 128
    assert getattr(ds, "PatientName", "") == "CompressedSamples^CT1"


def test_mwl_generate_json_and_dataset():
    service = MwlGeneratorService()
    json_entry = service.generate_json()

    assert "00080050" in json_entry  # Accession
    assert "00080060" in json_entry  # Modality
    assert "00100010" in json_entry  # PatientName
    assert "00100020" in json_entry  # PatientID
    assert "00400100" in json_entry  # ScheduledProcedureStepSequence

    dataset = service.generate_dataset()
    assert dataset.PatientID is not None
    assert dataset.AccessionNumber is not None
    assert dataset.Modality is not None
    assert len(dataset.ScheduledProcedureStepSequence) > 0


def test_mwl_custom_overrides():
    service = MwlGeneratorService()
    custom = {
        "patientName": "TEST^CUSTOM",
        "patientId": "CUSTOM-123",
        "modality": "MG",
        "studyDescription": "Mammogram Exam",
    }
    json_entry = service.generate_json(custom=custom)
    assert json_entry["00100010"]["Value"][0]["Alphabetic"] == "TEST^CUSTOM"
    assert json_entry["00100020"]["Value"][0] == "CUSTOM-123"
    assert json_entry["00080060"]["Value"][0] == "MG"


def test_rate_calculation_business_vs_after_hours():
    cfg = AppConfig(mwl_rate_per_hr=12.0)
    service = MwlGeneratorService(app_config=cfg)

    # 10:00 AM local time (Business hours: 9am-5pm)
    dt_biz = datetime(2026, 8, 28, 10, 0, 0)
    rate_biz = service.get_current_rate_per_hr(dt_biz)
    assert rate_biz == 12.0

    # 8:00 PM local time (After hours: < 9am or >= 5pm)
    dt_after = datetime(2026, 8, 28, 20, 0, 0)
    rate_after = service.get_current_rate_per_hr(dt_after)
    assert rate_after == 0.6 or round(rate_after, 4) == 0.6


def test_window_retention_purging():
    cfg = AppConfig(mwl_window_hr=24)
    service = MwlGeneratorService(app_config=cfg)

    now = datetime(2026, 8, 28, 12, 0, 0)
    # Manually append entries created at different times
    rec_recent = service.generate_json(scheduled_at=now - timedelta(hours=5))
    ds_recent = service.json_to_dataset(rec_recent)
    service._entries.append({
        "json_entry": rec_recent,
        "dataset": ds_recent,
        "created_at": now - timedelta(hours=5),
        "patient_id": rec_recent["00100020"]["Value"][0],
        "patient_name": "RECENT^PATIENT",
        "accession": rec_recent["00080050"]["Value"][0],
        "modality": "CT",
        "study_uid": rec_recent["0020000D"]["Value"][0],
    })

    rec_old = service.generate_json(scheduled_at=now - timedelta(hours=30))
    ds_old = service.json_to_dataset(rec_old)
    service._entries.append({
        "json_entry": rec_old,
        "dataset": ds_old,
        "created_at": now - timedelta(hours=30),
        "patient_id": rec_old["00100020"]["Value"][0],
        "patient_name": "OLD^PATIENT",
        "accession": rec_old["00080050"]["Value"][0],
        "modality": "CT",
        "study_uid": rec_old["0020000D"]["Value"][0],
    })

    assert len(service._entries) == 2

    # Purging relative to `now` should remove the 30hr old entry
    purged_count = service.purge_expired_entries(now)
    assert purged_count == 1
    assert len(service._entries) == 1
    assert service._entries[0]["patient_name"] == "RECENT^PATIENT"



def test_seed_initial_entries():
    cfg = AppConfig(mwl_window_hr=24)
    service = MwlGeneratorService(app_config=cfg)
    seeded = service.seed_initial_entries(count=5)

    assert len(seeded) == 5
    assert len(service.list_entries()) == 5
    status = service.get_status()
    assert status["active_entries_count"] == 5
    assert status["window_hr"] == 24
    assert status["base_rate_per_hr"] == 12.0


def test_mwl_generator_randomized_instance_counts():
    """Verify that generated MWL entries have randomized instance counts between min_slices and max_slices."""
    cfg = AppConfig(min_slices=8, max_slices=24)
    service = MwlGeneratorService(app_config=cfg)

    counts = set()
    for _ in range(30):
        entry = service.add_entry()
        count = entry["num_instances"]
        assert 8 <= count <= 24
        counts.add(count)

    # Across 30 generated entries, we should observe multiple distinct instance counts
    assert len(counts) > 1


def test_mwl_generator_modality_aligned_study_descriptions():
    """Verify MWL entries generate modality-appropriate study descriptions."""
    from dicom_py_mock_server.services.generator import MODALITY_STUDY_DESCRIPTIONS

    service = MwlGeneratorService()
    for modality in ["CT", "MR", "US", "DX", "CR", "MG", "NM", "PT", "XA", "RF", "OT"]:
        entry = service.generate_json(custom={"modality": modality})
        desc = entry["00081030"]["Value"][0]
        assert desc in MODALITY_STUDY_DESCRIPTIONS[modality]

