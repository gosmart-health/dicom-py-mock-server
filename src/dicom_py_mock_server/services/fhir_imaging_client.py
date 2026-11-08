"""HTTP Client for communicating with the gosmart-fhir-py-plugin service."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from dicom_py_mock_server.config import config

logger = structlog.get_logger(__name__)


class FhirPluginClient:
    """Async client for fetching patient imaging studies from gosmart-fhir-py-plugin."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or config.fhir_plugin_url).rstrip("/")

    async def fetch_patient_imaging(
        self,
        count: int = 200,
        modalities: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Fetch patient imaging studies bundle from gosmart-fhir-py-plugin.

        Returns:
            A tuple of (imaging_study_bundles, returned_count).
        """
        params: dict[str, Any] = {
            "count": count,
        }
        if modalities:
            params["modalities"] = modalities

        # Default standard path in gosmart-fhir-py-plugin is /api/v1/fhir/patient-imaging
        url = f"{self.base_url}/api/v1/fhir/patient-imaging"
        fallback_url = f"{self.base_url}/api/v1/patient-imaging"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, params=params)
                if response.status_code == 404:
                    logger.debug("fhir_patient_imaging_fallback_url", fallback_url=fallback_url)
                    response = await client.get(fallback_url, params=params)

                response.raise_for_status()
                data = response.json()

                new_count = data.get("count", 0)
                imaging_study = data.get("imaging_study", [])

                logger.debug(
                    "fhir_patient_imaging_fetch_success",
                    url=str(response.url),
                    status_code=response.status_code,
                    bundles_count=len(imaging_study),
                    count=new_count,
                )
                return imaging_study, new_count

        except httpx.HTTPError as exc:
            logger.error(
                "fhir_patient_imaging_http_error",
                url=url,
                error=str(exc),
                count=count,
            )
            return [], 0
        except Exception as exc:
            logger.error(
                "fhir_patient_imaging_unexpected_error",
                url=url,
                error=str(exc),
                count=count,
            )
            return [], 0
