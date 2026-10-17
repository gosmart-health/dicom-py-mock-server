"""Unit tests for SyntheaUtils using the Synthea FHIR dataset in ./tests/synthea/fhir."""

import json
import os

import pytest

from dicom_py_mock_server.models import FhirBundle
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
