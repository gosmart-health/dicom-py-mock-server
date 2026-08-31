"""Unit and integration tests for Physician and Institution attribute features."""

from dicom_py_mock_server.config import AppConfig
from dicom_py_mock_server.models.dicom import (
    MockDicomRequest,
    PatientModel,
    SeriesModel,
    StudyModel,
)
from dicom_py_mock_server.services.generator import DicomGeneratorService
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService
from dicom_py_mock_server.services.person_generator import PersonGenerator


def test_config_physician_suffix_and_institution_defaults():
    """Verify default values for pn_suffix and institution_name."""
    cfg = AppConfig()
    assert cfg.pn_suffix == "_GSH"
    assert cfg.institution_name == "GO SMART CLINIC"


def test_config_physician_suffix_and_institution_env_overrides(monkeypatch):
    """Verify env variable overrides including GORMART_MS_INSTITUTION_NAME typo and empty pn_suffix."""
    monkeypatch.setenv("GOSMART_MS_PN_SUFFIX", "_DOC")
    monkeypatch.setenv("GORMART_MS_INSTITUTION_NAME", "CUSTOM CLINIC")
    cfg = AppConfig()
    assert cfg.pn_suffix == "_DOC"
    assert cfg.institution_name == "CUSTOM CLINIC"

    # Empty string for pn_suffix
    monkeypatch.setenv("GOSMART_MS_PN_SUFFIX", "")
    cfg_empty = AppConfig()
    assert cfg_empty.pn_suffix == ""


def test_person_generator_physician_names():
    """Verify PersonGenerator generates physician names with pn_suffix."""
    gen = PersonGenerator(pn_suffix="_GSH")
    physician = gen.generate_physician("MD")
    assert physician.name.split("^")[0].endswith("_GSH")
    assert physician.name.endswith("^^^MD")

    # Empty pn_suffix
    plain_gen = PersonGenerator(pn_suffix="")
    plain_physician = plain_gen.generate_physician("MD")
    assert not plain_physician.name.split("^")[0].endswith("_GSH")
    assert plain_physician.name.endswith("^^^MD")

    # Physician pool generation
    pool = gen.generate_physician_pool(count=3, title="MD")
    assert len(pool) == 3
    for name in pool:
        assert name.split("^")[0].endswith("_GSH")
        assert name.endswith("^^^MD")


def test_mwl_generator_initial_physician_pools():
    """Verify MWL generator initializes pools of 3 referring, 3 performing, and 3 reading physicians."""
    service = MwlGeneratorService()
    assert len(service.referring_physicians) == 3
    assert len(service.performing_physicians) == 3
    assert len(service.reading_physicians) == 3

    for pool in [service.referring_physicians, service.performing_physicians, service.reading_physicians]:
        for doc_name in pool:
            assert doc_name.split("^")[0].endswith("_GSH")
            assert "^^^MD" in doc_name or doc_name.endswith("MD")


def test_mwl_entry_physician_and_institution_random_selection():
    """Verify MWL entries randomly pick from the physician pools and populate institution."""
    service = MwlGeneratorService()
    entry_json = service.generate_json()

    # Verify JSON structure
    assert "00080080" in entry_json  # InstitutionName
    assert entry_json["00080080"]["Value"][0] == "GO SMART CLINIC"

    assert "00080090" in entry_json  # ReferringPhysicianName
    ref_name = entry_json["00080090"]["Value"][0]["Alphabetic"]
    assert ref_name in service.referring_physicians

    assert "00081050" in entry_json  # PerformingPhysicianName
    perf_name = entry_json["00081050"]["Value"][0]["Alphabetic"]
    assert perf_name in service.performing_physicians

    assert "00081060" in entry_json  # NameOfPhysiciansReadingStudy
    read_name = entry_json["00081060"]["Value"][0]["Alphabetic"]
    assert read_name in service.reading_physicians

    # ScheduledProcedureStepSequence
    sps_perf = entry_json["00400100"]["Value"][0]["00400006"]["Value"]
    sps_perf_val = sps_perf[0]["Alphabetic"] if isinstance(sps_perf, list) else sps_perf.get("Alphabetic", sps_perf)
    assert sps_perf_val in service.performing_physicians

    # Verify dataset conversion
    ds = service.generate_dataset()
    assert ds.InstitutionName == "GO SMART CLINIC"
    assert str(ds.ReferringPhysicianName) in service.referring_physicians
    assert str(ds.PerformingPhysicianName) in service.performing_physicians
    assert str(ds.NameOfPhysiciansReadingStudy) in service.reading_physicians
    assert str(ds.ScheduledProcedureStepSequence[0].ScheduledPerformingPhysicianName) in service.performing_physicians


