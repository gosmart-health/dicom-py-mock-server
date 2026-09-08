"""Expose API router."""

from dicom_py_mock_server.api.dicomweb_routes import dicomweb_router
from dicom_py_mock_server.api.fhir_routes import router as fhir_router
from dicom_py_mock_server.api.hl7_routes import hl7_server
from dicom_py_mock_server.api.hl7_routes import router as hl7_router
from dicom_py_mock_server.api.mcp_routes import mcp_router
from dicom_py_mock_server.api.routes import router

__all__ = ["dicomweb_router", "fhir_router", "hl7_router", "hl7_server", "mcp_router", "router"]
