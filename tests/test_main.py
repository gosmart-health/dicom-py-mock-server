from fastapi.testclient import TestClient
from pynetdicom import AE
from pynetdicom.sop_class import Verification

from dicom_py_mock_server.config import config
from dicom_py_mock_server.main import app


def test_app_title():
    assert app.title == "DICOM Mock Server"


def test_app_lifespan_starts_scp_and_seeds_mock_studies():
    """Verify that starting the app starts DICOM SCP and seeds/generates mock studies."""
    with TestClient(app) as client:
        # Check SCP status endpoint
        res_scp = client.get("/api/v1/scp/status")
        assert res_scp.status_code == 200
        scp_data = res_scp.json()
        assert scp_data["is_running"] is True
        assert scp_data["port"] == config.scp_port

        # Check MWL status endpoint
        res_mwl = client.get("/api/v1/mwl/status")
        assert res_mwl.status_code == 200
        mwl_data = res_mwl.json()
        assert mwl_data["active_entries_count"] >= 10
        assert mwl_data["is_auto_generating"] is True

        # Check that mock entries are actively queryable via API
        res_entries = client.get("/api/v1/mwl")
        assert res_entries.status_code == 200
        entries = res_entries.json()
        assert len(entries) >= 10

        # Test C-ECHO to verify SCP listener is accepting network associations
        ae = AE(ae_title="TEST_SCU")
        ae.add_requested_context(Verification)
        assoc = ae.associate("127.0.0.1", config.scp_port)
        assert assoc.is_established
        status = assoc.send_c_echo()
        assert status and status.Status == 0x0000
        assoc.release()
