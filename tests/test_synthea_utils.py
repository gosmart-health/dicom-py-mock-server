"""Unit tests for SyntheaUtils using the Synthea FHIR dataset in ./tests/synthea/fhir."""

import json
import os
import pathlib
import unittest.mock

import pytest

from dicom_py_mock_server.models import FhirBundle
from dicom_py_mock_server.models.fhir_models import FhirIdentifier, FhirPatient
from dicom_py_mock_server.services.synthea_utils import SyntheaUtils

SYNTHEA_FHIR_FOLDER = "./tests/synthea/fhir"
DX_ONLY_PATIENT_FILE = os.path.join(
    SYNTHEA_FHIR_FOLDER,
    "Abbey813_Pollich983_b86d32b0-5bd7-2bbd-c575-b07bfaa9270e.json",
)
CR_US_PATIENT_FILE = os.path.join(
    SYNTHEA_FHIR_FOLDER,
    "Alden634_Hettinger594_1bbc0b16-2965-fc1c-0a29-c8237663d154.json",
)
HOSPITAL_FILE = os.path.join(
    SYNTHEA_FHIR_FOLDER,
    "hospitalInformation1791996124090.json",
)
PRACTITIONER_FILE = os.path.join(
    SYNTHEA_FHIR_FOLDER,
    "practitionerInformation1791996124090.json",
)


def test_synthea_utils_init_default_modalities():
    """Verify that SyntheaUtils initializes with default modalities when unspecified."""
    syn = SyntheaUtils(synthea_output_folder=SYNTHEA_FHIR_FOLDER)
    assert syn._modalities == ["CT", "US", "CR"]
    assert syn.modalities == ["CT", "US", "CR"]


def test_synthea_utils_init_custom_modalities():
    """Verify that SyntheaUtils assigns specified modalities."""
    custom_mods = ["MR", "DX", "PET"]
    syn = SyntheaUtils(synthea_output_folder=SYNTHEA_FHIR_FOLDER, modalities=custom_mods)
    assert syn._modalities == custom_mods
    assert syn.modalities == custom_mods


def test_synthea_utils_filter_imaging_bundle():
    """Verify filter_imaging_bundle and get_imaging_studies use self._modalities on real Synthea data."""
    with open(DX_ONLY_PATIENT_FILE, "r", encoding="utf-8") as f:
        bundle = FhirBundle.model_validate(json.load(f))

    # Default modalities (["CT", "US", "CR"]) do not include DX
    syn_default = SyntheaUtils(synthea_output_folder=SYNTHEA_FHIR_FOLDER)
    assert syn_default.filter_imaging_bundle(bundle) is None
    assert len(syn_default.get_imaging_studies(bundle)) == 0

    # Custom modalities including DX match the bundle
    syn_dx = SyntheaUtils(synthea_output_folder=SYNTHEA_FHIR_FOLDER, modalities=["DX"])
    assert syn_dx.filter_imaging_bundle(bundle) is not None
    studies_dx = syn_dx.get_imaging_studies(bundle)
    assert len(studies_dx) > 0


def test_synthea_utils_scan_and_load_without_modalities_param():
    """Verify load_synthea_bundle and scan_synthea_output against ./tests/synthea/fhir."""
    syn = SyntheaUtils(synthea_output_folder=SYNTHEA_FHIR_FOLDER)

    # File with only DX returns None with default modalities
    assert syn.load_synthea_bundle(DX_ONLY_PATIENT_FILE) is None

    # File with CR/US returns a validated FhirBundle with default modalities
    loaded = syn.load_synthea_bundle(CR_US_PATIENT_FILE)
    assert loaded is not None

    # scan_synthea_output scans the real dataset and populates self._patient_bundles
    scanned = syn.scan_synthea_output(max_count=5)
    assert len(scanned) == 1
    assert syn._patient_bundles == scanned


def test_synthea_utils_methods_throw_exception_when_patient_bundles_is_none():
    """Verify that helper methods raise an exception when bundle is None and self._patient_bundles is None."""
    syn = SyntheaUtils(synthea_output_folder=SYNTHEA_FHIR_FOLDER)
    assert syn._patient_bundles is None

    with pytest.raises(ValueError):
        syn.filter_imaging_bundle()

    with pytest.raises(ValueError):
        syn.get_patient()

    with pytest.raises(ValueError):
        syn.get_encounters()

    with pytest.raises(ValueError):
        syn.get_imaging_studies()

    with pytest.raises(ValueError):
        syn.get_diagnostic_reports()

    with pytest.raises(ValueError):
        syn.get_procedures()


