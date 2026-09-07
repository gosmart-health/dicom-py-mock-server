"""Unit and API tests for FHIR ServiceRequest bundle parsing and MWL integration."""

import pytest
from fastapi.testclient import TestClient

from dicom_py_mock_server.config import AppConfig
from dicom_py_mock_server.main import app
from dicom_py_mock_server.services.fhir_parser import FhirParserService
from dicom_py_mock_server.services.generator import DicomGeneratorService
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService

SAMPLE_FHIR_CT_BUNDLE = {
    "resourceType": "Bundle",
    "type": "collection",
    "entry": [
        {
            "fullUrl": "urn:uuid:patient-001",
            "resource": {
                "resourceType": "Patient",
                "id": "pat-12345",
                "identifier": [{"system": "http://hospital.org/mrn", "value": "MRN-FHIR-9988"}],
                "name": [
                    {
                        "use": "official",
                        "family": "WILLIAMS",
                        "given": ["SARAH", "JANE"],
                    }
                ],
                "gender": "female",
                "birthDate": "1982-06-15",
            },
        },
        {
            "fullUrl": "urn:uuid:practitioner-001",
            "resource": {
                "resourceType": "Practitioner",
                "id": "doc-678",
                "name": [{"family": "TAYLOR", "given": ["MICHAEL"]}],
            },
        },
        {
            "fullUrl": "urn:uuid:servicerequest-001",
            "resource": {
                "resourceType": "ServiceRequest",
                "id": "sr-ct-5566",
                "status": "active",
                "intent": "order",
                "identifier": [{"system": "http://hospital.org/accession", "value": "ACC-FHIR-CT-01"}],
                "code": {
                    "coding": [{"system": "http://loinc.org", "code": "24627-2", "display": "CT Chest with contrast"}],
                    "text": "CT Chest with IV contrast",
                },
                "subject": {"reference": "Patient/pat-12345"},
                "requester": {"reference": "Practitioner/doc-678"},
                "occurrenceDateTime": "2026-09-07T16:00:00",
                "reasonCode": [{"text": "Persistent cough evaluation"}],
            },
        },
    ],
}

SAMPLE_FHIR_MR_BUNDLE = {
    "resourceType": "Bundle",
    "type": "collection",
    "entry": [
        {
            "resource": {
                "resourceType": "Patient",
                "id": "pat-mr-99",
                "identifier": [{"value": "MRN-FHIR-MR-22"}],
                "name": [{"family": "MILLER", "given": ["DAVID"]}],
                "gender": "male",
                "birthDate": "1975-08-20",
            }
        },
        {
            "resource": {
                "resourceType": "ServiceRequest",
                "id": "sr-mr-7788",
                "status": "active",
                "intent": "order",
                "identifier": [{"value": "ACC-FHIR-MR-02"}],
                "code": {
                    "coding": [{"code": "MR-BRAIN", "display": "MR Brain without contrast"}],
                    "text": "MR Brain without contrast",
                },
                "subject": {"reference": "Patient/pat-mr-99"},
                "occurrenceDateTime": "2026-09-07T17:30:00",
            }
        },
    ],
}

SAMPLE_FHIR_UNSUPPORTED_MODALITY_BUNDLE = {
    "resourceType": "Bundle",
    "type": "collection",
    "entry": [
        {
            "resource": {
                "resourceType": "Patient",
                "id": "pat-pet",
                "identifier": [{"value": "MRN-PET-99"}],
                "name": [{"family": "GREEN", "given": ["LISA"]}],
            }
        },
        {
            "resource": {
                "resourceType": "ServiceRequest",
                "id": "sr-pet-11",
                "status": "active",
                "intent": "order",
                "identifier": [{"value": "ACC-PET-09"}],
                "code": {
                    "coding": [{"code": "PET-BODY", "display": "PET SCAN BODY"}],
                    "text": "PET whole body scan",
                },
                "subject": {"reference": "Patient/pat-pet"},
            }
        },
    ],
}

SAMPLE_FHIR_CANCEL_BUNDLE = {
    "resourceType": "Bundle",
    "type": "collection",
    "entry": [
        {
            "resource": {
                "resourceType": "ServiceRequest",
                "id": "sr-ct-5566",
                "status": "revoked",
                "identifier": [{"value": "ACC-FHIR-CT-01"}],
                "subject": {"reference": "Patient/pat-12345"},
            }
        }
    ],
}


