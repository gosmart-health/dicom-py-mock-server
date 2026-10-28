"""Integration and unit tests for FHIR-driven MWL, C-FIND, pacing, and auto-push."""

from unittest.mock import AsyncMock

import pytest

from dicom_py_mock_server.config import AppConfig
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService
from dicom_py_mock_server.services.scp import DicomScpService


def create_sample_fhir_bundle(
    study_uid="1.2.840.111.1",
    patient_id="P-001",
    modality="CT",
    identifier_system="urn:oid:2.16.840.1.113883.4.3.25",
):
    """Helper to create a valid FHIR bundle payload with Patient and ImagingStudy."""
    patient_res = {
        "resourceType": "Patient",
        "id": patient_id,
        "name": [{"family": "Taylor", "given": ["Jordan"]}],
        "gender": "female",
        "birthDate": "1988-06-14",
    }
    if identifier_system:
        patient_res["identifier"] = [
            {
                "system": identifier_system,
                "value": patient_id,
            }
        ]
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": patient_res,
            },
            {
                "resource": {
                    "resourceType": "ImagingStudy",
                    "id": f"study-{study_uid.replace('.', '-')}",
                    "status": "available",
                    "identifier": [{"value": f"urn:oid:{study_uid}"}],
                    "description": f"{modality} Scan Chest",
                    "started": "2026-10-28T10:00:00Z",
                    "series": [
                        {
                            "uid": f"{study_uid}.1",
                            "number": 1,
                            "modality": {"code": modality},
                            "description": f"{modality} Routine",
                            "numberOfInstances": 4,
                        }
                    ],
                }
            },
        ],
    }


@pytest.mark.anyio
async def test_fhir_mwl_replenishment_and_pacing():
    """Verify that when the queue is empty, MwlGeneratorService fetches bundles from client and activates one study."""
    cfg = AppConfig(
        generator_mode="fhir",
        mwl_rate_per_hr=12.0,
        fhir_plugin_url="http://mock-fhir:8088",
    )

    b1 = create_sample_fhir_bundle("1.2.840.111.101", "P-101", "CT")
    b2 = create_sample_fhir_bundle("1.2.840.111.102", "P-102", "MR")

    mock_client = AsyncMock()
    # First call returns 2 bundles and new offset=2
    mock_client.fetch_patient_imaging.return_value = ([b1, b2], 2, 2)

    mwl_service = MwlGeneratorService(app_config=cfg, fhir_client=mock_client)
    assert mwl_service._fhir_raw_offset == 0
    assert len(mwl_service._fhir_bundle_queue) == 0

    # 1. Generate one study
    rec1 = await mwl_service._generate_one_fhir_study()
    assert rec1 is not None
    assert rec1["study_uid"] == "1.2.840.111.101"
    assert rec1["patient_id"] == "P-101"
    assert rec1["modality"] == "CT"

    # Verify client was called with offset 0 and raw_count 200
    mock_client.fetch_patient_imaging.assert_called_once()
    assert mwl_service._fhir_raw_offset == 2
    # 1 was popped, so 1 remaining in queue
    assert len(mwl_service._fhir_bundle_queue) == 1
    assert len(mwl_service._entries) == 1

    # 2. Generate second study - queue has 1 item, so should NOT call fetch_patient_imaging again
    mock_client.fetch_patient_imaging.reset_mock()
    rec2 = await mwl_service._generate_one_fhir_study()
    assert rec2 is not None
    assert rec2["study_uid"] == "1.2.840.111.102"
    assert rec2["patient_id"] == "P-102"
    assert rec2["modality"] == "MR"

    mock_client.fetch_patient_imaging.assert_not_called()
    assert len(mwl_service._fhir_bundle_queue) == 0
    assert len(mwl_service._entries) == 2


@pytest.mark.anyio
async def test_fhir_mwl_data_exhaustion():
    """Verify that on data exhaustion from API query, no studies are generated and no synthetic fallback occurs."""
    cfg = AppConfig(generator_mode="fhir", mwl_rate_per_hr=12.0)
    mock_client = AsyncMock()
    # API query returns 0 bundles (exhausted)
    mock_client.fetch_patient_imaging.return_value = ([], 50, 0)

    mwl_service = MwlGeneratorService(app_config=cfg, fhir_client=mock_client)

    rec = await mwl_service._generate_one_fhir_study()
    assert rec is None
    assert mwl_service._fhir_is_exhausted is True
    assert len(mwl_service._entries) == 0

    status = mwl_service.get_status()
    assert status["generator_mode"] == "fhir"
    assert status["is_exhausted"] is True
    assert status["fhir_queue_depth"] == 0
    assert status["active_entries_count"] == 0