def test_synthea_utils_methods_use_patient_bundles_when_bundle_is_none():
    """Verify that methods use self._patient_bundles populated from ./tests/synthea/fhir when bundle is None."""
    syn = SyntheaUtils(synthea_output_folder=SYNTHEA_FHIR_FOLDER)
    scanned = syn.scan_synthea_output(max_count=5)
    assert len(scanned) == 1

    # filter_imaging_bundle uses self._patient_bundles
    matched = syn.filter_imaging_bundle()
    assert matched is not None

    # get_patient and demographic helpers use self._patient_bundles
    patient = syn.get_patient()
    assert patient is not None
    assert syn.get_patient_name(patient) == "Hettinger594^Alden634^Frankie174^Mr.^JD"
    assert syn.get_patient_id(patient) == "S99916806"
    assert syn.get_patient_sex(patient) == "M"
    assert syn.get_date_time(patient.birthDate) == ("19260821", "")

    # get_imaging_studies uses self._patient_bundles
    studies = syn.get_imaging_studies()
    assert len(studies) == 8

    # get_encounters uses self._patient_bundles
    enc_ref = studies[0].encounter.reference
    encounters = syn.get_encounters(encounter_ref=enc_ref)
    assert len(encounters) == 1
    assert encounters[0].id == "1bbc0b16-2965-fc1c-b8e2-01ed9b1da080"

    # get_diagnostic_reports uses self._patient_bundles
    reports = syn.get_diagnostic_reports(encounter_ref=enc_ref)
    assert len(reports) == 11

    # get_procedures uses self._patient_bundles
    procedures = syn.get_procedures(encounter_ref=enc_ref)
    assert len(procedures) == 17

    # get_hospital_information and get_practitioner_information resolve references from ./tests/synthea/fhir
    hospitals = syn.get_hospital_information(reference=encounters[0].serviceProvider.reference)
    assert len(hospitals) == 1
    assert hospitals[0].name == "Fitchburg Outpatient Clinic"

    practitioners = syn.get_practitioner_information(reference=encounters[0].participant[0].individual.reference)
    assert len(practitioners) == 1
    assert practitioners[0].id == "ef3edc9b-f77c-37c1-922f-ce1c1a5fcf09"


def test_synthea_utils_parse_file_uri_validation():
    """Verify parse_file_uri accepts valid file:// JSON URIs and rejects invalid schemes or paths."""
    valid_uri = pathlib.Path(os.path.abspath(CR_US_PATIENT_FILE)).as_uri()
    resolved = SyntheaUtils.parse_file_uri(valid_uri)
    assert os.path.isfile(resolved)
    assert resolved.endswith(".json")

    with pytest.raises(ValueError, match="Unsupported URI scheme"):
        SyntheaUtils.parse_file_uri("s3://bucket/patient.json")

    with pytest.raises(ValueError, match="Unsupported URI scheme"):
        SyntheaUtils.parse_file_uri("http://example.com/patient.json")

    dir_uri = pathlib.Path(os.path.abspath(SYNTHEA_FHIR_FOLDER)).as_uri()
    with pytest.raises(ValueError, match="directory"):
        SyntheaUtils.parse_file_uri(dir_uri)

    with pytest.raises(ValueError, match="must point to a .json file"):
        SyntheaUtils.parse_file_uri("file:///tmp/not_a_json.txt")

    with pytest.raises(ValueError, match="File not found"):
        SyntheaUtils.parse_file_uri("file:///nonexistent_path/missing_bundle.json")

    # Verify Windows-style file:// URI with drive letter resolves without duplicating drive
    with (
        unittest.mock.patch("urllib.request.url2pathname", return_value=r"D:\a\test\patient.json"),
        unittest.mock.patch("os.path.abspath", side_effect=lambda p: p),
        unittest.mock.patch("os.path.exists", return_value=True),
        unittest.mock.patch("os.path.isfile", return_value=True),
        unittest.mock.patch("os.path.isdir", return_value=False),
    ):
        res = SyntheaUtils.parse_file_uri("file:///D:/a/test/patient.json")
        assert res == r"D:\a\test\patient.json"


