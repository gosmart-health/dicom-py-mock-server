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
    assert "auto_push_ae" in data
    assert "auto_push_host" in data
    assert "auto_push_port" in data
    assert "auto_push_sec" in data
    assert "is_auto_pushing" in data


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
    assert "CT" in data["template_modalities"]
    assert "MR" in data["template_modalities"]


def test_mwl_generate_endpoint():
    payload = {
        "patientName": "MWL^API^TEST",
        "patientId": "MWL-PAT-999",
        "modality": "CT",
    }
    response = client.post("/api/v1/mwl/generate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["patient_id"] == "MWL-PAT-999"
    assert data["modality"] == "CT"

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


def test_move_api_endpoint():
    from tests.test_cmove_workflow import MockStorageScp

    viewer_port = 11135
    viewer = MockStorageScp(ae_title="API_MOVE_VIEWER", port=viewer_port)
    viewer.start()
    try:
        # Move by patient_id
        payload = {
            "patient_id": "API-MOVE-PAT-001",
            "target_ae_title": "API_MOVE_VIEWER",
            "target_host": "127.0.0.1",
            "target_port": viewer_port,
        }
        res = client.post("/api/v1/move", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["instances_sent"] >= 8
        assert data["patient_id"] == "API-MOVE-PAT-001"
        assert data["target_ae_title"] == "API_MOVE_VIEWER"

        # Move by accession
        payload_acc = {
            "accession": "API-MOVE-ACC-888",
            "target_ae_title": "API_MOVE_VIEWER",
            "target_host": "127.0.0.1",
            "target_port": viewer_port,
        }
        res_acc = client.post("/api/v1/scp/move", json=payload_acc)
        assert res_acc.status_code == 200
        data_acc = res_acc.json()
        assert data_acc["success"] is True
        assert data_acc["instances_sent"] >= 8
        assert data_acc["accession"] == "API-MOVE-ACC-888"
    finally:
        viewer.stop()


def test_auto_push_api_endpoint():
    """Test POST and GET /api/v1/scp/auto-push endpoints with target AE schema."""
    # 1. Configure auto-push with target AE schema
    payload = {
        "intervalSec": 45,
        "targetAeTitle": "VIEWER_AUTO_PUSH",
        "targetHost": "192.168.1.55",
        "targetPort": 11119,
    }
    res = client.post("/api/v1/scp/auto-push", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["targetAeTitle"] == "VIEWER_AUTO_PUSH"
    assert data["targetHost"] == "192.168.1.55"
    assert data["targetPort"] == 11119
    assert data["intervalSec"] == 45.0
    assert data["is_auto_pushing"] is True

    # 2. Query status via GET
    get_res = client.get("/api/v1/scp/auto-push")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["targetAeTitle"] == "VIEWER_AUTO_PUSH"
    assert get_data["targetHost"] == "192.168.1.55"
    assert get_data["targetPort"] == 11119
    assert get_data["intervalSec"] == 45.0
    assert get_data["is_auto_pushing"] is True

    # 3. Disable auto-push with intervalSec = 0
    disable_payload = {
        "intervalSec": 0,
        "targetAeTitle": "VIEWER_AUTO_PUSH",
        "targetHost": "192.168.1.55",
        "targetPort": 11119,
    }
    dis_res = client.post("/api/v1/scp/auto-push", json=disable_payload)
    assert dis_res.status_code == 200
    dis_data = dis_res.json()
    assert dis_data["success"] is True
    assert dis_data["intervalSec"] == 0.0
    assert dis_data["is_auto_pushing"] is False

    # Verify status reflects disabled and holds target info
    status_res = client.get("/api/v1/scp/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["is_auto_pushing"] is False
    assert status_data["auto_push_ae"] == "VIEWER_AUTO_PUSH"
    assert status_data["auto_push_host"] == "192.168.1.55"
    assert status_data["auto_push_port"] == 11119
