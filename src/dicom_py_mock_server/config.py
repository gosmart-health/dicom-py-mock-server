from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Global configuration settings for DICOM Mock Server."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="GOSMART_MS_",
        extra="ignore",
    )

    app_name: str = "DICOM Mock Server"
    app_version: str = "0.2.3"
    host: str = "127.0.0.1"
    port: int = 8000
    scp_ae_title: str = Field(
        default="GOSMART_SCP",
        validation_alias=AliasChoices("GOSMART_MS_SCP_AE_TITLE", "GOSMART_MS_AE_TITLE", "SCP_AE_TITLE", "AE_TITLE"),
        description="Application Entity Title",
    )
    scp_port: int = Field(
        default=11112,
        validation_alias=AliasChoices("GOSMART_MS_SCP_PORT", "SCP_PORT"),
        description="DICOM SCP port",
    )
    storage_dir: str = Field(
        default="./data/dicom_storage",
        validation_alias=AliasChoices("GOSMART_MS_STORAGE_DIR", "STORAGE_DIR"),
        description="Path to store DICOM files",
    )
    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("GOSMART_MS_LOG_LEVEL", "LOG_LEVEL"),
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    log_path: str = Field(
        default="./logs",
        validation_alias=AliasChoices("GOSMART_MS_LOG_PATH", "GOSMART_MS_LOG_FILE", "LOG_PATH", "LOG_FILE"),
        description="Directory or file path for log files",
    )
    log_rotation_days: int = Field(
        default=7,
        validation_alias=AliasChoices("GOSMART_MS_LOG_ROTATION_DAYS", "LOG_ROTATION_DAYS"),
        description="Log auto-rotation interval in days",
    )
    log_backup_count: int = Field(
        default=4,
        validation_alias=AliasChoices("GOSMART_MS_LOG_BACKUP_COUNT", "LOG_BACKUP_COUNT"),
        description="Number of backup log files to retain",
    )
    log_json_format: bool = Field(
        default=True,
        validation_alias=AliasChoices("GOSMART_MS_LOG_JSON_FORMAT", "LOG_JSON_FORMAT"),
        description="Enable JSON log formatting for log files",
    )
    templates_path: str = Field(
        default="./templates",
        validation_alias=AliasChoices("GOSMART_TEMPLATES_PATH", "GOSMART_MS_TEMPLATES_PATH", "TEMPLATES_PATH"),
        description="Path to templates directory",
    )
    mwl_window_hr: int = Field(
        default=24,
        validation_alias=AliasChoices("GOSMART_MS_MWL_WINDOW_HR", "MWL_WINDOW_HR"),
        description="MWL active retention window in hours",
    )
    mwl_rate_per_hr: float = Field(
        default=12.0,
        validation_alias=AliasChoices("GOSMART_MS_MWL_RATE_PER_HR", "MWL_RATE_PER_HR"),
        description="Creation rate of new MWL entries per hour during business hours (9am-5pm)",
    )
    mcp_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("GOSMART_MS_MCP_ENABLED", "MCP_ENABLED"),
        description="Enable MCP SSE integration endpoints",
    )
    mcp_sse_path: str = Field(
        default="/sse",
        validation_alias=AliasChoices("GOSMART_MS_MCP_SSE_PATH", "MCP_SSE_PATH"),
        description="Base path for MCP SSE endpoint",
    )
    min_slices: int = Field(
        default=8,
        validation_alias=AliasChoices("GOSMART_MS_MIN_SLICES", "MIN_SLICES"),
        description="Minimum number of slices for volume image generation",
    )
    max_slices: int = Field(
        default=24,
        validation_alias=AliasChoices("GOSMART_MS_MAX_SLICES", "MAX_SLICES"),
        description="Maximum number of slices for volume image generation",
    )
    transfer_syntax: str = Field(
        default="JPEG2000_LOSSLESS",
        validation_alias=AliasChoices("GOSMART_MS_TRANSFER_SYNTAX", "TRANSFER_SYNTAX"),
        description="Default DICOM Transfer Syntax for generated images (RAW, JPEG, JPEG2000, JPEG2000_LOSSLESS, RLE)",
    )
    stress: bool = Field(
        default=False,
        validation_alias=AliasChoices("GOSMART_MS_STRESS", "STRESS"),
        description=(
            "Enable high-performance stress mode (single frame compression, demographics overlay only, no slice number)"
        ),
    )
    move_destinations: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("GOSMART_MS_MOVE_DESTINATIONS", "MOVE_DESTINATIONS"),
        description="Mapping of Move Destination AE Titles to target host and port dicts",
    )
    patient_suffix: str = Field(
        default="_GSH",
        validation_alias=AliasChoices("GOSMART_MS_PATIENT_SUFFIX", "PATIENT_SUFFIX"),
        description="Suffix appended to patient last name to avoid PACS collisions",
    )
    pn_suffix: str = Field(
        default="_GSH",
        validation_alias=AliasChoices("GOSMART_MS_PN_SUFFIX", "PN_SUFFIX"),
        description="Suffix appended to generated physician names to avoid PACS collisions",
    )
    institution_name: str = Field(
        default="GO SMART CLINIC",
        validation_alias=AliasChoices(
            "GOSMART_MS_INSTITUTION_NAME",
            "GORMART_MS_INSTITUTION_NAME",
            "INSTITUTION_NAME",
        ),
        description="Default Institution Name attribute for generated DICOM studies and MWL entries",
    )
    id_prefix: str = Field(
        default="GSH-",
        validation_alias=AliasChoices("GOSMART_MS_ID_PREFIX", "ID_PREFIX"),
        description="Prefix prepended to patient ID and accession number to avoid PACS collisions",
    )
    dicom_namespace_uuid: str = Field(
        default="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        validation_alias=AliasChoices("GOSMART_MS_NAMESPACE_UUID", "GOSMART_MS_DICOM_NAMESPACE_UUID", "NAMESPACE_UUID"),
        description="Persistent UUID namespace used for deterministic ITU-T X.667 DICOM UID generation",
    )
    dicom_uid_version: int = Field(
        default=5,
        validation_alias=AliasChoices("GOSMART_MS_UID_VERSION", "GOSMART_MS_DICOM_UID_VERSION", "UID_VERSION"),
        description="UUID version for deterministic DICOM UID generation (5 for SHA-1, 3 for MD5)",
    )

    @property
    def ae_title(self) -> str:
        return self.scp_ae_title

    @property
    def log_file(self) -> str:
        path = Path(self.log_path)
        if path.suffix == ".log" or path.is_file():
            return str(path)
        return str(path / "dicom_mock_server.log")


config = AppConfig()
