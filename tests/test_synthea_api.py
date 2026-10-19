"""Integration tests for Synthea FHIR R4 REST API endpoints."""

import json
import os

import pydicom
import pytest
from fastapi.testclient import TestClient

from dicom_py_mock_server.api.fhir_routes import synthea_utils
from dicom_py_mock_server.api.routes import mwl_service
from dicom_py_mock_server.config import config
from dicom_py_mock_server.main import app

SYNTHEA_FHIR_FOLDER = "./tests/synthea/fhir"
HOSPITAL_FILE = os.path.join(SYNTHEA_FHIR_FOLDER, "hospitalInformation1791996124090.json")
PRACTITIONER_FILE = os.path.join(SYNTHEA_FHIR_FOLDER, "practitionerInformation1791996124090.json")
DX_ONLY_PATIENT_FILE = os.path.join(
    SYNTHEA_FHIR_FOLDER,
    "Abbey813_Pollich983_b86d32b0-5bd7-2bbd-c575-b07bfaa9270e.json",
)
CR_US_PATIENT_FILE = os.path.join(
    SYNTHEA_FHIR_FOLDER,
    "Alden634_Hettinger594_1bbc0b16-2965-fc1c-0a29-c8237663d154.json",
)


def _load_json(file_path: str) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def reset_synthea_and_storage(tmp_path, monkeypatch):
    """Reset synthea_utils memory caches, MWL entries, and storage_dir before each test."""
    monkeypatch.setattr(config, "storage_dir", str(tmp_path))
    synthea_utils._hospital_bundles = None
    synthea_utils._practitioner_bundles = None
    synthea_utils._patient_bundles = None
    mwl_service._entries.clear()
    yield
    synthea_utils._hospital_bundles = None
    synthea_utils._practitioner_bundles = None
    synthea_utils._patient_bundles = None


def test_synthea_load_validation_errors():
    """Verify POST /api/v1/synthea/load rejects empty payloads and invalid FHIR bundle structures."""
    client = TestClient(app)

    # Empty payload list
    resp = client.post("/api/v1/synthea/load", json=[])
    assert resp.status_code == 400
    assert "non-empty list" in resp.json()["detail"].lower()

    # Empty payload dict / None
    resp = client.post("/api/v1/synthea/load", json={})
    assert resp.status_code == 400

    # Malformed bundle content
    resp = client.post("/api/v1/synthea/load", json=[{"invalid": "not_a_bundle"}])
    assert resp.status_code == 400
    assert "invalid fhir bundle" in resp.json()["detail"].lower()


def test_synthea_load_missing_hospital_and_practitioner_prerequisites():
    """Verify POST /api/v1/synthea/load enforces hospital first, then practitioner prerequisites."""
    client = TestClient(app)
    patient_bundle = _load_json(CR_US_PATIENT_FILE)
    hosp_bundle = _load_json(HOSPITAL_FILE)

    # Case 1: Neither hospital nor practitioner info loaded
    resp = client.post("/api/v1/synthea/load", json=[patient_bundle])
    assert resp.status_code == 400
    assert "hospital resources must be sent first" in resp.json()["detail"].lower()

    # Case 2: Hospital loaded, but practitioner info missing
    hosp_resp = client.post("/api/v1/synthea/load", json=[hosp_bundle])
    assert hosp_resp.status_code == 200
    assert hosp_resp.json() == []

    resp2 = client.post("/api/v1/synthea/load", json=[patient_bundle])
    assert resp2.status_code == 400
    assert "practitioner resources must be sent first" in resp2.json()["detail"].lower()


