"""Unit tests for MCP stdio transport runner."""

import io
import json
from unittest.mock import AsyncMock, patch

import pytest

from dicom_py_mock_server.logging_config import setup_logging
from dicom_py_mock_server.mcp_stdio import main, run_stdio_server
from dicom_py_mock_server.services.mcp import McpService


@pytest.fixture(autouse=True)
def reset_logging_after_test():
    """Ensure logging is restored after stdio tests."""
    yield
    setup_logging()


@pytest.mark.anyio
async def test_run_stdio_server_initialize_and_tools_list():
    """Test stdio server processes initialize and tools/list requests."""
    service = McpService()

    input_lines = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        + "\n"
    )

    mock_stdout = io.StringIO()

    mock_reader = AsyncMock()
    mock_reader.readline.side_effect = [
        input_lines.splitlines(True)[0].encode("utf-8"),
        input_lines.splitlines(True)[1].encode("utf-8"),
        b"",
    ]

    with (
        patch("sys.stdout.write", side_effect=mock_stdout.write),
        patch("sys.stdout.flush"),
        patch("asyncio.StreamReader", return_value=mock_reader),
        patch("asyncio.get_running_loop") as mock_loop,
    ):
        mock_loop.return_value.connect_read_pipe = AsyncMock()
        await run_stdio_server(service)

    output = mock_stdout.getvalue()
    responses = [json.loads(line) for line in output.strip().splitlines() if line]

    assert len(responses) == 2
    assert responses[0]["id"] == 1
    assert "protocolVersion" in responses[0]["result"]
    assert responses[1]["id"] == 2
    assert "tools" in responses[1]["result"]


@pytest.mark.anyio
async def test_run_stdio_server_invalid_json():
    """Test stdio server handles invalid JSON gracefully."""
    mock_stdout = io.StringIO()

    mock_reader = AsyncMock()
    mock_reader.readline.side_effect = [b"invalid-json-content\n", b""]

    with (
        patch("sys.stdout.write", side_effect=mock_stdout.write),
        patch("sys.stdout.flush"),
        patch("asyncio.StreamReader", return_value=mock_reader),
        patch("asyncio.get_running_loop") as mock_loop,
    ):
        mock_loop.return_value.connect_read_pipe = AsyncMock()
        await run_stdio_server()

    output = mock_stdout.getvalue()
    responses = [json.loads(line) for line in output.strip().splitlines() if line]
    assert len(responses) == 1
    assert responses[0]["error"]["code"] == -32700


def test_main_cli_entrypoint():
    """Test main entry point handles clean shutdown."""
    with patch("dicom_py_mock_server.mcp_stdio.run_stdio_server", return_value=None):
        with patch("asyncio.run", side_effect=KeyboardInterrupt):
            main()  # Should handle cleanly without raising
