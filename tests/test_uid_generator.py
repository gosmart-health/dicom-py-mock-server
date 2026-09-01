"""Comprehensive tests for deterministic ITU-T X.667 / ISO/IEC 9834-8 DICOM UID generator."""

import uuid

import pytest

from dicom_py_mock_server.models.dicom import MockDicomRequest, PatientModel, SeriesModel, StudyModel
from dicom_py_mock_server.services.generator import DicomGeneratorService
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService
from dicom_py_mock_server.services.uid_generator import (
    DICOM_UID_ROOT,
    dicom_uid_to_uuid,
    generate_deterministic_uid,
    generate_dicom_uid,
    generate_series_uid,
    generate_sop_instance_uid,
    generate_study_uid,
    uuid_to_dicom_uid,
)


def test_uuid_to_dicom_uid_format_and_length():
    """Verify conversion of UUID to 2.25.<u128> decimal string and length constraint."""
    u = uuid.uuid4()
    dicom_uid = uuid_to_dicom_uid(u)

    assert dicom_uid.startswith(f"{DICOM_UID_ROOT}.")
    assert len(dicom_uid) <= 64

    # Verify round-trip conversion
    recovered_u = dicom_uid_to_uuid(dicom_uid)
    assert recovered_u == u
    assert recovered_u.int == u.int


def test_uuid_bitfields_itu_t_x667_compliance():
    """Verify version and variant bitfields comply with RFC 4122 / ITU-T X.667."""
    custom_ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

    # UUID Version 5 (SHA-1)
    uid_v5 = generate_deterministic_uid("test-sample-payload", namespace=custom_ns, version=5)
    parsed_v5 = dicom_uid_to_uuid(uid_v5)
    assert parsed_v5.version == 5
    assert parsed_v5.variant == uuid.RFC_4122

    # UUID Version 3 (MD5)
    uid_v3 = generate_deterministic_uid("test-sample-payload", namespace=custom_ns, version=3)
    parsed_v3 = dicom_uid_to_uuid(uid_v3)
    assert parsed_v3.version == 3
    assert parsed_v3.variant == uuid.RFC_4122

    with pytest.raises(ValueError, match="Unsupported UUID version"):
        generate_deterministic_uid("test-sample-payload", version=1)


def test_study_uid_determinism_and_components():
    """Verify StudyInstanceUID is deterministically derived from PatientName, PatientID, and AccessionNumber."""
    uid1 = generate_study_uid("DOE^JOHN", "MRN-12345", "ACC-998877")
    uid2 = generate_study_uid("DOE^JOHN", "MRN-12345", "ACC-998877")
    assert uid1 == uid2
    assert uid1.startswith("2.25.")
    assert len(uid1) <= 64

    # Changing PatientName changes StudyUID
    uid_diff_name = generate_study_uid("SMITH^JANE", "MRN-12345", "ACC-998877")
    assert uid_diff_name != uid1

    # Changing PatientID changes StudyUID
    uid_diff_id = generate_study_uid("DOE^JOHN", "MRN-54321", "ACC-998877")
    assert uid_diff_id != uid1

    # Changing AccessionNumber changes StudyUID
    uid_diff_acc = generate_study_uid("DOE^JOHN", "MRN-12345", "ACC-112233")
    assert uid_diff_acc != uid1


def test_series_and_sop_instance_uid_hierarchy():
    """Verify hierarchical derivation: StudyUID -> SeriesUID -> SOPInstanceUID."""
    study_uid = generate_study_uid("DOE^JOHN", "MRN-12345", "ACC-998877")

    series_uid_1 = generate_series_uid(study_uid, series_number=1)
    series_uid_2 = generate_series_uid(study_uid, series_number=2)
    assert series_uid_1 != series_uid_2
    assert series_uid_1.startswith("2.25.")
    assert series_uid_2.startswith("2.25.")

    # SOP Instance UIDs derived from Series 1
    sop_uid_1_1 = generate_sop_instance_uid(series_uid_1, instance_number=1)
    sop_uid_1_2 = generate_sop_instance_uid(series_uid_1, instance_number=2)
    assert sop_uid_1_1 != sop_uid_1_2
    assert sop_uid_1_1.startswith("2.25.")

    # SOP Instance UID for Series 2 with same instance number is distinct
    sop_uid_2_1 = generate_sop_instance_uid(series_uid_2, instance_number=1)
    assert sop_uid_2_1 != sop_uid_1_1

    # Repetition produces exact same UIDs
    assert generate_sop_instance_uid(series_uid_1, instance_number=1) == sop_uid_1_1