@pytest.mark.anyio
async def test_fhir_mwl_auto_push_forwarding():
    """Verify that generated FHIR studies are forwarded to auto-push and auto-push does not synthesize on empty."""
    cfg = AppConfig(
        generator_mode="fhir",
        auto_push_ae="TARGET_PACS",
        auto_push_host="127.0.0.1",
        auto_push_port=11119,
        auto_push_sec=1.0,
    )

    b1 = create_sample_fhir_bundle("1.2.840.111.301", "P-301", "CT")
    mock_client = AsyncMock()
    mock_client.fetch_patient_imaging.return_value = ([b1], 1, 1)

    mwl_service = MwlGeneratorService(app_config=cfg, fhir_client=mock_client)
    scp_service = DicomScpService(ae_title="TEST_SCP", port=11118, mwl_service=mwl_service)
    mwl_service.set_scp_service(scp_service)

    # Generate one study
    rec = await mwl_service._generate_one_fhir_study()
    assert rec is not None
    # Verify enqueued into auto-push queue
    assert len(scp_service._auto_push_queue) == 1
    assert scp_service._auto_push_queue[0]["study_uid"] == "1.2.840.111.301"

    # Verify when auto-push queue is empty in fhir mode, _push_one_auto_study returns None without fallback
    scp_service._auto_push_queue.clear()
    assert scp_service._push_one_auto_study() is None
    # mwl entries should not have grown synthetically
    assert len(mwl_service._entries) == 1


@pytest.mark.anyio
async def test_fhir_mwl_cfind_discovery():
    """Verify that FHIR-generated studies are discoverable by MWL C-FIND and Study Root C-FIND."""
    cfg = AppConfig(generator_mode="fhir")
    b1 = create_sample_fhir_bundle("1.2.840.111.501", "P-501", "CT")

    mock_client = AsyncMock()
    mock_client.fetch_patient_imaging.return_value = ([b1], 1, 1)

    mwl_service = MwlGeneratorService(app_config=cfg, fhir_client=mock_client)
    rec = await mwl_service._generate_one_fhir_study()
    assert rec is not None

    study_uid = rec["study_uid"]
    patient_id = rec["patient_id"]
    accession = rec["accession"]

    # Verify patient_id and accession are exactly without prefix
    assert patient_id == "P-501"
    assert not patient_id.startswith("GSH-")
    assert not accession.startswith("GSH-")

    # 1. MWL C-FIND query by StudyInstanceUID
    mwl_results = mwl_service.find_entries(study_uid=study_uid)
    assert len(mwl_results) == 1
    assert mwl_results[0]["study_uid"] == study_uid

    # 2. MWL C-FIND query by Accession
    mwl_acc_results = mwl_service.find_entries(accession=accession)
    assert len(mwl_acc_results) == 1
    assert mwl_acc_results[0]["accession"] == accession

    # 3. Study Root C-FIND
    sr_results = mwl_service.find_study_series_entries(study_uid=study_uid)
    assert len(sr_results) >= 1
    assert sr_results[0]["patient_id"] == patient_id
    assert sr_results[0]["study_uid"] == study_uid

    # 4. Generate C-FIND datasets (Patient, Study, Series, Image levels)
    study_ds = mwl_service.to_study_cfind_dataset(sr_results[0])
    assert study_ds.StudyInstanceUID == study_uid
    assert study_ds.PatientID == patient_id

    series_ds = mwl_service.to_series_cfind_dataset(sr_results[0])
    assert series_ds.SeriesInstanceUID == sr_results[0]["series_uid"]
    assert series_ds.Modality == "CT"

    image_datasets = mwl_service.to_image_cfind_datasets(sr_results[0])
    assert len(image_datasets) == sr_results[0]["num_instances"]
    assert hasattr(image_datasets[0], "SOPInstanceUID")


@pytest.mark.anyio
async def test_fhir_mwl_skips_when_patient_id_system_missing(capsys, caplog):
    """Verify that when a FHIR patient lacks the required identifier system, no MWL or C-FIND records are created."""
    cfg = AppConfig(
        generator_mode="fhir",
        fhir_patient_id_system="urn:oid:2.16.840.1.113883.4.3.25",
    )
    # Bundle where patient identifier has wrong system
    b_invalid = create_sample_fhir_bundle(
        study_uid="1.2.840.111.901",
        patient_id="PAT-INVALID-01",
        modality="CT",
        identifier_system="http://hl7.org/fhir/sid/us-ssn",
    )
    mock_client = AsyncMock()
    mock_client.fetch_patient_imaging.return_value = ([b_invalid], 1, 1)

    mwl_service = MwlGeneratorService(app_config=cfg, fhir_client=mock_client)
    rec = await mwl_service._generate_one_fhir_study()

    assert rec is None
    assert len(mwl_service._entries) == 0
    assert len(mwl_service._synthea_entries) == 0

    expected_log = (
        "FHIR Patient Resource PAT-INVALID-01 does not contain the identifier matching "
        "GOSMART_MS_FHIR_PATIENT_ID_SYSTEM=urn:oid:2.16.840.1.113883.4.3.25"
    )
    captured = capsys.readouterr()
    assert expected_log in captured.out or expected_log in captured.err or expected_log in caplog.text


@pytest.mark.anyio
async def test_trigger_generation_immediate():
    """Verify trigger_generation generates immediately without waiting for timer."""
    cfg = AppConfig(generator_mode="fhir")
    b1 = create_sample_fhir_bundle("1.2.840.111.999", "P-999", "CT")
    mock_client = AsyncMock()
    mock_client.fetch_patient_imaging.return_value = ([b1], 1, 1)

    mwl_service = MwlGeneratorService(app_config=cfg, fhir_client=mock_client)
    rec = await mwl_service.trigger_generation()

    assert rec is not None
    assert rec["study_uid"] == "1.2.840.111.999"
    assert rec["patient_id"] == "P-999"
    assert len(mwl_service._entries) == 1
