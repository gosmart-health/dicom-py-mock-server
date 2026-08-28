"""Structlog logging system setup with auto-rotating file logs."""

import logging
import logging.handlers
import sys
from pathlib import Path

import structlog
from structlog.types import Processor

from dicom_py_mock_server.config import AppConfig, config


def setup_logging(cfg: AppConfig | None = None) -> None:
    """Initialize structlog and standard library logging with 7-day auto-rotation.

    Args:
        cfg: AppConfig instance. If None, uses default global config.
    """
    if cfg is None:
        cfg = config

    log_level = getattr(logging, cfg.log_level.upper(), logging.INFO)

    # Ensure output log directory exists
    log_path = Path(cfg.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Shared processors for structlog pipeline
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Structlog global configuration
    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Foreign pre-chain for standard library log messages (e.g., uvicorn, pynetdicom)
    foreign_pre_chain: list[Processor] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
    ]

    # Console Handler Formatter (Human readable / colored if tty)
    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=foreign_pre_chain,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()),
        ],
    )

    # File Handler Formatter (JSON or Console depending on config)
    file_processor: Processor = (
        structlog.processors.JSONRenderer()
        if cfg.log_json_format
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    file_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=foreign_pre_chain,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            file_processor,
        ],
    )

    # Handlers setup
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(log_level)

    # Auto-rotating file handler on 7-day basis
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_path),
        when="D",
        interval=cfg.log_rotation_days,
        backupCount=cfg.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(log_level)

    # Root Logger Setup
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Standardize third-party library loggers
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "pynetdicom", "fastapi"):
        lib_logger = logging.getLogger(logger_name)
        lib_logger.handlers.clear()
        lib_logger.propagate = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name. If None, caller's module name is inferred.

    Returns:
        structlog BoundLogger instance.
    """
    return structlog.get_logger(name)