def test_synthea_utils_additive_uri_loading_and_deduplication():
    """Verify load_synthea_uri additively caches hospital, practitioner, and patient bundles without duplicates."""
    syn = SyntheaUtils(synthea_output_folder="")
    assert not syn.has_hospital_and_practitioner_info()

    hosp_uri = pathlib.Path(os.path.abspath(HOSPITAL_FILE)).as_uri()
    prac_uri = pathlib.Path(os.path.abspath(PRACTITIONER_FILE)).as_uri()
    patient_uri = pathlib.Path(os.path.abspath(CR_US_PATIENT_FILE)).as_uri()
    dx_uri = pathlib.Path(os.path.abspath(DX_ONLY_PATIENT_FILE)).as_uri()

    b_type, hosp_bundle = syn.load_synthea_uri(hosp_uri)
    assert b_type == "hospital"
    assert hosp_bundle is not None
    assert len(syn._hospital_bundles) == 1
    assert not syn.has_hospital_and_practitioner_info()

    # Duplicate load of the same hospital bundle does not duplicate
    syn.load_synthea_uri(hosp_uri)
    assert len(syn._hospital_bundles) == 1

    b_type, prac_bundle = syn.load_synthea_uri(prac_uri)
    assert b_type == "practitioner"
    assert prac_bundle is not None
    assert len(syn._practitioner_bundles) == 1
    assert syn.has_hospital_and_practitioner_info()

    # Duplicate load of the same practitioner bundle does not duplicate
    syn.load_synthea_uri(prac_uri)
    assert len(syn._practitioner_bundles) == 1

    # Patient bundle without supported modalities returns ("patient", None) and is not cached
    b_type, skipped_bundle = syn.load_synthea_uri(dx_uri)
    assert b_type == "patient"
    assert skipped_bundle is None
    assert syn._patient_bundles is None

    # Patient bundle with supported CR/US modalities is cached additively
    b_type, pat_bundle = syn.load_synthea_uri(patient_uri)
    assert b_type == "patient"
    assert pat_bundle is not None
    assert len(syn._patient_bundles) == 1

    # Duplicate load of the same patient bundle does not duplicate
    syn.load_synthea_uri(patient_uri)
    assert len(syn._patient_bundles) == 1

    # Verify get_patient_bundle_by_id works by primary ID, MRN/UUID, and returns None for unknown
    by_dl = syn.get_patient_bundle_by_id("S99916806")
    assert by_dl is not None
    by_uuid = syn.get_patient_bundle_by_id("1bbc0b16-2965-fc1c-0a29-c8237663d154")
    assert by_uuid is not None
    assert syn.get_patient_bundle_by_id("NONEXISTENT-ID") is None


def test_synthea_utils_get_patient_id_fallbacks():
    """Verify get_patient_id falls back to MRN and patient.id when driver's license OID is missing."""
    syn = SyntheaUtils(synthea_output_folder="")

    patient_mrn_only = FhirPatient(
        id="patient-uuid-1",
        identifier=[
            FhirIdentifier(system="http://hospital.smarthealthit.org", value="MRN-12345"),
        ],
    )
    assert syn.get_patient_id(patient_mrn_only) == "MRN-12345"

    patient_id_only = FhirPatient(id="patient-uuid-2")
    assert syn.get_patient_id(patient_id_only) == "patient-uuid-2"


