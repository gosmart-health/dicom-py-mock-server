"""Unit and integration tests for the push_hl7 CLI utility."""

import asyncio
from pathlib import Path

import pytest

from dicom_py_mock_server.config import AppConfig
from dicom_py_mock_server.services.hl7_server import Hl7MllpServer
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService
from dicom_py_mock_server.utils.push_hl7 import (
    find_default_orm_file,
    main,
    normalize_hl7_message,
    parse_ack_status,
    push_hl7_file,
    send_hl7_mllp,
)


@pytest.fixture
def test_config():
    """Create isolated test configuration for HL7 listener."""
    return AppConfig(
        templates_path="./templates",
        hl7_port=22576,
        mwl_window_hr=24,
    )


@pytest.fixture
def test_mwl_service(test_config):
    """Create isolated MWL service."""
    return MwlGeneratorService(app_config=test_config)


@pytest.fixture
def test_hl7_server(test_mwl_service, test_config):
    """Create isolated HL7 server instance."""
    return Hl7MllpServer(mwl_service=test_mwl_service, app_config=test_config)


def test_normalize_hl7_message():
    """Verify line endings are normalized to standard CR segment delimiters."""
    unix_text = "MSH|^~\\&|A|B\nPID|1||123\nOBR|1\n"
    normalized = normalize_hl7_message(unix_text)
    assert normalized == "MSH|^~\\&|A|B\rPID|1||123\rOBR|1\r"

    windows_text = "MSH|^~\\&|A|B\r\nPID|1||123\r\nOBR|1\r\n"
    normalized_win = normalize_hl7_message(windows_text)
    assert normalized_win == "MSH|^~\\&|A|B\rPID|1||123\rOBR|1\r"

    with pytest.raises(ValueError, match="Empty HL7 message"):
        normalize_hl7_message("   \n\r\n  ")


def test_parse_ack_status():
    """Verify extraction of MSA status codes, control ID, and comments."""
    ack_aa = "MSH|^~\\&|APP|FAC\rMSA|AA|MSG-001|Order accepted successfully\r"
    code, msg_id, comment = parse_ack_status(ack_aa)
    assert code == "AA"
    assert msg_id == "MSG-001"
    assert comment == "Order accepted successfully"

    ack_ae = "MSH|^~\\&|APP|FAC\rMSA|AE|MSG-002|Rejected: No template images\r"
    code, msg_id, comment = parse_ack_status(ack_ae)
    assert code == "AE"
    assert msg_id == "MSG-002"
    assert "Rejected" in comment


def test_find_default_orm_file():
    """Verify default orm.txt can be located from repository."""
    found = find_default_orm_file()
    assert found is not None
    assert found.name == "orm.txt"
    assert found.is_file()


def test_push_hl7_success_with_mllp_server(test_hl7_server, test_mwl_service, test_config):
    """Verify end-to-end pushing of sample util/orm.txt to live MLLP server."""

    async def _run():
        await test_hl7_server.start()
        try:
            orm_file = Path("util/orm.txt")
            assert orm_file.is_file()

            exit_code, ack_text = await asyncio.to_thread(
                push_hl7_file,
                file_path=orm_file,
                host=test_config.hl7_host,
                port=test_config.hl7_port,
                timeout=5.0,
                verbose=True,
            )

            assert exit_code == 0
            assert "MSA|AA|MSG-CT-001" in ack_text

            # Confirm MWL entry was created
            entries = test_mwl_service.find_entries(accession="ACC-CT-7788")
            assert len(entries) == 1
            assert entries[0]["patient_name"] == "JOHNSON^ROBERT^M"
            assert entries[0]["patient_id"] == "TEST-PAT-8899"
            assert entries[0]["modality"] == "CT"
        finally:
            await test_hl7_server.stop()

    asyncio.run(_run())


def test_push_hl7_rejection_with_unsupported_modality(test_hl7_server, test_mwl_service, test_config, tmp_path):
    """Verify rejection when order specifies unsupported modality without templates."""

    async def _run():
        await test_hl7_server.start()
        try:
            unsupported_orm = (
                "MSH|^~\\&|EPIC|HOSPITAL|GOSMART_MWL|GOSMART_HOSP|20260907120000||ORM^O01|MSG-PET-99|P|2.3\n"
                "PID|1||PAT-99^^^HOSPITAL||PETPATIENT^TEST||19800101|M\n"
                "ORC|NW|ORD-PET-1|ACC-PET-99\n"
                "OBR|1|ORD-PET-1|ACC-PET-99|PET01^PET SCAN||||||||||||||||||PET\n"
            )
            msg_file = tmp_path / "pet_orm.txt"
            msg_file.write_text(unsupported_orm, encoding="utf-8")

            exit_code, ack_text = await asyncio.to_thread(
                push_hl7_file,
                file_path=msg_file,
                host=test_config.hl7_host,
                port=test_config.hl7_port,
                timeout=5.0,
            )

            assert exit_code == 1
            assert "MSA|AE|MSG-PET-99" in ack_text
            assert "No template images available for modality 'PET'" in ack_text
        finally:
            await test_hl7_server.stop()

    asyncio.run(_run())


def test_push_hl7_connection_error(tmp_path):
    """Verify graceful handling when target server is down."""
    msg_file = tmp_path / "dummy_orm.txt"
    msg_file.write_text("MSH|^~\\&|A|B\rPID|1||123\r", encoding="utf-8")

    # Port 29999 should be closed
    exit_code = main(["-p", "29999", "-t", "0.5", str(msg_file)])
    assert exit_code == 1


def test_push_hl7_file_not_found():
    """Verify handling when specified file does not exist."""
    exit_code = main(["non_existent_file_xyz_123.txt"])
    assert exit_code == 1


def test_push_hl7_cli_success(test_hl7_server, test_config):
    """Verify main() CLI execution with command-line arguments."""

    async def _run():
        await test_hl7_server.start()
        try:
            exit_code = await asyncio.to_thread(
                main,
                [
                    "-H",
                    test_config.hl7_host,
                    "-p",
                    str(test_config.hl7_port),
                    "util/orm.txt",
                ],
            )
            assert exit_code == 0
        finally:
            await test_hl7_server.stop()

    asyncio.run(_run())


def test_send_hl7_mllp_malformed_response(monkeypatch):
    """Verify error raised if server sends non-MLLP response."""
    import socket

    class MockSocket:
        def __init__(self, *args, **kwargs):
            self._called = False

        def settimeout(self, timeout):
            pass

        def connect(self, addr):
            pass

        def sendall(self, data):
            pass

        def recv(self, bufsize):
            if not self._called:
                self._called = True
                return b"HTTP/1.1 200 OK\r\n\r\n"
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(socket, "socket", MockSocket)
    with pytest.raises(ConnectionError, match="Malformed or missing MLLP framing"):
        send_hl7_mllp("MSH|^~\\&|A|B\r", "127.0.0.1", 2575)
