"""Tests for MCP SSE transport and JSON-RPC tool endpoints."""

import json

import pytest
from fastapi.testclient import TestClient

from dicom_py_mock_server.api.mcp_routes import mcp_service, sse_event_generator
from dicom_py_mock_server.config import config
from dicom_py_mock_server.main import app

client = TestClient(app)


@pytest.mark.anyio
async def test_mcp_service_jsonrpc_protocol(tmp_path):
    config.storage_dir = str(tmp_path)

    session_id = mcp_service.create_session()
    assert mcp_service.get_session_queue(session_id) is not None

    # Test initialize
    init_res = await mcp_service.handle_jsonrpc_request(
        session_id,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
    )
    assert init_res is not None
    assert init_res["id"] == 1
    assert init_res["result"]["serverInfo"]["name"] == "DICOM Mock Server"

    # Test initialized notification
    notif_res = await mcp_service.handle_jsonrpc_request(
        session_id,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert notif_res is None

    # Test ping
    ping_res = await mcp_service.handle_jsonrpc_request(
        session_id,
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
    )
    assert ping_res == {"jsonrpc": "2.0", "id": 2, "result": {}}

    # Test tools/list
    list_res = await mcp_service.handle_jsonrpc_request(
        session_id,
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
    )
    assert list_res is not None
    tools = list_res["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "health_check" in tool_names
    assert "generate_mock_dicom" in tool_names
    assert "get_scp_status" in tool_names
    assert "generate_mwl_entry" in tool_names

    # Test tools/call health_check
    health_res = await mcp_service.handle_jsonrpc_request(
        session_id,
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "health_check", "arguments": {}}},
    )
    assert health_res is not None
    text_content = health_res["result"]["content"][0]["text"]
    assert "ok" in text_content

    # Test tools/call generate_mock_dicom
    gen_res = await mcp_service.handle_jsonrpc_request(
        session_id,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "generate_mock_dicom",
                "arguments": {
                    "patient": {"patient_id": "MCP-TEST-001"},
                    "num_instances": 1,
                    "rows": 32,
                    "columns": 32,
                },
            },
        },
    )
    assert gen_res is not None
    gen_data = json.loads(gen_res["result"]["content"][0]["text"])
    assert gen_data["success"] is True
    assert gen_data["patient_id"] == "MCP-TEST-001"

    # Test tools/call MWL generate and list
    mwl_gen_res = await mcp_service.handle_jsonrpc_request(
        session_id,
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "generate_mwl_entry",
                "arguments": {"patientId": "MWL-MCP-PAT", "modality": "MR"},
            },
        },
    )
    assert mwl_gen_res is not None
    mwl_gen_data = json.loads(mwl_gen_res["result"]["content"][0]["text"])
    assert mwl_gen_data["patient_id"] == "MWL-MCP-PAT"

    mwl_list_res = await mcp_service.handle_jsonrpc_request(
        session_id,
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "list_mwl_entries", "arguments": {}}},
    )
    assert mwl_list_res is not None
    mwl_list_data = json.loads(mwl_list_res["result"]["content"][0]["text"])
    assert any(e["patient_id"] == "MWL-MCP-PAT" for e in mwl_list_data)

    mcp_service.remove_session(session_id)
    assert mcp_service.get_session_queue(session_id) is None


@pytest.mark.anyio
async def test_mcp_sse_generator_events():
    config.mcp_enabled = True
    session_id = mcp_service.create_session()

    class DummyRequest:
        async def is_disconnected(self):
            return False

    gen = sse_event_generator(DummyRequest(), session_id)
    first_event = await anext(gen)
    assert "event: endpoint" in first_event
    assert f"session_id={session_id}" in first_event

    # Push message and get second event
    mcp_service.push_session_event(session_id, {"jsonrpc": "2.0", "id": 99, "result": {"status": "ok"}})
    second_event = await anext(gen)
    assert "event: message" in second_event
    assert '"id": 99' in second_event

    await gen.aclose()


def test_mcp_post_messages_endpoint():
    config.mcp_enabled = True

    session_id = mcp_service.create_session()
    res_post = client.post(
        f"/api/v1/sse/messages?session_id={session_id}",
        json={"jsonrpc": "2.0", "id": 10, "method": "ping"},
    )
    assert res_post.status_code == 202

    queue = mcp_service.get_session_queue(session_id)
    assert queue is not None
    msg = queue.get_nowait()
    assert msg["id"] == 10
    assert msg["result"] == {}
    mcp_service.remove_session(session_id)


def test_mcp_invalid_session_and_disabled():
    # Test invalid session_id
    res = client.post("/api/v1/sse/messages?session_id=invalid_id", json={"jsonrpc": "2.0", "id": 1})
    assert res.status_code == 404

    # Test disabled MCP
    config.mcp_enabled = False
    res_disabled = client.get("/api/v1/sse")
    assert res_disabled.status_code == 403
    config.mcp_enabled = True


@pytest.mark.anyio
async def test_mcp_move_study_tool():
    from tests.test_cmove_workflow import MockStorageScp

    viewer_port = 11136
    viewer = MockStorageScp(ae_title="MCP_VIEWER", port=viewer_port)
    viewer.start()

    session_id = mcp_service.create_session()
    try:
        # Move patient PAT-MCP-999
        res_move_pat = await mcp_service.handle_jsonrpc_request(
            session_id,
            {
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tools/call",
                "params": {
                    "name": "move_study",
                    "arguments": {
                        "patient_id": "PAT-MCP-999",
                        "target_ae_title": "MCP_VIEWER",
                        "target_host": "127.0.0.1",
                        "target_port": viewer_port,
                    },
                },
            },
        )
        assert res_move_pat is not None
        assert res_move_pat["result"]["isError"] is False
        move_data = json.loads(res_move_pat["result"]["content"][0]["text"])
        assert move_data["success"] is True
        assert move_data["patient_id"] == "PAT-MCP-999"
        assert move_data["instances_sent"] >= 8

        # Move accession ACC-MCP-777
        res_move_acc = await mcp_service.handle_jsonrpc_request(
            session_id,
            {
                "jsonrpc": "2.0",
                "id": 21,
                "method": "tools/call",
                "params": {
                    "name": "move_study",
                    "arguments": {
                        "accession": "ACC-MCP-777",
                        "target_ae_title": "MCP_VIEWER",
                        "target_host": "127.0.0.1",
                        "target_port": viewer_port,
                    },
                },
            },
        )
        assert res_move_acc is not None
        assert res_move_acc["result"]["isError"] is False
        acc_data = json.loads(res_move_acc["result"]["content"][0]["text"])
        assert acc_data["success"] is True
        assert acc_data["accession"] == "ACC-MCP-777"
        assert acc_data["instances_sent"] >= 8
    finally:
        viewer.stop()
        mcp_service.remove_session(session_id)