def test_synthea_utils_load_and_generate_from_uris(tmp_path):
    """Verify two-pass URI ingestion creates coherent MWL entries and on-disk DICOM files."""
    import pydicom

    from dicom_py_mock_server.services.generator import DicomGeneratorService
    from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService

    syn = SyntheaUtils(synthea_output_folder="")
    mwl_service = MwlGeneratorService()
    mwl_service._entries.clear()
    generator_service = DicomGeneratorService()

    hosp_uri = pathlib.Path(os.path.abspath(HOSPITAL_FILE)).as_uri()
    prac_uri = pathlib.Path(os.path.abspath(PRACTITIONER_FILE)).as_uri()
    patient_uri = pathlib.Path(os.path.abspath(CR_US_PATIENT_FILE)).as_uri()
    dx_uri = pathlib.Path(os.path.abspath(DX_ONLY_PATIENT_FILE)).as_uri()

    # Loading a patient bundle before hospital & practitioner bundles raises ValueError
    with pytest.raises(ValueError, match="Hospital and practitioner information"):
        syn.load_and_generate_from_uris(
            [patient_uri],
            mwl_service=mwl_service,
            generator_service=generator_service,
            target_dir=str(tmp_path),
        )

    # Loading patient URI alongside hospital & practitioner URIs (even with patient URI listed first) succeeds
    responses = syn.load_and_generate_from_uris(
        [patient_uri, dx_uri, hosp_uri, prac_uri],
        mwl_service=mwl_service,
        generator_service=generator_service,
        target_dir=str(tmp_path),
    )

    assert len(responses) == 8
    # Male patient has 7 CR series and 1 US series; US MWL entry is skipped because US template has PatientSex == 'F'
    assert len(mwl_service._entries) == 7

    first_resp = responses[0]
    first_mwl = mwl_service._entries[0]
    assert first_resp.patient_id == "S99916806"
    assert first_mwl["patient_id"] == "S99916806"
    assert first_resp.study_instance_uid == first_mwl["study_uid"]
    assert not first_resp.study_instance_uid.startswith("urn:oid:")
    assert first_resp.series_instance_uid == first_mwl["series_uid"]
    assert first_mwl["institution_name"] == "Fitchburg Outpatient Clinic"
    assert first_mwl["referring_physician"] == "Reilly981^Ted955^^Dr."

    ds = pydicom.dcmread(first_resp.file_paths[0])
    assert str(ds.PatientID) == "S99916806"
    assert str(ds.AccessionNumber) == first_mwl["accession"]
    assert str(ds.StudyInstanceUID) == first_resp.study_instance_uid
    assert str(ds.SeriesInstanceUID) == first_resp.series_instance_uid
    assert str(ds.InstitutionName) == "Fitchburg Outpatient Clinic"
    assert str(ds.ReferringPhysicianName) == "Reilly981^Ted955^^Dr."


def test_synthea_utils_load_and_generate_from_raw_bundles(tmp_path):
    """Verify raw JSON bundle ingestion enforces prerequisites and generates MWL and DICOM files."""
    import json

    import pydicom

    from dicom_py_mock_server.services.generator import DicomGeneratorService
    from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService

    syn = SyntheaUtils(synthea_output_folder="")
    mwl_service = MwlGeneratorService()
    mwl_service._entries.clear()
    generator_service = DicomGeneratorService()

    with open(HOSPITAL_FILE, "r", encoding="utf-8") as f:
        hosp_data = json.load(f)
    with open(PRACTITIONER_FILE, "r", encoding="utf-8") as f:
        prac_data = json.load(f)
    with open(CR_US_PATIENT_FILE, "r", encoding="utf-8") as f:
        patient_data = json.load(f)
    with open(DX_ONLY_PATIENT_FILE, "r", encoding="utf-8") as f:
        dx_data = json.load(f)

    assert not syn.has_hospital_info()
    assert not syn.has_practitioner_info()
    assert not syn.has_hospital_and_practitioner_info()

    # Empty bundle list raises ValueError
    with pytest.raises(ValueError, match="A non-empty list of FHIR Bundles is required"):
        syn.load_and_generate_from_raw_bundles([], mwl_service, generator_service)

    # Missing hospital resources raises clear error
    with pytest.raises(ValueError, match="Hospital resources must be sent first"):
        syn.load_and_generate_from_raw_bundles([patient_data], mwl_service, generator_service)

    # Load hospital resources
    syn.load_and_generate_from_raw_bundles([hosp_data], mwl_service, generator_service)
    assert syn.has_hospital_info()
    assert not syn.has_practitioner_info()

    # Missing practitioner resources raises clear error
    with pytest.raises(ValueError, match="Practitioner resources must be sent first"):
        syn.load_and_generate_from_raw_bundles([patient_data], mwl_service, generator_service)

    # Load practitioner resources
    syn.load_and_generate_from_raw_bundles([prac_data], mwl_service, generator_service)
    assert syn.has_practitioner_info()
    assert syn.has_hospital_and_practitioner_info()

    # Patient bundle without ImagingStudy does not error, logs warning and returns empty list
    skipped_bundles = syn.load_and_generate_from_raw_bundles(
        [dx_data],
        mwl_service=mwl_service,
        generator_service=generator_service,
        target_dir=str(tmp_path),
    )
    assert skipped_bundles == []

    # Patient bundle with CR/US ImagingStudy returns parsed FhirBundle list and generates DICOM + MWL
    processed_bundles = syn.load_and_generate_from_raw_bundles(
        [patient_data],
        mwl_service=mwl_service,
        generator_service=generator_service,
        target_dir=str(tmp_path),
    )
    assert len(processed_bundles) == 1
    assert processed_bundles[0].get_resource_type() == "Bundle"
    assert len(mwl_service._entries) == 7

    # Verify generated DICOM files
    dcm_files = [os.path.join(r, f) for r, _, fs in os.walk(str(tmp_path)) for f in fs if f.endswith(".dcm")]
    assert len(dcm_files) == 8
    ds = pydicom.dcmread(dcm_files[0])
    assert str(ds.PatientID) == "S99916806"