@pytest.fixture
def test_config():
    return AppConfig(templates_path="./templates", mwl_window_hr=24)


@pytest.fixture
def test_mwl_service(test_config):
    return MwlGeneratorService(app_config=test_config)


@pytest.fixture
def fhir_parser(test_mwl_service):
    return FhirParserService(mwl_service=test_mwl_service)


def test_fhir_parser_creates_ct_mwl(fhir_parser, test_mwl_service):
    """Verify FHIR ServiceRequest bundle creates MWL entry with exact demographics."""
    result = fhir_parser.process_bundle(SAMPLE_FHIR_CT_BUNDLE)

    assert result["status"] == "success"
    assert len(result["entries_created"]) == 1

    matched = test_mwl_service.find_entries(accession="ACC-FHIR-CT-01")
    assert len(matched) == 1
    entry = matched[0]

    # Verify demographics are untouched
    assert entry["patient_name"] == "WILLIAMS^SARAH^JANE"
    assert entry["patient_id"] == "MRN-FHIR-9988"
    assert entry["accession"] == "ACC-FHIR-CT-01"
    assert entry["modality"] == "CT"
    assert entry["referring_physician"] == "TAYLOR^MICHAEL"


def test_fhir_parser_creates_mr_mwl(fhir_parser, test_mwl_service):
    """Verify MR ServiceRequest bundle creates MR MWL entry from templates/sample_mr."""
    result = fhir_parser.process_bundle(SAMPLE_FHIR_MR_BUNDLE)

    assert result["status"] == "success"
    matched = test_mwl_service.find_entries(accession="ACC-FHIR-MR-02")
    assert len(matched) == 1
    assert matched[0]["modality"] == "MR"
    assert matched[0]["patient_name"] == "MILLER^DAVID"


def test_fhir_parser_rejects_unsupported_modality(fhir_parser, test_mwl_service):
    """Verify bundle requesting modality with no template images is rejected."""
    result = fhir_parser.process_bundle(SAMPLE_FHIR_UNSUPPORTED_MODALITY_BUNDLE)

    assert result["status"] == "rejected"
    assert len(result["rejections"]) == 1
    assert "No template images available for modality 'PET'" in result["rejections"][0]["error"]

    matched = test_mwl_service.find_entries(accession="ACC-PET-09")
    assert len(matched) == 0


def test_fhir_parser_cancellation(fhir_parser, test_mwl_service):
    """Verify status='revoked' removes active MWL entry."""
    # 1. Ingest order
    fhir_parser.process_bundle(SAMPLE_FHIR_CT_BUNDLE)
    assert len(test_mwl_service.find_entries(accession="ACC-FHIR-CT-01")) == 1

    # 2. Cancel order
    result = fhir_parser.process_bundle(SAMPLE_FHIR_CANCEL_BUNDLE)
    assert result["entries_removed"] >= 1

    # 3. Verify removed
    assert len(test_mwl_service.find_entries(accession="ACC-FHIR-CT-01")) == 0


def test_fhir_downstream_dicom_generation(fhir_parser, test_mwl_service):
    """Verify downstream DICOM creation from FHIR-derived MWL entry."""
    fhir_parser.process_bundle(SAMPLE_FHIR_CT_BUNDLE)
    matched = test_mwl_service.find_entries(accession="ACC-FHIR-CT-01")
    assert len(matched) == 1

    instances = DicomGeneratorService.create_instances_from_mwl(matched[0], num_instances=2)
    assert len(instances) == 2
    for ds in instances:
        assert str(ds.PatientName) == "WILLIAMS^SARAH^JANE"
        assert str(ds.PatientID) == "MRN-FHIR-9988"
        assert str(ds.AccessionNumber) == "ACC-FHIR-CT-01"


def test_fhir_api_endpoints():
    """Verify REST POST endpoints for FHIR bundles."""
    client = TestClient(app)

    # Primary endpoint
    res1 = client.post("/api/v1/fhir_service_request", json=SAMPLE_FHIR_CT_BUNDLE)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "success"
    assert len(data1["entries_created"]) == 1

    # Semantic alias endpoint
    res2 = client.post("/api/v1/fhir/Bundle", json=SAMPLE_FHIR_MR_BUNDLE)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "success"

    # Unsupported modality returns HTTP 422
    res3 = client.post("/api/v1/fhir_service_request", json=SAMPLE_FHIR_UNSUPPORTED_MODALITY_BUNDLE)
    assert res3.status_code == 422
