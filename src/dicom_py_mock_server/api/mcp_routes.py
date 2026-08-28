"""FastAPI endpoints for MCP Server-Sent Events (SSE) transport."""

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from dicom_py_mock_server.config import config
from dicom_py_mock_server.logging_config import get_logger
from dicom_py_mock_server.services.mcp import McpService

logger = get_logger(__name__)

mcp_router = APIRouter()
mcp_service = McpService(app_config=config)


async def sse_event_generator(request: Request, session_id: str) -> AsyncGenerator[str, None]:
    """Asynchronous generator yielding SSE events for MCP client session."""
    queue = mcp_service.get_session_queue(session_id)
    if queue is None:
        return

    try:
        # 1. Send initial 'endpoint' event specifying the message POST URI according to MCP SSE standard
        post_uri = f"/api/v1/sse/messages?session_id={session_id}"
        yield f"event: endpoint\ndata: {post_uri}\n\n"

        # 2. Continuously stream JSON-RPC message events queued for this session
        while True:
            if await request.is_disconnected():
                logger.info("mcp_client_disconnected", session_id=session_id)
                break

            try:
                item = queue.get_nowait()
                if item is None:
                    break

                event_data = json.dumps(item)
                yield f"event: message\ndata: {event_data}\n\n"
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.05)
                continue
    except Exception as exc:
        logger.error("mcp_sse_generator_error", session_id=session_id, error=str(exc))
    finally:
        mcp_service.remove_session(session_id)


@mcp_router.get("/sse")
@mcp_router.get("/api/v1/sse")
async def mcp_sse_endpoint(request: Request):
    """Establishes an SSE transport connection for MCP client."""
    if not config.mcp_enabled:
        raise HTTPException(status_code=403, detail="MCP integration is disabled in server configuration.")

    session_id = mcp_service.create_session()
    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        sse_event_generator(request, session_id),
        media_type="text/event-stream",
        headers=headers,
    )


@mcp_router.post("/sse/messages")
@mcp_router.post("/api/v1/sse/messages")
async def mcp_post_messages(request: Request, session_id: str | None = None):
    """Accepts JSON-RPC 2.0 requests from MCP clients for an active SSE session."""
    if not config.mcp_enabled:
        raise HTTPException(status_code=403, detail="MCP integration is disabled in server configuration.")

    target_session_id = session_id or request.query_params.get("session_id")
    if not target_session_id or mcp_service.get_session_queue(target_session_id) is None:
        raise HTTPException(status_code=404, detail="Invalid or expired MCP session_id")

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    response_payload = await mcp_service.handle_jsonrpc_request(target_session_id, body)
    if response_payload is not None:
        mcp_service.push_session_event(target_session_id, response_payload)

    return Response(status_code=202, content="Accepted", media_type="text/plain")

