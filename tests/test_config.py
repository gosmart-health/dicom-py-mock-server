"""Unit tests for configuration loading, env variables, and .env file reading."""

from dicom_py_mock_server.config import AppConfig


def test_default_config_values():
    """Test default values when no environment variables are set."""
    cfg = AppConfig()
    assert cfg.scp_ae_title == "GOSMART_SCP"
    assert cfg.ae_title == "GOSMART_SCP"
    assert cfg.scp_port == 11112
    assert cfg.log_path == "./logs"
    assert cfg.log_file.endswith("dicom_mock_server.log")
    assert cfg.log_rotation_days == 7
    assert cfg.templates_path == "./templates"
    assert cfg.mwl_window_hr == 24
    assert cfg.mwl_rate_per_hr == 12.0
    assert cfg.min_slices == 8
    assert cfg.max_slices == 24
    assert cfg.patient_suffix == "_GSH"
    assert cfg.pn_suffix == "_GSH"
    assert cfg.institution_name == "GO SMART CLINIC"
    assert cfg.id_prefix == "GSH-"
    assert cfg.transfer_syntax == "JPEG2000_LOSSLESS"


def test_env_variables_override(monkeypatch):
    """Test overriding config via environment variables."""
    monkeypatch.setenv("GOSMART_MS_SCP_AE_TITLE", "CUSTOM_AE")
    monkeypatch.setenv("GOSMART_MS_SCP_PORT", "12345")
    monkeypatch.setenv("GOSMART_MS_LOG_PATH", "/custom/log/path")
    monkeypatch.setenv("GOSMART_MS_LOG_ROTATION_DAYS", "14")
    monkeypatch.setenv("GOSMART_TEMPLATES_PATH", "/custom/templates")
    monkeypatch.setenv("GOSMART_MS_MWL_WINDOW_HR", "48")
    monkeypatch.setenv("GOSMART_MS_MWL_RATE_PER_HR", "20")
    monkeypatch.setenv("GOSMART_MS_MIN_SLICES", "16")
    monkeypatch.setenv("GOSMART_MS_MAX_SLICES", "32")
    monkeypatch.setenv("GOSMART_MS_PATIENT_SUFFIX", "_TEST")
    monkeypatch.setenv("GOSMART_MS_PN_SUFFIX", "_PHY")
    monkeypatch.setenv("GORMART_MS_INSTITUTION_NAME", "MY CLINIC")
    monkeypatch.setenv("GOSMART_MS_ID_PREFIX", "TEST-")

    cfg = AppConfig()
    assert cfg.scp_ae_title == "CUSTOM_AE"
    assert cfg.ae_title == "CUSTOM_AE"
    assert cfg.scp_port == 12345
    assert cfg.log_path == "/custom/log/path"
    assert cfg.log_rotation_days == 14
    assert cfg.templates_path == "/custom/templates"
    assert cfg.mwl_window_hr == 48
    assert cfg.mwl_rate_per_hr == 20.0
    assert cfg.min_slices == 16
    assert cfg.max_slices == 32
    assert cfg.patient_suffix == "_TEST"
    assert cfg.pn_suffix == "_PHY"
    assert cfg.institution_name == "MY CLINIC"
    assert cfg.id_prefix == "TEST-"


def test_empty_string_env_variables_override(monkeypatch):
    """Test that empty strings are permitted for patient_suffix, pn_suffix, and id_prefix in env."""
    monkeypatch.setenv("GOSMART_MS_PATIENT_SUFFIX", "")
    monkeypatch.setenv("GOSMART_MS_PN_SUFFIX", "")
    monkeypatch.setenv("GOSMART_MS_ID_PREFIX", "")

    cfg = AppConfig()
    assert cfg.patient_suffix == ""
    assert cfg.pn_suffix == ""
    assert cfg.id_prefix == ""


def test_env_file_reading(tmp_path, monkeypatch):
    """Test reading values from a .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GOSMART_MS_SCP_AE_TITLE=DOTENV_AE\n"
        "GOSMART_MS_SCP_PORT=22222\n"
        "GOSMART_MS_LOG_PATH=./dotenv_logs\n"
        "GOSMART_MS_LOG_ROTATION_DAYS=30\n"
        "GOSMART_TEMPLATES_PATH=./dotenv_templates\n"
        "GOSMART_MS_MWL_WINDOW_HR=12\n"
        "GOSMART_MS_MWL_RATE_PER_HR=6.5\n"
        "GOSMART_MS_MIN_SLICES=10\n"
        "GOSMART_MS_MAX_SLICES=40\n"
        "GOSMART_MS_PATIENT_SUFFIX=_DOTENV\n"
        "GOSMART_MS_PN_SUFFIX=_DOTENV_PN\n"
        "GORMART_MS_INSTITUTION_NAME=DOTENV CLINIC\n"
        "GOSMART_MS_ID_PREFIX=DOTENV-\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    cfg = AppConfig()

    assert cfg.scp_ae_title == "DOTENV_AE"
    assert cfg.scp_port == 22222
    assert cfg.log_path == "./dotenv_logs"
    assert cfg.log_rotation_days == 30
    assert cfg.templates_path == "./dotenv_templates"
    assert cfg.mwl_window_hr == 12
    assert cfg.mwl_rate_per_hr == 6.5
    assert cfg.min_slices == 10
    assert cfg.max_slices == 40
    assert cfg.patient_suffix == "_DOTENV"
    assert cfg.pn_suffix == "_DOTENV_PN"
    assert cfg.institution_name == "DOTENV CLINIC"
    assert cfg.id_prefix == "DOTENV-"
