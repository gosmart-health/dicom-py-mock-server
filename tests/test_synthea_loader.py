"""Unit and integration tests for the Synthea loader CLI utility."""

import json
from unittest.mock import MagicMock, patch

import pytest

from util.synthea_loader import load, main

SAMPLE_HOSPITAL_BUNDLE = {
    "resourceType": "Bundle",
    "type": "collection",
    "entry": [
        {
            "fullUrl": "urn:uuid:74ab949d-17ac-3309-83a0-13b4405c66aa",
            "resource": {
                "resourceType": "Organization",
                "id": "74ab949d-17ac-3309-83a0-13b4405c66aa",
                "name": "Community Health Center",
            },
        }
    ],
}

SAMPLE_PRACTITIONER_BUNDLE = {
    "resourceType": "Bundle",
    "type": "collection",
    "entry": [
        {
            "fullUrl": "urn:uuid:ef3edc9b-f77c-37c1-922f-ce1c1a5fcf09",
            "resource": {
                "resourceType": "Practitioner",
                "id": "ef3edc9b-f77c-37c1-922f-ce1c1a5fcf09",
                "name": [{"family": "Smith", "given": ["Jane"], "prefix": ["Dr."]}],
            },
        }
    ],
}

SAMPLE_PATIENT_BUNDLE = {
    "resourceType": "Bundle",
    "type": "collection",
    "entry": [
        {
            "fullUrl": "urn:uuid:1bbc0b16-2965-fc1c-0a29-c8237663d154",
            "resource": {
                "resourceType": "Patient",
                "id": "1bbc0b16-2965-fc1c-0a29-c8237663d154",
                "name": [{"family": "Doe", "given": ["John"]}],
                "gender": "male",
                "birthDate": "1980-01-01",
            },
        }
    ],
}


def test_main_missing_folder():
    """Verify CLI exits with non-zero code when --folder is omitted."""
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0


def test_main_invokes_load(tmp_path):
    """Verify main correctly parses --folder and --url flags and invokes load."""
    folder = tmp_path / "fhir_files"
    folder.mkdir()

    with patch("util.synthea_loader.load", return_value=True) as mock_load:
        code = main(["--folder", str(folder), "--url", "http://localhost:9000"])
        assert code == 0
        mock_load.assert_called_once_with(bundle_folder=str(folder), url="http://localhost:9000", chunk_size=25)


def test_load_nonexistent_folder(capsys):
    """Verify load reports error and returns False if bundle_folder does not exist."""
    result = load("/nonexistent/directory/path/12345")
    assert result is False
    captured = capsys.readouterr()
    assert "does not exist" in captured.err.lower()


def test_load_file_instead_of_directory(tmp_path, capsys):
    """Verify load reports error and returns False if bundle_folder is a file."""
    test_file = tmp_path / "not_a_dir.txt"
    test_file.write_text("hello", encoding="utf-8")

    result = load(str(test_file))
    assert result is False
    captured = capsys.readouterr()
    assert "not a directory" in captured.err.lower()


def test_load_filtering_and_corrupted_json(tmp_path, capsys):
    """Verify load ignores non-.js files, catches malformed JSON, and reports error."""
    # File without .js in name
    (tmp_path / "readme.txt").write_text("some info", encoding="utf-8")
    # File with .js in name but invalid JSON
    (tmp_path / "broken.json").write_text("{invalid json", encoding="utf-8")

    result = load(str(tmp_path), url="http://127.0.0.1:8000")
    # Returns False because of parse error
    assert result is False
    captured = capsys.readouterr()
    assert "failed to read/parse json from 'broken.json'" in captured.err.lower()


def test_load_with_mocked_live_server(tmp_path):
    """Verify successful upload flow against a live server endpoint."""
    (tmp_path / "hospitalInformation123.json").write_text(json.dumps(SAMPLE_HOSPITAL_BUNDLE), encoding="utf-8")
    (tmp_path / "practitionerInformation123.json").write_text(json.dumps(SAMPLE_PRACTITIONER_BUNDLE), encoding="utf-8")
    (tmp_path / "patient_bundle.json").write_text(json.dumps(SAMPLE_PATIENT_BUNDLE), encoding="utf-8")

    mock_health = MagicMock(status_code=200)
    mock_post_hosp = MagicMock(status_code=200)
    mock_post_patient = MagicMock(status_code=200)
    mock_post_patient.json.return_value = [{"resourceType": "Bundle"}]

    mock_client = MagicMock()
    mock_client.post.side_effect = [mock_post_hosp, mock_post_patient]

    with (
        patch("httpx.get", return_value=mock_health),
        patch("httpx.Client", return_value=mock_client),
    ):
        success = load(str(tmp_path), url="http://127.0.0.1:8000")
        assert success is True
        assert mock_client.post.call_count == 2


