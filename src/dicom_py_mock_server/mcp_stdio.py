"""Stdio transport runner for Model Context Protocol (MCP) CLI and local console agents."""

import asyncio
import json
import sys
from typing import Any

from dicom_py_mock_server.config import config
from dicom_py_mock_server.logging_config import get_logger, setup_logging
from dicom_py_mock_server.services.mcp import McpService

logger = get_logger(__name__)


async def run_stdio_server(mcp_service: McpService | None = None) -> None:
    """Run interactive JSON-RPC stdio loop reading from sys.stdin and writing to sys.stdout."""
    setup_logging(console_stream=sys.stderr)
    service = mcp_service or McpService(app_config=config)
    session_id = service.create_session()

    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line_bytes = await reader.readline()
        if not line_bytes:
            break
        line = line_bytes.decode("utf-8").strip()
        if not line:
            continue
        try:
            req: dict[str, Any] = json.loads(line)
        except Exception:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
            continue

        resp = await service.handle_jsonrpc_request(session_id, req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def main() -> None:
    """CLI entrypoint for stdio MCP server."""
    try:
        asyncio.run(run_stdio_server())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
