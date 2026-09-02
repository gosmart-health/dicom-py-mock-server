"""Unit tests for structlog logging system and auto-rotation configuration."""

import json
import logging
import logging.handlers

from dicom_py_mock_server.config import AppConfig
from dicom_py_mock_server.logging_config import get_logger, setup_logging


def test_setup_logging_configures_timed_rotating_handler(tmp_path):
    """Test setup_logging configures TimedRotatingFileHandler with 7-day rotation."""
    log_file = tmp_path / "logs" / "test.log"
    cfg = AppConfig(
        log_file=str(log_file),
        log_rotation_days=7,
        log_backup_count=3,
        log_level="DEBUG",
        log_json_format=True,
    )

    setup_logging(cfg)

    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG

    handlers = root_logger.handlers
    assert len(handlers) >= 2

    file_handlers = [h for h in handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)]
    assert len(file_handlers) == 1

    handler = file_handlers[0]
    assert handler.when == "D"
    assert handler.interval == 7 * 24 * 3600  # TimedRotatingFileHandler converts 'D' interval to seconds
    assert handler.backupCount == 3
    assert handler.baseFilename == str(log_file.resolve())


def test_structlog_json_file_output(tmp_path):
    """Test structlog writes structured JSON formatted logs to file."""
    log_file = tmp_path / "logs" / "json_test.log"
    cfg = AppConfig(
        log_file=str(log_file),
        log_rotation_days=7,
        log_backup_count=2,
        log_level="INFO",
        log_json_format=True,
    )

    setup_logging(cfg)
    logger = get_logger("test.module")

    logger.info("user_login_attempt", user_id="user_123", status="success")

    # Flush handlers
    for h in logging.getLogger().handlers:
        h.flush()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8").strip()
    assert len(content) > 0

    log_entry = json.loads(content.splitlines()[-1])
    assert log_entry["event"] == "user_login_attempt"
    assert log_entry["user_id"] == "user_123"
    assert log_entry["status"] == "success"
    assert log_entry["level"] == "info"
    assert log_entry["logger"] == "test.module"
    assert log_entry["method_name"] == "test_structlog_json_file_output"
    assert log_entry["func_name"] == "test_structlog_json_file_output"
    assert "timestamp" in log_entry


def test_stdlib_logging_interception(tmp_path):
    """Test standard library logging calls are intercepted and formatted by structlog formatter."""
    log_file = tmp_path / "logs" / "stdlib_test.log"
    cfg = AppConfig(
        log_file=str(log_file),
        log_rotation_days=7,
        log_level="INFO",
        log_json_format=True,
    )

    setup_logging(cfg)
    std_logger = logging.getLogger("stdlib.test")

    std_logger.info("Standard library log message from third-party package")

    for h in logging.getLogger().handlers:
        h.flush()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8").strip()
    log_entry = json.loads(content.splitlines()[-1])
    assert log_entry["event"] == "Standard library log message from third-party package"
    assert log_entry["logger"] == "stdlib.test"
    assert log_entry["level"] == "info"
    assert log_entry["method_name"] == "test_stdlib_logging_interception"
    assert log_entry["func_name"] == "test_stdlib_logging_interception"