def test_synthea_patient_study_series_cfind_and_dicomweb(tmp_path):
    """Verify SyntheaUtils populates patient/study/series lists and serves C-FIND and DICOMweb queries."""
    from types import SimpleNamespace

    from pydicom.dataset import Dataset
    from pynetdicom.sop_class import (
        PatientRootQueryRetrieveInformationModelFind,
        StudyRootQueryRetrieveInformationModelFind,
    )

    from dicom_py_mock_server.services.dicomweb import DicomWebService
    from dicom_py_mock_server.services.generator import DicomGeneratorService
    from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService
    from dicom_py_mock_server.services.scp import DicomScpService

    mwl_service = MwlGeneratorService()
    mwl_service._entries.clear()
    generator_service = DicomGeneratorService()
    syn = SyntheaUtils(synthea_output_folder=SYNTHEA_FHIR_FOLDER, mwl_service=mwl_service)

    # Load all Synthea bundles from folder and process to DICOM
    responses = syn.process_all_patients_to_dicom(
        mwl_service=mwl_service,
        generator_service=generator_service,
        target_dir=str(tmp_path),
    )
    assert len(responses) == 11

    # 1. Verify SyntheaUtils maintains Patient, Study, and Series lists
    patients = syn.get_patients()
    assert len(patients) == 3
    patient_ids = {p.patient_id for p in patients}
    assert patient_ids == {"S99916806", "S99992538", "S99924581"}

    alden_patients = syn.get_patients(patient_id="S99916806")
    assert len(alden_patients) == 1
    assert alden_patients[0].patient_name == "Hettinger594^Alden634^Frankie174^Mr.^JD"
    assert alden_patients[0].patient_sex == "M"

    studies = syn.get_studies()
    assert len(studies) == 11
    alden_studies = syn.get_studies(patient_id="S99916806")
    assert len(alden_studies) == 8
    waylon_studies = syn.get_studies(patient_id="S99924581")
    assert len(waylon_studies) == 1

    series_list = syn.get_series()
    assert len(series_list) == 11
    us_series = syn.get_series(modality="US")
    assert len(us_series) == 3
    cr_series = syn.get_series(modality="CR")
    assert len(cr_series) == 8

    # 2. Verify DICOM C-FIND at PATIENT, STUDY, SERIES, and IMAGE levels
    dicomweb_service = DicomWebService(
        mwl_service=mwl_service,
        generator_service=generator_service,
        storage_dir=str(tmp_path),
        received_dir=str(tmp_path / "received"),
    )
    scp_service = DicomScpService(mwl_service=mwl_service, dicomweb_service=dicomweb_service)

    def _run_cfind(identifier_ds: Dataset, sop_class_uid=StudyRootQueryRetrieveInformationModelFind) -> list[Dataset]:
        evt_mock = SimpleNamespace(
            assoc=SimpleNamespace(requestor=SimpleNamespace(ae_title="TEST_SCU")),
            request=SimpleNamespace(AffectedSOPClassUID=sop_class_uid),
            identifier=identifier_ds,
        )
        return [ds for status, ds in scp_service._handle_find(evt_mock) if status == 0xFF00 and ds is not None]

    # 2a. PATIENT-level C-FIND (Patient Root)
    pat_query = Dataset()
    pat_query.QueryRetrieveLevel = "PATIENT"
    pat_query.PatientID = ""
    pat_query.PatientName = ""
    pat_results = _run_cfind(pat_query, sop_class_uid=PatientRootQueryRetrieveInformationModelFind)
    assert len(pat_results) == 3
    pat_map = {str(d.PatientID): d for d in pat_results}
    assert "S99916806" in pat_map
    assert "S99992538" in pat_map
    assert "S99924581" in pat_map
    assert int(pat_map["S99916806"].NumberOfPatientRelatedStudies) == 8
    assert int(pat_map["S99916806"].NumberOfPatientRelatedSeries) == 8
    assert int(pat_map["S99992538"].NumberOfPatientRelatedStudies) == 2
    assert int(pat_map["S99924581"].NumberOfPatientRelatedStudies) == 1

    # Filter PATIENT-level C-FIND by PatientName wildcard
    pat_name_query = Dataset()
    pat_name_query.QueryRetrieveLevel = "PATIENT"
    pat_name_query.PatientName = "Emmerich580*"
    pat_name_results = _run_cfind(pat_name_query, sop_class_uid=PatientRootQueryRetrieveInformationModelFind)
    assert len(pat_name_results) == 1
    assert str(pat_name_results[0].PatientID) == "S99924581"

    # 2b. STUDY-level C-FIND (finds all 11 studies across all 3 patients, including male US studies)
    study_query = Dataset()
    study_query.QueryRetrieveLevel = "STUDY"
    study_results = _run_cfind(study_query)
    assert len(study_results) == 11

    alden_study_query = Dataset()
    alden_study_query.QueryRetrieveLevel = "STUDY"
    alden_study_query.PatientID = "S99916806"
    alden_study_results = _run_cfind(alden_study_query)
    assert len(alden_study_results) == 8
    alden_modalities = {str(d.Modality) for d in alden_study_results}
    assert alden_modalities == {"CR", "US"}

    # Filter STUDY-level C-FIND by Modality=US (finds all 3 male US studies even though MWL skipped them)
    us_study_query = Dataset()
    us_study_query.QueryRetrieveLevel = "STUDY"
    us_study_query.Modality = "US"
    us_study_results = _run_cfind(us_study_query)
    assert len(us_study_results) == 3

    # 2c. SERIES-level C-FIND
    target_us_study_uid = str(us_study_results[0].StudyInstanceUID)
    series_query = Dataset()
    series_query.QueryRetrieveLevel = "SERIES"
    series_query.StudyInstanceUID = target_us_study_uid
    series_results = _run_cfind(series_query)
    assert len(series_results) == 1
    assert str(series_results[0].Modality) == "US"
    target_us_series_uid = str(series_results[0].SeriesInstanceUID)

    # 2d. IMAGE-level C-FIND
    img_query = Dataset()
    img_query.QueryRetrieveLevel = "IMAGE"
    img_query.StudyInstanceUID = target_us_study_uid
    img_query.SeriesInstanceUID = target_us_series_uid
    img_results = _run_cfind(img_query)
    assert len(img_results) >= 1
    assert str(img_results[0].StudyInstanceUID) == target_us_study_uid
    assert str(img_results[0].SeriesInstanceUID) == target_us_series_uid

    # 3. Verify DICOMweb QIDO-RS and WADO-RS queries
    qido_all_studies = dicomweb_service.search_studies({})
    assert len(qido_all_studies) == 11

    qido_alden_studies = dicomweb_service.search_studies({"PatientID": "S99916806"})
    assert len(qido_alden_studies) == 8

    qido_waylon_studies = dicomweb_service.search_studies({"PatientID": "S99924581"})
    assert len(qido_waylon_studies) == 1

    qido_us_series = dicomweb_service.search_series(target_us_study_uid, {})
    assert len(qido_us_series) == 1
    assert qido_us_series[0]["00080060"]["Value"][0] == "US"

    qido_us_instances = dicomweb_service.search_instances(target_us_study_uid, target_us_series_uid, {})
    assert len(qido_us_instances) >= 1

    wado_us_datasets = dicomweb_service.get_study_datasets(target_us_study_uid)
    assert len(wado_us_datasets) >= 1
    assert str(wado_us_datasets[0].StudyInstanceUID) == target_us_study_uid
    assert str(wado_us_datasets[0].Modality) == "US"
