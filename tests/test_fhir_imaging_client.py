"""Unit tests for FhirPluginClient using httpx MockTransport."""

import httpx
import pytest

from dicom_py_mock_server.services.fhir_imaging_client import FhirPluginClient


@pytest.mark.anyio
async def test_fhir_client_fetch_success():
    """Verify standard fetch from /api/v1/fhir/patient-imaging."""
    mock_payload = {
        "raw_offset": 200,
        "raw_count": 50,
        "imaging_study": [
            {"resourceType": "Bundle", "id": "b-1", "entry": []},
            {"resourceType": "Bundle", "id": "b-2", "entry": []},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/fhir/patient-imaging"
        assert request.url.params.get("raw_offset") == "100"
        assert request.url.params.get("raw_count") == "50"
        return httpx.Response(200, json=mock_payload)

    transport = httpx.MockTransport(handler)

    client = FhirPluginClient(base_url="http://mock-fhir:8088")
    import unittest.mock

    with unittest.mock.patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        bundles, new_offset, new_count = await client.fetch_patient_imaging(raw_offset=100, raw_count=50)

    assert len(bundles) == 2
    assert new_offset == 200
    assert new_count == 50


@pytest.mark.anyio
async def test_fhir_client_fallback_on_404():
    """Verify fallback to /api/v1/patient-imaging when /api/v1/fhir/patient-imaging returns 404."""
    call_history = []

    def handler(request: httpx.Request) -> httpx.Response:
        call_history.append(request.url.path)
        if request.url.path == "/api/v1/fhir/patient-imaging":
            return httpx.Response(404, text="Not Found")
        elif request.url.path == "/api/v1/patient-imaging":
            return httpx.Response(200, json={"raw_offset": 10, "raw_count": 10, "imaging_study": []})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = FhirPluginClient(base_url="http://mock-fhir:8088")

    import unittest.mock

    with unittest.mock.patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        bundles, new_offset, new_count = await client.fetch_patient_imaging(raw_offset=0, raw_count=10)

    assert call_history == ["/api/v1/fhir/patient-imaging", "/api/v1/patient-imaging"]
    assert new_offset == 10
    assert new_count == 10
    assert bundles == []


@pytest.mark.anyio
async def test_fhir_client_http_error_graceful_handling():
    """Verify that HTTP 500 or connection errors return empty results without raising."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(handler)
    client = FhirPluginClient(base_url="http://mock-fhir:8088")

    import unittest.mock

    with unittest.mock.patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        bundles, new_offset, new_count = await client.fetch_patient_imaging(raw_offset=42, raw_count=10)

    assert bundles == []
    assert new_offset == 42
    assert new_count == 0
