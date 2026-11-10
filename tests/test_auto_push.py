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


@pytest.mark.anyio
async def test_auto_push_unresolvable_host_handled_gracefully(monkeypatch):
    """Verify that an unresolvable host (OSError / socket.gaierror) returns a structured failure without crashing."""
    mwl_service = MwlGeneratorService(config)
    scp_service = DicomScpService(ae_title="ERR_TEST_SCP", port=11150, mwl_service=mwl_service)
    test_entry = mwl_service.add_entry(custom={"num_instances": 1, "modality": "CT"})
    assert test_entry is not None
    scp_service.enqueue_auto_push_study(test_entry)

    scp_service.auto_push_ae = "BAD_DEST_AE"
    scp_service.auto_push_host = "unresolvable.invalid.host.local"
    scp_service.auto_push_port = 11112

    def mock_associate(*args, **kwargs):
        raise OSError(8, "nodename nor servname provided, or not known")

    monkeypatch.setattr("pynetdicom.ae.ApplicationEntity.associate", mock_associate)

    res = scp_service._push_one_auto_study()
    assert res is not None
    assert res["success"] is False
    assert res["instances_sent"] == 0
    assert res["target_ae_title"] == "BAD_DEST_AE"
    assert res["target_host"] == "unresolvable.invalid.host.local"
    assert res["target_port"] == 11112
    assert "nodename nor servname" in res["message"]
    assert len(scp_service._auto_push_queue) == 1
    assert scp_service._auto_push_queue[0] is test_entry


@pytest.mark.anyio
async def test_auto_push_retries_indefinitely_without_dropping_or_skipping(monkeypatch):
    """Verify failed pushes retain the head item in _auto_push_queue and retry in strict FIFO order."""
    mwl_service = MwlGeneratorService(config)
    scp_service = DicomScpService(ae_title="RETRY_TEST_SCP", port=11151, mwl_service=mwl_service)

    entry1 = mwl_service.add_entry(custom={"num_instances": 1, "modality": "CT", "accession": "ACC-RETRY-1"})
    entry2 = mwl_service.add_entry(custom={"num_instances": 1, "modality": "CT", "accession": "ACC-RETRY-2"})
    entry3 = mwl_service.add_entry(custom={"num_instances": 1, "modality": "CT", "accession": "ACC-RETRY-3"})
    assert entry1 and entry2 and entry3

    scp_service.enqueue_auto_push_study(entry1)
    scp_service.enqueue_auto_push_study(entry2)

    scp_service.auto_push_ae = "DEST_SCP"
    scp_service.auto_push_host = "127.0.0.1"
    scp_service.auto_push_port = 11152

    server_up = False
    pushed_accessions: list[str] = []

    def fake_push_datasets(datasets, target_ae_title, target_host="127.0.0.1", target_port=11113, preferred_syntax=None):
        acc = str(getattr(datasets[0], "AccessionNumber", ""))
        if not server_up:
            return {
                "success": False,
                "message": "Connection refused",
                "instances_sent": 0,
                "target_ae_title": target_ae_title,
                "target_host": target_host,
                "target_port": target_port,
            }
        pushed_accessions.append(acc)
        return {
            "success": True,
            "message": "OK",
            "instances_sent": len(datasets),
            "accession": acc,
            "target_ae_title": target_ae_title,
            "target_host": target_host,
            "target_port": target_port,
        }

    monkeypatch.setattr(scp_service, "push_datasets_to_destination", fake_push_datasets)

    # Attempt 1 & 2 while target SCP is down: must keep entry1 at head and never skip to entry2
    res1 = scp_service._push_one_auto_study()
    assert res1 is not None and res1["success"] is False
    assert [e["accession"] for e in scp_service._auto_push_queue] == ["ACC-RETRY-1", "ACC-RETRY-2"]

    # Enqueue entry3 while target SCP is still down
    scp_service.enqueue_auto_push_study(entry3)

    res2 = scp_service._push_one_auto_study()
    assert res2 is not None and res2["success"] is False
    assert [e["accession"] for e in scp_service._auto_push_queue] == [
        "ACC-RETRY-1",
        "ACC-RETRY-2",
        "ACC-RETRY-3",
    ]
    assert pushed_accessions == []

    # Target SCP comes back online: items must be pushed in strict FIFO order without any dropped items
    server_up = True

    res3 = scp_service._push_one_auto_study()
    assert res3 is not None and res3["success"] is True
    assert pushed_accessions == ["ACC-RETRY-1"]
    assert [e["accession"] for e in scp_service._auto_push_queue] == ["ACC-RETRY-2", "ACC-RETRY-3"]

    res4 = scp_service._push_one_auto_study()
    assert res4 is not None and res4["success"] is True
    assert pushed_accessions == ["ACC-RETRY-1", "ACC-RETRY-2"]
    assert [e["accession"] for e in scp_service._auto_push_queue] == ["ACC-RETRY-3"]

    res5 = scp_service._push_one_auto_study()
    assert res5 is not None and res5["success"] is True
    assert pushed_accessions == ["ACC-RETRY-1", "ACC-RETRY-2", "ACC-RETRY-3"]
    assert len(scp_service._auto_push_queue) == 0


@pytest.mark.anyio
async def test_auto_push_worker_recovers_after_target_scp_downtime():
    """Integration test: target SCP is stopped initially, then started; queued studies are retried and delivered in order."""
    test_port = 11153
    scp_port = 11154

    mwl_service = MwlGeneratorService(config)
    scp_service = DicomScpService(ae_title="RETRY_WORKER_SCP", port=scp_port, mwl_service=mwl_service)

    entry1 = mwl_service.add_entry(custom={"num_instances": 1, "modality": "CT", "accession": "ACC-DOWN-1"})
    entry2 = mwl_service.add_entry(custom={"num_instances": 1, "modality": "CT", "accession": "ACC-DOWN-2"})
    assert entry1 and entry2
    scp_service.enqueue_auto_push_study(entry1)
    scp_service.enqueue_auto_push_study(entry2)

    target_scp = MockStorageScp(ae_title="DOWN_DEST_SCP", port=test_port)
    config.move_destinations["DOWN_DEST_SCP"] = {"host": "127.0.0.1", "port": test_port}

    try:
        # Start auto-push while target_scp is NOT running
        scp_service.configure_auto_push(
            target_ae_title="DOWN_DEST_SCP",
            interval_sec=0.15,
            target_host="127.0.0.1",
            target_port=test_port,
        )
        # Allow multiple failed retry cycles while destination is down
        await asyncio.sleep(0.45)
        assert [e["accession"] for e in scp_service._auto_push_queue] == ["ACC-DOWN-1", "ACC-DOWN-2"]

        # Now start the target SCP and verify both queued studies arrive in order
        target_scp.start()
        start_wait = time.time()
        while len(target_scp.received_datasets) < 2 and time.time() - start_wait < 10.0:
            await asyncio.sleep(0.1)

        scp_service.stop_auto_push()
        received_accs = [str(ds.AccessionNumber) for ds in target_scp.received_datasets[:2]]
        assert received_accs == ["ACC-DOWN-1", "ACC-DOWN-2"]
    finally:
        scp_service.stop()
        target_scp.stop()
