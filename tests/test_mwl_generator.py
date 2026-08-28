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
    from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, MRImageStorage, generate_uid

    # Create Part-10 DICOM file (.dcm)
    file_meta_ct = FileMetaDataset()
    file_meta_ct.MediaStorageSOPClassUID = CTImageStorage
    file_meta_ct.MediaStorageSOPInstanceUID = generate_uid()
    file_meta_ct.TransferSyntaxUID = ExplicitVRLittleEndian
    ds_ct = FileDataset(str(tmp_path / "sample_ct.dcm"), {}, file_meta=file_meta_ct, preamble=b"\x00" * 128)
    ds_ct.Modality = "CT"
    ds_ct.SOPClassUID = CTImageStorage
    ds_ct.SOPInstanceUID = file_meta_ct.MediaStorageSOPInstanceUID
    ds_ct.is_little_endian = True
    ds_ct.is_implicit_VR = False
    ds_ct.save_as(tmp_path / "sample_ct.dcm", enforce_file_format=True)

    # Create raw DICOM file without preamble (.dicom)
    ds_mr = Dataset()
    ds_mr.Modality = "MR"
    ds_mr.SOPClassUID = MRImageStorage
    ds_mr.SOPInstanceUID = generate_uid()
    ds_mr.is_little_endian = True
    ds_mr.is_implicit_VR = True
    ds_mr.save_as(tmp_path / "sample_mr.dicom", enforce_file_format=False)

    cfg = AppConfig(templates_path=str(tmp_path))
    service = MwlGeneratorService(app_config=cfg)

    modalities = service.get_template_modalities()
    assert set(modalities) == {"CT", "MR"}

    # Check indexed DICOM templates by Modality key
    ct_templates = service.get_dicom_templates_by_modality("CT")
    mr_templates = service.get_dicom_templates_by_modality("MR")

    assert len(ct_templates) == 1
    assert ct_templates[0].Modality == "CT"
    assert len(mr_templates) == 1
    assert mr_templates[0].Modality == "MR"


def test_mwl_generator_no_modality_fallback_when_template_present(tmp_path):
    from pydicom.dataset import Dataset

    # Create ONLY a single CT DICOM template file
    ds_ct = Dataset()
    ds_ct.Modality = "CT"
    ds_ct.is_little_endian = True
    ds_ct.is_implicit_VR = True
    ds_ct.save_as(tmp_path / "only_ct.dcm", enforce_file_format=False)

    cfg = AppConfig(templates_path=str(tmp_path))
    service = MwlGeneratorService(app_config=cfg)

    modalities = service.get_template_modalities()
    assert modalities == ["CT"]

    # Generate multiple MWL entries and verify ALL of them have Modality "CT"
    for _ in range(10):
        entry = service.generate_json()
        assert entry["00080060"]["Value"][0] == "CT"


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