def test_sop_instance_generation_attribute_propagation_from_mwl():
    """Verify SOP instances created from MWL record propagate all 4 attributes."""
    service = MwlGeneratorService()
    record = service.add_entry()

    assert record["institution_name"] == "GO SMART CLINIC"
    assert record["referring_physician"] in service.referring_physicians
    assert record["performing_physician"] in service.performing_physicians
    assert record["reading_physician"] in service.reading_physicians

    datasets = DicomGeneratorService.create_instances_from_mwl(record, num_instances=2)
    assert len(datasets) == 2

    for ds in datasets:
        assert ds.InstitutionName == "GO SMART CLINIC"
        assert str(ds.ReferringPhysicianName) == record["referring_physician"]
        assert str(ds.PerformingPhysicianName) == record["performing_physician"]
        assert str(ds.NameOfPhysiciansReadingStudy) == record["reading_physician"]


def test_sop_instance_direct_generation_physicians_and_institution():
    """Verify direct create_dicom_file populates Institution and Physician tags."""
    generator = DicomGeneratorService()
    req = MockDicomRequest(
        patient=PatientModel(patient_id="DOC-PAT-001"),
        study=StudyModel(
            institution_name="TEST MEDICAL CENTER",
            referring_physician_name="REF_DOC_GSH^ALICE^^^MD",
            reading_physician_name="READ_DOC_GSH^BOB^^^MD",
            performing_physician_name="PERF_DOC_GSH^CHARLIE^^^MD",
        ),
        series=SeriesModel(
            modality="CT",
            performing_physician_name="PERF_DOC_GSH^CHARLIE^^^MD",
        ),
        num_instances=1,
    )
    ds = generator.create_dicom_file(req, instance_number=1)

    assert ds.InstitutionName == "TEST MEDICAL CENTER"
    assert str(ds.ReferringPhysicianName) == "REF_DOC_GSH^ALICE^^^MD"
    assert str(ds.NameOfPhysiciansReadingStudy) == "READ_DOC_GSH^BOB^^^MD"
    assert str(ds.PerformingPhysicianName) == "PERF_DOC_GSH^CHARLIE^^^MD"


def test_study_and_series_cfind_dataset_includes_physicians_and_institution():
    """Verify to_study_cfind_dataset and to_series_cfind_dataset include physician and institution attributes."""
    service = MwlGeneratorService()
    record = service.add_entry(
        custom={
            "institutionName": "TEST INSTITUTION",
            "referringPhysician": "REF^DOC^^^MD",
            "performingPhysician": "PERF^DOC^^^MD",
            "readingPhysician": "READ^DOC^^^MD",
        }
    )

    study_ds = service.to_study_cfind_dataset(record)
    assert study_ds.InstitutionName == "TEST INSTITUTION"
    assert str(study_ds.ReferringPhysicianName) == "REF^DOC^^^MD"
    assert str(study_ds.PerformingPhysicianName) == "PERF^DOC^^^MD"
    assert str(study_ds.NameOfPhysiciansReadingStudy) == "READ^DOC^^^MD"

    series_ds = service.to_series_cfind_dataset(record)
    assert series_ds.InstitutionName == "TEST INSTITUTION"
    assert str(series_ds.PerformingPhysicianName) == "PERF^DOC^^^MD"
