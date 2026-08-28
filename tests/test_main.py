"""Tests for dicom-py-mock-server main app."""

from dicom_py_mock_server.main import app


def test_app_title():
    assert app.title == "DICOM Mock Server"