def test_phi_protection_in_generated_uids():
    """Verify that sensitive PHI tokens do not appear in generated UIDs."""
    patient_name = "SECRET_CELEBRITY^PATIENT"
    patient_id = "SSN-999-88-7777"
    accession = "TOP-SECRET-ACCESSION"

    study_uid = generate_study_uid(patient_name, patient_id, accession)
    series_uid = generate_series_uid(study_uid, 1)
    sop_uid = generate_sop_instance_uid(series_uid, 1)

    for uid in (study_uid, series_uid, sop_uid):
        assert "SECRET" not in uid
        assert "CELEBRITY" not in uid
        assert "999-88-7777" not in uid
        assert "TOP-SECRET" not in uid
        # Must be valid 2.25.<integer>
        parts = uid.split(".")
        assert len(parts) == 3
        assert parts[0] == "2"
        assert parts[1] == "25"
        assert parts[2].isdigit()


def test_generator_service_uid_integration():
    """Verify DicomGeneratorService assigns standards-compliant 2.25 UIDs."""
    generator = DicomGeneratorService()
    req = MockDicomRequest(
        patient=PatientModel(patient_id="PAT-DET-001", patient_name="DETERMINISTIC^PATIENT"),
        study=StudyModel(accession_number="ACC-DET-001"),
        series=SeriesModel(modality="CT", series_number=1),
        num_instances=3,
    )

    ds1 = generator.create_dicom_file(req, instance_number=1)
    ds2 = generator.create_dicom_file(req, instance_number=2)

    assert ds1.StudyInstanceUID.startswith("2.25.")
    assert ds1.SeriesInstanceUID.startswith("2.25.")
    assert ds1.SOPInstanceUID.startswith("2.25.")

    # Study and Series UIDs match across instances of same series
    assert ds1.StudyInstanceUID == ds2.StudyInstanceUID
    assert ds1.SeriesInstanceUID == ds2.SeriesInstanceUID

    # SOP Instance UIDs differ
    assert ds1.SOPInstanceUID != ds2.SOPInstanceUID

    # SOP Instance UID in FileMeta matches SOPCommon module
    assert ds1.file_meta.MediaStorageSOPInstanceUID == ds1.SOPInstanceUID


def test_mwl_service_uid_integration():
    """Verify MwlGeneratorService assigns deterministic 2.25 UIDs."""
    service = MwlGeneratorService()
    entry = service.add_entry(
        custom={
            "patientName": "MWL^DET^PATIENT",
            "patientId": "MWL-ID-001",
            "accession": "MWL-ACC-001",
            "modality": "CT",
        }
    )

    assert entry["study_uid"].startswith("2.25.")
    assert entry["series_uid"].startswith("2.25.")

    # Re-generating with identical attributes generates identical StudyUID
    entry2 = service.generate_json(
        custom={
            "patientName": "MWL^DET^PATIENT",
            "patientId": "MWL-ID-001",
            "accession": "MWL-ACC-001",
            "modality": "CT",
        }
    )
    assert entry2["0020000D"]["Value"][0] == entry["study_uid"]

    # Image level C-FIND datasets use 2.25 UIDs
    cfind_images = MwlGeneratorService.to_image_cfind_datasets(entry)
    assert len(cfind_images) == entry["num_instances"]
    for i, ds in enumerate(cfind_images, 1):
        assert str(ds.StudyInstanceUID) == entry["study_uid"]
        assert str(ds.SeriesInstanceUID) == entry["series_uid"]
        assert str(ds.SOPInstanceUID).startswith("2.25.")
        assert ds.InstanceNumber == i


def test_generate_dicom_uid_fallback_and_seed():
    """Verify generate_dicom_uid with seed vs unseeded random fallback."""
    uid_unseeded = generate_dicom_uid()
    assert uid_unseeded.startswith("2.25.")
    parsed_unseeded = dicom_uid_to_uuid(uid_unseeded)
    assert parsed_unseeded.version == 4

    uid_seeded = generate_dicom_uid("custom-seed-value")
    assert uid_seeded.startswith("2.25.")
    parsed_seeded = dicom_uid_to_uuid(uid_seeded)
    assert parsed_seeded.version == 5
