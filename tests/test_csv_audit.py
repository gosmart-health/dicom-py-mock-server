"""Tests for C-STORE Association CSV Audit Logging Subsystem."""

import csv
from datetime import datetime, timezone
from pathlib import Path

from dicom_py_mock_server.services.csv_audit import (
    CStoreAuditRecord,
    CStoreAuditSession,
)


def test_cstore_audit_record_creation():
    """Verify CStoreAuditRecord data model creation and fields."""
    record = CStoreAuditRecord(
        date="20261017",
        time="120000",
        destination_ae="PACS_STORAGE",
        status="Accepted",
        patient_name="Doe^John",
        patient_id="GSH-12345",
        accession_number="ACC-9999",
        study_uid="2.25.123456",
        series_uid="2.25.123456.1",
        instance_uid="2.25.123456.1.1",
        transfer_rate_kbps=1024.5,
    )
    assert record.date == "20261017"
    assert record.time == "120000"
    assert record.destination_ae == "PACS_STORAGE"
    assert record.status == "Accepted"
    assert record.patient_name == "Doe^John"
    assert record.patient_id == "GSH-12345"
    assert record.accession_number == "ACC-9999"
    assert record.study_uid == "2.25.123456"
    assert record.series_uid == "2.25.123456.1"
    assert record.instance_uid == "2.25.123456.1.1"
    assert record.transfer_rate_kbps == 1024.5


def test_push_study_generates_accepted_csv(tmp_path: Path):
    """Verify audit session records transfers and writes compliant CSV file."""
    session = CStoreAuditSession(
        destination_ae="TEST_PACS",
        csv_dir=tmp_path,
        start_time=datetime(2026, 10, 17, 14, 30, 0, tzinfo=timezone.utc),
    )

    session.add_record(
        status="Accepted",
        patient_name="Smith^Alice",
        patient_id="GSH-001",
        accession_number="ACC-001",
        study_uid="2.25.1001",
        series_uid="2.25.1001.1",
        instance_uid="2.25.1001.1.1",
        instance_bytes=524288,
        transfer_rate_kbps=2048.0,
    )

    session.add_record(
        status="Accepted",
        patient_name="Smith^Alice",
        patient_id="GSH-001",
        accession_number="ACC-001",
        study_uid="2.25.1001",
        series_uid="2.25.1001.1",
        instance_uid="2.25.1001.1.2",
        instance_bytes=524288,
        transfer_rate_kbps=2048.0,
    )

    csv_file = session.write_csv()
    assert csv_file.exists()
    assert csv_file.name == "20261017143000_TEST_PACS.csv"

    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = list(csv.reader(f))

    assert reader[0] == [
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
    assert len(reader) == 3
    assert reader[1][2] == "TEST_PACS"
    assert reader[1][3] == "Accepted"
    assert reader[1][4] == "Smith^Alice"
    assert reader[1][5] == "GSH-001"
    assert reader[1][6] == "ACC-001"
    assert reader[1][7] == "2.25.1001"
    assert reader[1][8] == "2.25.1001.1"
    assert reader[1][9] == "2.25.1001.1.1"
    assert reader[1][10] == "2048.00"


def test_audit_session_rejection_and_no_connection(tmp_path: Path):
    """Verify recording rejected, dropped, and no connection transfers."""
    session = CStoreAuditSession(
        destination_ae="OFFLINE_SCP",
        csv_dir=tmp_path,
        start_time=datetime(2026, 10, 17, 15, 0, 0, tzinfo=timezone.utc),
    )

    session.add_record(
        status="No Connection",
        patient_name="Unknown",
        patient_id="GSH-999",
        accession_number="ACC-999",
        study_uid="2.25.9999",
    )
    session.add_record(
        status="Rejected",
        patient_name="Jones^Bob",
        patient_id="GSH-002",
        accession_number="ACC-002",
        study_uid="2.25.2002",
    )
    session.add_record(
        status="Dropped",
        patient_name="Jones^Bob",
        patient_id="GSH-002",
        accession_number="ACC-002",
        study_uid="2.25.2002",
    )

    custom_path = tmp_path / "custom_audit.csv"
    session.write_csv(custom_path)
    assert custom_path.exists()

    with open(custom_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    assert len(rows) == 4
    statuses = [r[3] for r in rows[1:]]
    assert statuses == ["No Connection", "Rejected", "Dropped"]