def test_load_chunks_patient_bundles(tmp_path):
    """Verify patients are chunked into requests of chunk_size (e.g. 25)."""
    (tmp_path / "hospitalInformation123.json").write_text(json.dumps(SAMPLE_HOSPITAL_BUNDLE), encoding="utf-8")
    (tmp_path / "practitionerInformation123.json").write_text(json.dumps(SAMPLE_PRACTITIONER_BUNDLE), encoding="utf-8")

    # Create 60 patient bundle files
    for idx in range(60):
        (tmp_path / f"patient_{idx:03d}.json").write_text(json.dumps(SAMPLE_PATIENT_BUNDLE), encoding="utf-8")

    mock_health = MagicMock(status_code=200)
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = [{"resourceType": "Bundle"}]

    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp

    with (
        patch("httpx.get", return_value=mock_health),
        patch("httpx.Client", return_value=mock_client),
    ):
        success = load(str(tmp_path), url="http://127.0.0.1:8000", chunk_size=25)
        assert success is True
        # 1 call for resources + 3 calls for 60 patients (25 + 25 + 10) = 4 calls
        assert mock_client.post.call_count == 4

        # Verify sizes of each chunk passed in json=...
        calls = mock_client.post.call_args_list
        assert len(calls[0].kwargs["json"]) == 2  # resources
        assert len(calls[1].kwargs["json"]) == 25  # chunk 1
        assert len(calls[2].kwargs["json"]) == 25  # chunk 2
        assert len(calls[3].kwargs["json"]) == 10  # chunk 3


def test_load_with_testclient_fallback(tmp_path):
    """Verify fallback to TestClient(app) when live server is unreachable."""
    (tmp_path / "hospitalInformation123.json").write_text(json.dumps(SAMPLE_HOSPITAL_BUNDLE), encoding="utf-8")
    (tmp_path / "practitionerInformation123.json").write_text(json.dumps(SAMPLE_PRACTITIONER_BUNDLE), encoding="utf-8")
    (tmp_path / "patient_bundle.json").write_text(json.dumps(SAMPLE_PATIENT_BUNDLE), encoding="utf-8")

    with (
        patch("httpx.get", side_effect=Exception("Connection refused")),
        patch("dicom_py_mock_server.main.app", MagicMock()),
    ):
        # Mock client inside TestClient
        mock_test_client = MagicMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = []
        mock_test_client.post.return_value = mock_resp

        with patch("util.synthea_loader.TestClient", return_value=mock_test_client):
            success = load(str(tmp_path), url="http://127.0.0.1:8000")
            assert success is True
            assert mock_test_client.post.call_count == 2


def test_load_real_synthea_bundles_in_process(tmp_path, monkeypatch):
    """Verify real Synthea bundles load through in-process TestClient end-to-end."""
    import shutil
    from pathlib import Path

    from dicom_py_mock_server.api.fhir_routes import synthea_utils
    from dicom_py_mock_server.api.routes import mwl_service
    from dicom_py_mock_server.config import config

    monkeypatch.setattr(config, "storage_dir", str(tmp_path / "storage"))
    synthea_utils._hospital_bundles = None
    synthea_utils._practitioner_bundles = None
    synthea_utils._patient_bundles = None
    mwl_service._entries.clear()

    fhir_src = Path("tests/synthea/fhir")
    test_dir = tmp_path / "fhir_input"
    test_dir.mkdir()

    # Copy hospital, practitioner, and 1 patient file
    hosp_file = next(fhir_src.glob("hospitalInformation*.json"))
    prac_file = next(fhir_src.glob("practitionerInformation*.json"))
    patient_file = fhir_src / "Antone63_Schmeler639_e0dc8582-54f5-4627-7ce8-3c9d3bb90b36.json"

    shutil.copy(hosp_file, test_dir / hosp_file.name)
    shutil.copy(prac_file, test_dir / prac_file.name)
    shutil.copy(patient_file, test_dir / patient_file.name)

    # Force fallback to TestClient by pointing to a dead port
    success = load(str(test_dir), url="http://127.0.0.1:59999")
    assert success is True
