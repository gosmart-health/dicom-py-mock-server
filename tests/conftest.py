"""Pytest configuration and global fixtures."""

import pytest

from dicom_py_mock_server.api.dicomweb_routes import dicomweb_service
from dicom_py_mock_server.config import config


@pytest.fixture(autouse=True)
def default_non_stress_env(monkeypatch):
    """Default tests to non-stress mode to ensure repeatable tests regardless of local .env file."""
    monkeypatch.setattr(config, "stress", False)
    dicomweb_service.clear_stress_cache()
    yield
    dicomweb_service.clear_stress_cache()
