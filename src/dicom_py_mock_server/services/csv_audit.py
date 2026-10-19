"""CSV Audit Logging Subsystem for C-STORE Association Tracking."""

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dicom_py_mock_server.config import config
from dicom_py_mock_server.logging_config import get_logger

logger = get_logger(__name__)

StatusType = Literal["Accepted", "Rejected", "No Connection", "Dropped"]


@dataclass
class CStoreAuditRecord:
    """Audit record for an individual C-STORE SOP instance transfer."""

    date: str  # YYYYMMDD
    time: str  # HHMMSS
    destination_ae: str
    status: StatusType
    patient_name: str
    patient_id: str
    accession_number: str
    study_uid: str
    series_uid: str
    instance_uid: str
    transfer_rate_kbps: float = 0.0


@dataclass
class CStoreAuditSession:
    """Manages an association C-STORE audit session and persists CSV logs."""

    destination_ae: str
    csv_dir: Path | str = field(default_factory=lambda: getattr(config, "csv_path", "./csv"))
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    records: list[CStoreAuditRecord] = field(default_factory=list)
    total_bytes: int = 0

    CSV_HEADER: list[str] = field(
        default_factory=lambda: [
            "Date",
            "Time",
            "Destination AE",
            "Status",
            "Patient Name",
            "Patient ID",
            "Accession Number",
            "Study UID",
            "Series UID",
            "Instance UID",
            "Transfer Rate kb/s",
        ]
    )

    def add_record(
        self,
        status: StatusType,
        patient_name: str = "",
        patient_id: str = "",
        accession_number: str = "",
        study_uid: str = "",
        series_uid: str = "",
        instance_uid: str = "",
        instance_bytes: int = 0,
        transfer_rate_kbps: float = 0.0,
    ) -> CStoreAuditRecord:
        """Record a single C-STORE transfer."""
        now = datetime.now(timezone.utc)
        record = CStoreAuditRecord(
            date=now.strftime("%Y%m%d"),
            time=now.strftime("%H%M%S"),
            destination_ae=self.destination_ae,
            status=status,
            patient_name=patient_name,
            patient_id=patient_id,
            accession_number=accession_number,
            study_uid=study_uid,
            series_uid=series_uid,
            instance_uid=instance_uid,
            transfer_rate_kbps=transfer_rate_kbps,
        )
        self.records.append(record)
        self.total_bytes += instance_bytes
        return record

    def write_csv(self, file_path: Path | str | None = None) -> Path:
        """Write session audit records to a CSV file."""
        csv_dir = Path(self.csv_dir)
        csv_dir.mkdir(parents=True, exist_ok=True)

        if file_path is None:
            ts_str = self.start_time.strftime("%Y%m%d%H%M%S")
            ae_clean = self.destination_ae.strip().replace(" ", "_") or "UNKNOWN_AE"
            file_path = csv_dir / f"{ts_str}_{ae_clean}.csv"
        else:
            file_path = Path(file_path)

        with open(file_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(self.CSV_HEADER)
            for r in self.records:
                writer.writerow(
                    [
                        r.date,
                        r.time,
                        r.destination_ae,
                        r.status,
                        r.patient_name,
                        r.patient_id,
                        r.accession_number,
                        r.study_uid,
                        r.series_uid,
                        r.instance_uid,
                        f"{r.transfer_rate_kbps:.2f}",
                    ]
                )

        logger.info("cstore_audit_csv_written", path=str(file_path), record_count=len(self.records))
        return file_path
