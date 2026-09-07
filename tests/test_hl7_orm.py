"""Unit and integration tests for HL7 v2 ORM^O01 parsing, MLLP server, and MWL integration."""

import asyncio

import pytest

from dicom_py_mock_server.config import AppConfig
from dicom_py_mock_server.services.generator import DicomGeneratorService
from dicom_py_mock_server.services.hl7_parser import (
    build_hl7_ack,
    extract_hl7_orm_fields,
    parse_hl7_message,
)
from dicom_py_mock_server.services.hl7_server import (
    MLLP_END_BLOCK,
    MLLP_START_BLOCK,
    Hl7MllpServer,
)
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService

SAMPLE_HL7_CT_ORM = (
    "MSH|^~\\&|EPIC|HOSPITAL|GOSMART_MWL|GOSMART_HOSP|20260907120000||ORM^O01|MSG-CT-001|P|2.3\r"
    "PID|1||TEST-PAT-8899^^^HOSPITAL||JOHNSON^ROBERT^M||19780312|M\r"
    "PV1|1|O||||||DOC101^CARTER^ALICE^MD\r"
    "ORC|NW|ORD-9901|ACC-CT-7788||||^^^20260907143000|||DOC101^CARTER^ALICE^MD\r"
    "OBR|1|ORD-9901|ACC-CT-7788|CT01^CT HEAD NON CONTRAST|||20260907143000||||||||DOC101^CARTER^ALICE^MD"
    "||||||||CT||||||Headache evaluation\r"
)

SAMPLE_HL7_MR_ORM = (
    "MSH|^~\\&|CERNER|CLINIC|GOSMART_MWL|GOSMART_HOSP|20260907121500||ORM^O01|MSG-MR-002|P|2.3\r"
    "PID|1||MRN-554433^^^CLINIC||DAVIS^EMILY^K||19901123|F\r"
    "PV1|1|O||||||DOC202^BROWN^DAVID^MD\r"
    "ORC|NW|ORD-9902|ACC-MR-1122||||^^^20260907150000|||DOC202^BROWN^DAVID^MD\r"
    "OBR|1|ORD-9902|ACC-MR-1122|MR01^MRI BRAIN ROUTINE|||20260907150000||||||||DOC202^BROWN^DAVID^MD"
    "||||||||MR||||||Seizure protocol\r"
)

SAMPLE_HL7_UNSUPPORTED_MODALITY_ORM = (
    "MSH|^~\\&|TEST_HIS|CLINIC|GOSMART_MWL|GOSMART_HOSP|20260907123000||ORM^O01|MSG-PET-003|P|2.3\r"
    "PID|1||PAT-PET-111^^^CLINIC||WHITE^SARAH||19650401|F\r"
    "ORC|NW|ORD-9903|ACC-PET-3344\r"
    "OBR|1|ORD-9903|ACC-PET-3344|PT01^PET WHOLE BODY||||||||||||||||||PET||||||Oncology scan\r"
)

SAMPLE_HL7_CANCEL_ORM = (
    "MSH|^~\\&|EPIC|HOSPITAL|GOSMART_MWL|GOSMART_HOSP|20260907124500||ORM^O01|MSG-CAN-004|P|2.3\r"
    "PID|1||TEST-PAT-8899^^^HOSPITAL||JOHNSON^ROBERT^M||19780312|M\r"
    "ORC|CA|ORD-9901|ACC-CT-7788\r"
    "OBR|1|ORD-9901|ACC-CT-7788|CT01^CT HEAD NON CONTRAST||||||||||||||||||CT\r"
)


@pytest.fixture
def test_config():
    """Create test configuration."""
    return AppConfig(
        templates_path="./templates",
        hl7_port=22575,
        mwl_window_hr=24,
    )


@pytest.fixture
def test_mwl_service(test_config):
    """Create isolated MWL service instance."""
    return MwlGeneratorService(app_config=test_config)


@pytest.fixture
def test_hl7_server(test_mwl_service, test_config):
    """Create isolated HL7 server instance."""
    return Hl7MllpServer(mwl_service=test_mwl_service, app_config=test_config)


def test_hl7_parser_extracts_correct_fields():
    """Verify parsing of ORM^O01 extracts exact patient demographics and procedure tags."""
    msg = parse_hl7_message(SAMPLE_HL7_CT_ORM)
    fields = extract_hl7_orm_fields(msg)

    assert fields["patient_id"] == "TEST-PAT-8899"
    assert fields["patient_name"] == "JOHNSON^ROBERT^M"
    assert fields["dob"] == "19780312"
    assert fields["sex"] == "M"
    assert fields["accession"] == "ACC-CT-7788"
    assert fields["modality"] == "CT"
    assert "CT HEAD" in fields["study_description"]
    assert fields["order_control"] == "NW"
    assert fields["referring_physician"] == "CARTER^ALICE"
    assert fields["message_control_id"] == "MSG-CT-001"


def test_hl7_ack_construction():
    """Verify HL7 ACK generation matches standard MSH/MSA formatting."""
    fields = {
        "message_control_id": "MSG-999",
        "sending_application": "EPIC",
        "sending_facility": "HOSPITAL",
    }
    ack_aa = build_hl7_ack(fields, ack_code="AA", text_message="Order accepted")
    assert "MSA|AA|MSG-999|Order accepted" in ack_aa
    assert "MSH|^~\\&|GOSMART_MWL|GOSMART_HOSP|EPIC|HOSPITAL|" in ack_aa

    ack_ae = build_hl7_ack(fields, ack_code="AE", text_message="Modality rejected")
    assert "MSA|AE|MSG-999|Modality rejected" in ack_ae


