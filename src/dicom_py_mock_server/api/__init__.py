"""Expose API router."""

from dicom_py_mock_server.api.dicomweb_routes import dicomweb_router
from dicom_py_mock_server.api.mcp_routes import mcp_router
from dicom_py_mock_server.api.routes import router

__all__ = ["dicomweb_router", "mcp_router", "router"]