def test_synthea_additive_lifecycle_and_get_endpoints():
    """Verify additive loading across multiple requests and querying via GET endpoints."""
    client = TestClient(app)

    hosp_bundle = _load_json(HOSPITAL_FILE)
    prac_bundle = _load_json(PRACTITIONER_FILE)
    dx_bundle = _load_json(DX_ONLY_PATIENT_FILE)
    cr_us_bundle = _load_json(CR_US_PATIENT_FILE)

    # Step 1: Load hospital and practitioner bundles first
    resp1 = client.post("/api/v1/synthea/load", json=[hosp_bundle, prac_bundle])
    assert resp1.status_code == 200
    assert resp1.json() == []

    # Verify GET /api/v1/synthea/hospitals and aliases
    hosp_resp = client.get("/api/v1/synthea/hospitals")
    assert hosp_resp.status_code == 200
    hospitals = hosp_resp.json()
    assert len(hospitals) > 0
    assert any(h.get("name") == "Fitchburg Outpatient Clinic" for h in hospitals)

    hosp_alias_resp = client.get("/api/v1/hospitals", params={"reference": "74ab949d-17ac-3309-83a0-13b4405c66aa"})
    assert hosp_alias_resp.status_code == 200
    assert len(hosp_alias_resp.json()) == 1
    assert hosp_alias_resp.json()[0]["name"] == "Fitchburg Outpatient Clinic"

    hosp_vi_resp = client.get("/api/vi/hospitals", params={"reference": "74ab949d-17ac-3309-83a0-13b4405c66aa"})
    assert hosp_vi_resp.status_code == 200
    assert len(hosp_vi_resp.json()) == 1

    # Verify GET /api/v1/synthea/practitioner
    prac_resp = client.get("/api/v1/synthea/practitioner", params={"reference": "9999984591"})
    assert prac_resp.status_code == 200
    practitioners = prac_resp.json()
    assert len(practitioners) == 1
    assert practitioners[0]["id"] == "ef3edc9b-f77c-37c1-922f-ce1c1a5fcf09"

    # Step 2: Load a patient bundle without supported modalities (DX only -> warning, returns [])
    resp2 = client.post("/api/v1/synthea/load", json=[dx_bundle])
    assert resp2.status_code == 200
    assert resp2.json() == []

    # Step 3: Incrementally load patient bundle with CR/US ImagingStudy resources
    resp3 = client.post("/api/v1/synthea/load", json=[cr_us_bundle])
    assert resp3.status_code == 200
    returned_bundles = resp3.json()
    assert len(returned_bundles) == 1
    assert returned_bundles[0]["resourceType"] == "Bundle"

    # Patient identifier inside returned parsed FhirBundle JSON
    patient_resource = next(
        e["resource"]
        for e in returned_bundles[0].get("entry", [])
        if e.get("resource", {}).get("resourceType") == "Patient"
    )
    assert patient_resource["id"] == "1bbc0b16-2965-fc1c-0a29-c8237663d154"

    # Verify DICOM files on disk and MWL entries coherence
    mwl_resp = client.get("/api/v1/mwl")
    assert mwl_resp.status_code == 200
    mwl_entries = mwl_resp.json()
    assert len(mwl_entries) == 7

    # Verify on-disk DICOM file generated
    first_entry = mwl_entries[0]
    expected_patient_id = first_entry["patient_id"]
    assert expected_patient_id == "S99916806"

    dcm_files = [os.path.join(r, f) for r, _, fs in os.walk(config.storage_dir) for f in fs if f.endswith(".dcm")]
    assert len(dcm_files) >= 1

    ds = pydicom.dcmread(dcm_files[0])
    assert str(ds.PatientID) == "S99916806"
    assert str(ds.PatientName) == "Hettinger594^Alden634^Frankie174^Mr.^JD"
    assert str(ds.InstitutionName) == "Fitchburg Outpatient Clinic"
    assert str(ds.ReferringPhysicianName) == "Reilly981^Ted955^^Dr."

    # Verify GET /api/v1/synthea/patient-bundle and alias
    bundle_resp = client.get("/api/v1/synthea/patient-bundle", params={"patient-id": "S99916806"})
    assert bundle_resp.status_code == 200
    bundle_json = bundle_resp.json()
    assert bundle_json["resourceType"] == "Bundle"

    alias_bundle_resp = client.get("/api/v1/syntha/patient-bundle?patient-id:S99916806")
    assert alias_bundle_resp.status_code == 200
    assert alias_bundle_resp.json()["resourceType"] == "Bundle"

    # Unknown patient-id returns 404
    not_found_resp = client.get("/api/v1/synthea/patient-bundle", params={"patient-id": "UNKNOWN-PATIENT"})
    assert not_found_resp.status_code == 404

    # Missing patient-id query param returns 400
    missing_param_resp = client.get("/api/v1/synthea/patient-bundle")
    assert missing_param_resp.status_code == 400

    # Verify Synthea patients, studies, and series endpoints
    patients_resp = client.get("/api/v1/synthea/patients")
    assert patients_resp.status_code == 200
    patients_json = patients_resp.json()
    assert len(patients_json) == 1
    assert patients_json[0]["patient_id"] == "S99916806"

    studies_resp = client.get("/api/v1/synthea/studies", params={"patient-id": "S99916806"})
    assert studies_resp.status_code == 200
    studies_json = studies_resp.json()
    assert len(studies_json) == 8

    series_resp = client.get("/api/v1/synthea/series", params={"modality": "US"})
    assert series_resp.status_code == 200
    series_json = series_resp.json()
    assert len(series_json) == 1
    us_study_uid = series_json[0]["study_instance_uid"]
    us_series_uid = series_json[0]["series_instance_uid"]

    # Verify DICOMweb QIDO-RS and WADO-RS endpoints find all 8 studies (7 CR + 1 US)
    qido_studies_resp = client.get("/dicomweb/studies", params={"PatientID": "S99916806"})
    assert qido_studies_resp.status_code == 200
    assert len(qido_studies_resp.json()) == 8

    qido_series_resp = client.get(f"/dicomweb/studies/{us_study_uid}/series")
    assert qido_series_resp.status_code == 200
    assert len(qido_series_resp.json()) == 1
    assert qido_series_resp.json()[0]["00080060"]["Value"][0] == "US"

    qido_inst_resp = client.get(f"/dicomweb/studies/{us_study_uid}/series/{us_series_uid}/instances")
    assert qido_inst_resp.status_code == 200
    assert len(qido_inst_resp.json()) >= 1

    wado_meta_resp = client.get(f"/dicomweb/studies/{us_study_uid}/metadata")
    assert wado_meta_resp.status_code == 200
    assert len(wado_meta_resp.json()) >= 1
    assert wado_meta_resp.json()[0]["00100020"]["Value"][0] == "S99916806"