def test_hl7_server_creates_mwl_without_demographic_alteration(test_hl7_server, test_mwl_service):
    """Verify that receiving an HL7 order creates an MWL item with the EXACT demographic values."""
    summary, ack = test_hl7_server.process_raw_message(SAMPLE_HL7_CT_ORM)

    assert summary["status"] == "created"
    assert "MSA|AA|MSG-CT-001" in ack

    # Check MWL active list
    matched = test_mwl_service.find_entries(accession="ACC-CT-7788")
    assert len(matched) == 1
    entry = matched[0]

    # Verify no _GSH suffix or GSH- prefix was added to raw HL7 inputs
    assert entry["patient_name"] == "JOHNSON^ROBERT^M"
    assert "_GSH" not in entry["patient_name"]
    assert entry["patient_id"] == "TEST-PAT-8899"
    assert not entry["patient_id"].startswith("GSH-")
    assert entry["accession"] == "ACC-CT-7788"
    assert entry["modality"] == "CT"


def test_hl7_server_mr_modality_creation(test_hl7_server, test_mwl_service):
    """Verify that MR orders are accepted since templates/sample_mr exists."""
    summary, ack = test_hl7_server.process_raw_message(SAMPLE_HL7_MR_ORM)

    assert summary["status"] == "created"
    assert "MSA|AA|MSG-MR-002" in ack

    matched = test_mwl_service.find_entries(accession="ACC-MR-1122")
    assert len(matched) == 1
    assert matched[0]["modality"] == "MR"
    assert matched[0]["patient_name"] == "DAVIS^EMILY^K"


def test_hl7_server_rejects_unsupported_modality(test_hl7_server, test_mwl_service):
    """Verify that an order for a modality without template images (PET) is logged and rejected."""
    summary, ack = test_hl7_server.process_raw_message(SAMPLE_HL7_UNSUPPORTED_MODALITY_ORM)

    assert summary["status"] == "rejected"
    assert "Rejected: No template images available for modality 'PET'" in summary["error"]
    assert "MSA|AE|MSG-PET-003" in ack
    assert "No template images available for modality 'PET'" in ack

    # Ensure it was NOT added to the MWL
    matched = test_mwl_service.find_entries(accession="ACC-PET-3344")
    assert len(matched) == 0


def test_hl7_order_cancellation(test_hl7_server, test_mwl_service):
    """Verify that ORC-1 = CA removes the active MWL entry."""
    # 1. First add the order
    test_hl7_server.process_raw_message(SAMPLE_HL7_CT_ORM)
    assert len(test_mwl_service.find_entries(accession="ACC-CT-7788")) == 1

    # 2. Send cancellation message
    summary, ack = test_hl7_server.process_raw_message(SAMPLE_HL7_CANCEL_ORM)
    assert summary["status"] == "cancelled"
    assert summary["removed_entries"] >= 1
    assert "MSA|AA|MSG-CAN-004" in ack

    # 3. Confirm entry was removed
    assert len(test_mwl_service.find_entries(accession="ACC-CT-7788")) == 0


def test_downstream_dicom_synthesis_from_hl7_mwl(test_hl7_server, test_mwl_service):
    """Verify the full circuit: HL7 order -> MWL entry -> DicomGeneratorService instance synthesis."""
    test_hl7_server.process_raw_message(SAMPLE_HL7_CT_ORM)
    matched = test_mwl_service.find_entries(accession="ACC-CT-7788")
    assert len(matched) == 1
    mwl_record = matched[0]

    # Synthesize DICOM instances as would happen during C-MOVE or DICOMweb WADO-RS
    instances = DicomGeneratorService.create_instances_from_mwl(mwl_record, num_instances=2)
    assert len(instances) == 2

    for ds in instances:
        assert str(ds.PatientName) == "JOHNSON^ROBERT^M"
        assert str(ds.PatientID) == "TEST-PAT-8899"
        assert str(ds.AccessionNumber) == "ACC-CT-7788"
        assert str(ds.Modality) == "CT"
        assert hasattr(ds, "PixelData")
        assert len(ds.PixelData) > 0


def test_mllp_socket_end_to_end(test_hl7_server, test_mwl_service):
    """Verify live TCP client sending MLLP frame and receiving MLLP ACK frame."""

    async def _run():
        await test_hl7_server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", test_hl7_server.port)

            # Send framed MLLP message
            mllp_request = MLLP_START_BLOCK + SAMPLE_HL7_CT_ORM.encode("utf-8") + MLLP_END_BLOCK
            writer.write(mllp_request)
            await writer.drain()

            # Read MLLP ACK response
            response_bytes = await reader.readuntil(MLLP_END_BLOCK)
            assert response_bytes.startswith(MLLP_START_BLOCK)
            assert response_bytes.endswith(MLLP_END_BLOCK)

            ack_content = response_bytes[len(MLLP_START_BLOCK) : -len(MLLP_END_BLOCK)].decode("utf-8")
            assert "MSA|AA|MSG-CT-001" in ack_content

            writer.close()
            await writer.wait_closed()

            # Check MWL entry exists
            assert len(test_mwl_service.find_entries(accession="ACC-CT-7788")) == 1

        finally:
            await test_hl7_server.stop()

    asyncio.run(_run())
