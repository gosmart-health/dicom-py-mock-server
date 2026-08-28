"""Tests for FastAPI endpoints."""

from fastapi.testclient import TestClient

from dicom_py_mock_server.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "DICOM Mock Server" in data["app"]


def test_scp_status_endpoint():
    response = client.get("/api/v1/scp/status")
    assert response.status_code == 200
    data = response.json()
    assert "ae_title" in data
    assert "port" in data
    assert "is_running" in data


def test_generate_endpoint(tmp_path):
    from dicom_py_mock_server.config import config
    config.storage_dir = str(tmp_path)

    payload = {
        "patient": {"patient_id": "API-PATIENT-001", "patient_name": "API^Test"},
        "study": {"study_description": "API Integration Test"},
        "series": {"modality": "CT"},
        "num_instances": 1,
        "rows": 32,
        "columns": 32,
    }

    response = client.post("/api/v1/generate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["patient_id"] == "API-PATIENT-001"
    assert data["generated_instances"] == 1
    assert len(data["file_paths"]) == 1


def test_generate_raw_endpoint(tmp_path):
    from dicom_py_mock_server.config import config
    config.storage_dir = str(tmp_path)

    payload = {
        "patient_name": "BURNED^RAW^PATIENT",
        "patient_id": "RAW-API-101",
        "study_date": "20260828",
        "study_time": "150000",
        "image_number": 3,
        "rows": 512,
        "columns": 512,
        "transfer_syntax": "RAW",
    }

    response = client.post("/api/v1/generate/raw", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["patient_id"] == "RAW-API-101"
    assert data["generated_instances"] == 1
    assert len(data["file_paths"]) == 1


def test_mwl_status_endpoint():
    response = client.get("/api/v1/mwl/status")
    assert response.status_code == 200
    data = response.json()
    assert "active_entries_count" in data
    assert "window_hr" in data
    assert data["window_hr"] == 24
    assert "base_rate_per_hr" in data
    assert "current_rate_per_hr" in data
    assert "template_modalities" in data


def test_mwl_generate_endpoint():
    payload = {
        "patientName": "MWL^API^TEST",
        "patientId": "MWL-PAT-999",
        "modality": "US",
    }
    response = client.post("/api/v1/mwl/generate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["patient_id"] == "MWL-PAT-999"
    assert data["modality"] == "US"

    # Verify listing
    res_list = client.get("/api/v1/mwl")
    assert res_list.status_code == 200
    entries = res_list.json()
    assert len(entries) >= 1
    assert any(e["patient_id"] == "MWL-PAT-999" for e in entries)


def test_mwl_start_stop_endpoints():
    res_start = client.post("/api/v1/mwl/start")
    assert res_start.status_code == 200
    data_start = res_start.json()
    assert "is_auto_generating" in data_start

    res_stop = client.post("/api/v1/mwl/stop")
    assert res_stop.status_code == 200
    data_stop = res_stop.json()
    assert data_stop["is_auto_generating"] is False


