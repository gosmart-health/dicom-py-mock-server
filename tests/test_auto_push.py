"""Integration and unit tests for automated study push (auto-push) functionality."""

import asyncio
import json
import time

import pytest

from dicom_py_mock_server.config import config
from dicom_py_mock_server.services.mcp import McpService
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService
from dicom_py_mock_server.services.scp import DicomScpService
from tests.test_cmove_workflow import MockStorageScp


@pytest.mark.anyio
async def test_auto_push_workflow():
    """Test that DicomScpService auto-push periodically pushes generated studies to destination SCP."""
    test_port = 11145
    scp_port = 11146

    # 1. Start target mock storage SCP
    target_scp = MockStorageScp(ae_title="AUTO_DEST_SCP", port=test_port)
    target_scp.start()

    # 2. Register destination in config
    config.move_destinations["AUTO_DEST_SCP"] = {"host": "127.0.0.1", "port": test_port}

    # 3. Setup MWL service and SCP service
    mwl_service = MwlGeneratorService(config)
    scp_service = DicomScpService(ae_title="AUTO_MOCK_SCP", port=scp_port, mwl_service=mwl_service)

    # Enqueue a fast 4-instance study
    test_entry = mwl_service.add_entry(custom={"num_instances": 4, "modality": "CT"})
    scp_service.enqueue_auto_push_study(test_entry)

    try:
        # Start auto push with target AE schema: 0.2 second interval, explicit host and port
        scp_service.configure_auto_push(
            target_ae_title="AUTO_DEST_SCP",
            interval_sec=0.2,
            target_host="127.0.0.1",
            target_port=test_port,
        )
        assert scp_service._is_auto_pushing is True
        assert scp_service.auto_push_ae == "AUTO_DEST_SCP"
        assert scp_service.auto_push_host == "127.0.0.1"
        assert scp_service.auto_push_port == test_port
        assert scp_service.auto_push_sec == 0.2

        # Wait until all 4 instances of the queued study are received or timeout
        start_wait = time.time()
        while len(target_scp.received_datasets) < 4 and time.time() - start_wait < 10.0:
            await asyncio.sleep(0.1)

        # Stop auto-push before asserting to prevent race with subsequent cycles
        stop_res = scp_service.configure_auto_push(target_ae_title="AUTO_DEST_SCP", interval_sec=0)
        assert stop_res["is_auto_pushing"] is False
        assert scp_service._is_auto_pushing is False

        # Verify target received generated study instances
        assert len(target_scp.received_datasets) >= 4

        first_ds = target_scp.received_datasets[0]
        assert hasattr(first_ds, "PatientID")
        assert hasattr(first_ds, "StudyInstanceUID")
        assert hasattr(first_ds, "SeriesInstanceUID")
        assert hasattr(first_ds, "SOPInstanceUID")
        assert hasattr(first_ds, "PixelData")
        assert str(first_ds.PatientID).startswith(config.id_prefix)

        initial_count = len(target_scp.received_datasets)

        # Wait a moment to ensure no more studies are pushed
        await asyncio.sleep(0.5)
        assert len(target_scp.received_datasets) == initial_count
    finally:
        scp_service.stop()
        target_scp.stop()


@pytest.mark.anyio
async def test_mcp_auto_push_tool():
    """Test MCP tool 'auto_push' permits 'auto push to {AE Title} every {interval} seconds'."""
    mwl_service = MwlGeneratorService(config)
    scp_service = DicomScpService(ae_title="MCP_TEST_SCP", port=11147, mwl_service=mwl_service)
    mcp_service = McpService(app_config=config, mwl_service=mwl_service, scp_service=scp_service)

    # Verify tool is listed
    tools = mcp_service.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "auto_push" in tool_names

    auto_push_def = next(t for t in tools if t["name"] == "auto_push")
    assert "auto push to {AE Title} every {interval} seconds" in auto_push_def["description"]

    # 1. Enable auto-push via MCP tool using camelCase target AE schema
    result = await mcp_service.execute_tool(
        "auto_push",
        {
            "targetAeTitle": "VIEWER_MCP",
            "intervalSec": 10,
            "targetHost": "127.0.0.1",
            "targetPort": 11119,
        },
    )
    assert result["isError"] is False
    content = json.loads(result["content"][0]["text"])
    assert content["success"] is True
    assert content["targetAeTitle"] == "VIEWER_MCP"
    assert content["targetHost"] == "127.0.0.1"
    assert content["targetPort"] == 11119
    assert content["intervalSec"] == 10.0
    assert content["is_auto_pushing"] is True
    assert scp_service._is_auto_pushing is True

    # 2. Disable auto-push via MCP tool with intervalSec = 0
    disable_res = await mcp_service.execute_tool(
        "auto_push",
        {"targetAeTitle": "VIEWER_MCP", "intervalSec": 0},
    )
    assert disable_res["isError"] is False
    disable_content = json.loads(disable_res["content"][0]["text"])
    assert disable_content["success"] is True
    assert disable_content["is_auto_pushing"] is False
    assert scp_service._is_auto_pushing is False


@pytest.mark.anyio
async def test_mcp_update_config_auto_push():
    """Test configuring auto_push settings via MCP update_config tool."""
    mwl_service = MwlGeneratorService(config)
    scp_service = DicomScpService(ae_title="MCP_CFG_SCP", port=11148, mwl_service=mwl_service)
    mcp_service = McpService(app_config=config, mwl_service=mwl_service, scp_service=scp_service)

    try:
        res = await mcp_service.execute_tool(
            "update_config",
            {"auto_push_ae": "DYNAMIC_DEST", "auto_push_sec": 20},
        )
        assert res["isError"] is False
        assert scp_service.auto_push_ae == "DYNAMIC_DEST"
        assert scp_service.auto_push_sec == 20.0
        assert scp_service._is_auto_pushing is True

        # Disable via update_config
        res_dis = await mcp_service.execute_tool(
            "update_config",
            {"auto_push_sec": 0},
        )
        assert res_dis["isError"] is False
        assert scp_service.auto_push_sec == 0.0
        assert scp_service._is_auto_pushing is False
    finally:
        scp_service.stop()


@pytest.mark.anyio
async def test_auto_push_invoked_from_thread():
    """Verify configure_auto_push succeeds when called from a background threadpool thread."""
    loop = asyncio.get_running_loop()
    mwl_service = MwlGeneratorService(config)
    scp_service = DicomScpService(ae_title="THREAD_TEST_SCP", port=11149, mwl_service=mwl_service)
    scp_service.set_event_loop(loop)

    try:
        # Call configure_auto_push from an off-loop worker thread (mimics sync route execution)
        def call_from_thread():
            return scp_service.configure_auto_push(
                target_ae_title="THREAD_DEST_SCP",
                interval_sec=5.0,
                target_host="127.0.0.1",
                target_port=11113,
            )

        res = await asyncio.to_thread(call_from_thread)
        assert res["success"] is True
        assert res["is_auto_pushing"] is True
        assert scp_service._is_auto_pushing is True

        # Wait a small slice for worker thread to start
        await asyncio.sleep(0.05)
        assert scp_service._auto_push_thread is not None
        assert scp_service._auto_push_thread.is_alive()

        # Stop from thread
        stop_res = await asyncio.to_thread(scp_service.stop_auto_push)
        assert stop_res["is_auto_pushing"] is False
        assert scp_service._is_auto_pushing is False
    finally:
        scp_service.stop()
