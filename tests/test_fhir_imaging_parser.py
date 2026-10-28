"""Unit tests for FhirImagingParser and clean_dicom_uid."""

from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.imagingstudy import ImagingStudy
from fhir.resources.R4B.patient import Patient

from dicom_py_mock_server.config import config
from dicom_py_mock_server.services.fhir_imaging_parser import FhirImagingParser, clean_dicom_uid


def test_clean_dicom_uid():
    """Verify clean_dicom_uid strips urn:oid: and urn:uuid: prefixes correctly."""
    assert clean_dicom_uid("urn:oid:1.2.840.10008.1.2") == "1.2.840.10008.1.2"
    assert clean_dicom_uid("urn:uuid:6ba7b810-9dad-11d1-80b4-00c04fd430c8") == "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
    assert clean_dicom_uid("1.2.840.10008.1.2") == "1.2.840.10008.1.2"
    assert clean_dicom_uid(None) is None
    assert clean_dicom_uid("") is None


def test_extract_patient_demographics():
    """Verify extraction of DICOM PN and ID formats with prefixes and suffixes."""
    parser = FhirImagingParser()
    patient = Patient.model_validate(
        {
            "resourceType": "Patient",
            "id": "pat-12345",
            "identifier": [{"value": "ID-9999"}],
            "name": [{"family": "Smith", "given": ["Alice"]}],
            "gender": "female",
            "birthDate": "1985-04-12",
        }
    )

    demo = parser.extract_patient_demographics(patient)
    assert demo["patient_id"] == f"{config.id_prefix}ID-9999"
    assert demo["patient_name"].startswith(f"Smith{config.patient_suffix}")
    assert demo["dob"] == "19850412"
    assert demo["sex"] == "F"


def test_parse_bundle_to_custom_entries():
    """Verify parsing a FHIR bundle containing Patient and multi-series ImagingStudy."""
    patient = Patient.model_validate(
        {
            "resourceType": "Patient",
            "id": "pat-ct-01",
            "name": [{"family": "Johnson", "given": ["Bob"]}],
            "gender": "male",
            "birthDate": "1972-11-20",
        }
    )

    study = ImagingStudy.model_validate(
        {
            "resourceType": "ImagingStudy",
            "id": "study-ct-01",
            "status": "available",
            "subject": {"reference": "Patient/pat-ct-01"},
            "identifier": [{"value": "urn:oid:1.2.840.999.1.1"}],
            "description": "Chest CT Scan with Contrast",
            "started": "2026-10-28T09:30:00Z",
            "series": [
                {
                    "uid": "1.2.840.999.1.1.1",
                    "number": 1,
                    "modality": {"code": "CT"},
                    "description": "Scout",
                    "numberOfInstances": 2,
                },
                {
                    "uid": "1.2.840.999.1.1.2",
                    "number": 2,
                    "modality": {"code": "CT"},
                    "description": "Axial 5mm",
                    "numberOfInstances": 48,
                },
            ],
        }
    )

    bundle = Bundle.model_validate(
        {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {"resource": patient.model_dump()},
                {"resource": study.model_dump()},
            ],
        }
    )

    parser = FhirImagingParser()
    entries = parser.parse_bundle_to_custom_entries(bundle)

    assert len(entries) == 2
    e1, e2 = entries[0], entries[1]

    # Check first series
    assert e1["patient_id"] == f"{config.id_prefix}pat-ct-01"
    assert e1["patient_name"].startswith(f"Johnson{config.patient_suffix}")
    assert e1["dob"] == "19721120"
    assert e1["sex"] == "M"
    assert e1["study_uid"] == "1.2.840.999.1.1"
    assert e1["series_uid"] == "1.2.840.999.1.1.1"
    assert e1["modality"] == "CT"
    assert e1["series_number"] == 1
    assert e1["series_description"] == "Scout"
    assert e1["num_instances"] == 2
    assert e1["studyDate"] == "20261028"
    assert e1["studyTime"] == "093000"

    # Check second series
    assert e2["series_uid"] == "1.2.840.999.1.1.2"
    assert e2["series_number"] == 2
    assert e2["series_description"] == "Axial 5mm"
    assert e2["num_instances"] == 48


def test_parse_bundle_dict_payload():
    """Verify parsing when payload is passed directly as a raw dict with urn prefixes."""
    payload = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-us-02",
                    "name": [{"family": "Williams", "given": ["Clara"]}],
                    "gender": "female",
                    "birthDate": "1990-01-15",
                }
            },
            {
                "resource": {
                    "resourceType": "ImagingStudy",
                    "id": "study-us-02",
                    "status": "available",
                    "identifier": [{"value": "urn:oid:1.2.840.777.2"}],
                    "started": "2026-10-28T14:15:22Z",
                    "series": [
                        {
                            "uid": "urn:oid:1.2.840.777.2.1",
                            "number": 1,
                            "modality": {"code": "US"},
                            "description": "Pelvic Ultrasound",
                            "numberOfInstances": 12,
                        }
                    ],
                }
            },
        ],
    }

    parser = FhirImagingParser()
    entries = parser.parse_bundle_to_custom_entries(payload)

    assert len(entries) == 1
    assert entries[0]["modality"] == "US"
    assert entries[0]["sex"] == "F"
    assert entries[0]["study_uid"] == "1.2.840.777.2"
    assert entries[0]["series_uid"] == "1.2.840.777.2.1"
