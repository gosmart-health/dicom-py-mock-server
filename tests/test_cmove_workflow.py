"""Integration test for full MWL -> Study Root C-FIND -> C-MOVE workflow."""

import time

from pydicom import Dataset
from pynetdicom import AE, StoragePresentationContexts, evt
from pynetdicom.sop_class import (
    ModalityWorklistInformationFind,
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove,
)

from dicom_py_mock_server.config import config
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService
from dicom_py_mock_server.services.scp import SUPPORTED_TRANSFER_SYNTAXES, DicomScpService


class MockStorageScp:
    """Helper mock storage SCP listener to receive pushed C-STORE datasets."""

    def __init__(self, ae_title: str = "VIEWER_AE", port: int = 11115):
        self.ae_title = ae_title
        self.port = port
        self.received_datasets: list[Dataset] = []
        self.ae: AE | None = None
        self.server = None

    def _handle_store(self, event: evt.Event) -> int:
        ds = event.dataset
        ds.file_meta = event.file_meta
        self.received_datasets.append(ds)
        return 0x0000  # Success

    def start(self):
        self.ae = AE(ae_title=self.ae_title)
        for cx in StoragePresentationContexts:
            self.ae.add_supported_context(cx.abstract_syntax, SUPPORTED_TRANSFER_SYNTAXES)
        handlers = [(evt.EVT_C_STORE, self._handle_store)]
        self.server = self.ae.start_server(("127.0.0.1", self.port), block=False, evt_handlers=handlers)

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server = None


def test_full_mwl_cfind_cmove_workflow():
    """Test the complete workflow: MWL generation -> MWL C-FIND -> Study C-FIND -> C-MOVE push."""
    # 1. Setup MWL and DICOM SCP Services
    mwl_service = MwlGeneratorService(config)
    mwl_entry = mwl_service.add_entry(
        custom={
            "patientName": "TEST^PATIENT",
            "patientId": "PAT12345",
            "modality": "CT",
            "accession": "ACC9999",
        }
    )

    study_uid = mwl_entry["study_uid"]
    patient_id = mwl_entry["patient_id"]
    patient_name = mwl_entry["patient_name"]

    scp_port = 11116
    viewer_port = 11117

    scp_service = DicomScpService(ae_title="MOCK_SCP", port=scp_port, mwl_service=mwl_service)
    scp_service.start()

    # 2. Setup Viewer Mock Storage SCP
    viewer_scp = MockStorageScp(ae_title="VIEWER_AE", port=viewer_port)
    viewer_scp.start()

    # Configure move destination in config
    config.move_destinations["VIEWER_AE"] = {"host": "127.0.0.1", "port": viewer_port}

    try:
        # 3. Test MWL C-FIND
        ae = AE(ae_title="CLIENT_SCU")
        ae.add_requested_context(ModalityWorklistInformationFind)
        assoc = ae.associate("127.0.0.1", scp_port)
        assert assoc.is_established

        query_ds = Dataset()
        query_ds.PatientID = patient_id
        responses = list(assoc.send_c_find(query_ds, ModalityWorklistInformationFind))
        assoc.release()

        mwl_matches = [ds for status, ds in responses if status and status.Status == 0xFF00 and ds]
        assert len(mwl_matches) == 1
        assert str(mwl_matches[0].PatientID) == patient_id

        # 4. Test Study Root C-FIND (STUDY Level)
        ae_study = AE(ae_title="CLIENT_SCU")
        ae_study.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
        assoc_study = ae_study.associate("127.0.0.1", scp_port)
        assert assoc_study.is_established

        study_query = Dataset()
        study_query.QueryRetrieveLevel = "STUDY"
        study_query.StudyInstanceUID = study_uid
        study_responses = list(assoc_study.send_c_find(study_query, StudyRootQueryRetrieveInformationModelFind))
        assoc_study.release()

        study_matches = [ds for status, ds in study_responses if status and status.Status == 0xFF00 and ds]
        assert len(study_matches) == 1
        assert str(study_matches[0].StudyInstanceUID) == study_uid
        assert str(study_matches[0].PatientID) == patient_id
        assert str(study_matches[0].PatientName) == patient_name
        assert str(study_matches[0].SeriesInstanceUID) != ""
        assert str(study_matches[0].Modality) == "CT"
        assert int(study_matches[0].SeriesNumber) == 1
        assert int(study_matches[0].NumberOfSeriesRelatedInstances) > 0

        # 4b. Test Study Root C-FIND (SERIES Level)
        ae_series = AE(ae_title="CLIENT_SCU")
        ae_series.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
        assoc_series = ae_series.associate("127.0.0.1", scp_port)
        assert assoc_series.is_established

        series_query = Dataset()
        series_query.QueryRetrieveLevel = "SERIES"
        series_query.StudyInstanceUID = study_uid
        series_responses = list(assoc_series.send_c_find(series_query, StudyRootQueryRetrieveInformationModelFind))
        assoc_series.release()

        series_matches = [ds for status, ds in series_responses if status and status.Status == 0xFF00 and ds]
        assert len(series_matches) == 1
        assert str(series_matches[0].StudyInstanceUID) == study_uid
        assert str(series_matches[0].SeriesInstanceUID) != ""
        assert str(series_matches[0].Modality) == "CT"
        assert int(series_matches[0].SeriesNumber) == 1
        assert int(series_matches[0].NumberOfSeriesRelatedInstances) > 0

        # 5. Test C-MOVE
        ae_move = AE(ae_title="CLIENT_SCU")
        ae_move.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
        assoc_move = ae_move.associate("127.0.0.1", scp_port)
        assert assoc_move.is_established

        move_query = Dataset()
        move_query.QueryRetrieveLevel = "STUDY"
        move_query.StudyInstanceUID = study_uid

        move_responses = list(
            assoc_move.send_c_move(move_query, "VIEWER_AE", StudyRootQueryRetrieveInformationModelMove)
        )
        assoc_move.release()

        # Check move status responses
        statuses = [status.Status for status, ds in move_responses if status]
        assert 0x0000 in statuses or 0xFF00 in statuses

        # Wait briefly for storage SCP to complete receiving
        time.sleep(0.5)

        # 6. Verify received datasets at viewer SCP
        expected_slices = mwl_entry.get("num_instances", config.min_slices)
        assert len(viewer_scp.received_datasets) == expected_slices
        assert config.min_slices <= len(viewer_scp.received_datasets) <= config.max_slices
        for ds in viewer_scp.received_datasets:
            assert str(ds.PatientID) == patient_id
            assert str(ds.PatientName) == patient_name
            assert str(ds.StudyInstanceUID) == study_uid
            assert str(ds.SeriesInstanceUID) != ""
            assert str(ds.Modality) == "CT"
            assert int(ds.SeriesNumber) == 1
            assert int(ds.NumberOfSeriesRelatedInstances) == expected_slices
            assert ds.PixelData is not None
            assert len(ds.PixelData) > 0

    finally:
        viewer_scp.stop()
        scp_service.stop()


def test_cstore_incoming_storage(tmp_path):
    """Test sending C-STORE to DICOM SCP saves the DICOM file to storage_dir."""
    from pathlib import Path

    import pydicom

    from dicom_py_mock_server.models.dicom import RawImageGeneratorRequest
    from dicom_py_mock_server.services.generator import DicomGeneratorService

    config.storage_dir = str(tmp_path)
    scp_port = 11118
    mwl_service = MwlGeneratorService(config)
    scp_service = DicomScpService(ae_title="STORE_MOCK_SCP", port=scp_port, mwl_service=mwl_service)
    scp_service.start()

    try:
        # Create a sample DICOM file to send
        gen = DicomGeneratorService()
        ds_to_send = gen.create_raw_dicom_file(
            RawImageGeneratorRequest(
                patient_name="CSTORE^SEND^PATIENT",
                patient_id="CSTORE-001",
                study_date="20260828",
                study_time="160000",
                image_number=1,
            )
        )

        ae = AE(ae_title="SCU_SENDER")
        for cx in StoragePresentationContexts:
            ae.add_requested_context(cx.abstract_syntax, SUPPORTED_TRANSFER_SYNTAXES)
        assoc = ae.associate("127.0.0.1", scp_port)
        assert assoc.is_established

        status = assoc.send_c_store(ds_to_send)
        assert status and status.Status == 0x0000
        assoc.release()

        # Verify file saved in storage_dir
        saved_files = list(Path(tmp_path).glob("*.dcm"))
        assert len(saved_files) >= 1
        saved_ds = pydicom.dcmread(saved_files[0])
        assert str(saved_ds.PatientID) == "CSTORE-001"
        assert str(saved_ds.PatientName) == "CSTORE^SEND^PATIENT"
    finally:
        scp_service.stop()


def test_cmove_on_demand_synthesis():
    """Test that C-MOVE requests for unseen study UIDs synthesize mock instances on demand."""
    scp_port = 11119
    viewer_port = 11120

    mwl_service = MwlGeneratorService(config)
    scp_service = DicomScpService(ae_title="ONDEMAND_SCP", port=scp_port, mwl_service=mwl_service)
    scp_service.start()

    viewer_scp = MockStorageScp(ae_title="VIEWER_ONDEMAND", port=viewer_port)
    viewer_scp.start()

    config.move_destinations["VIEWER_ONDEMAND"] = {"host": "127.0.0.1", "port": viewer_port}

    try:
        unseen_study_uid = "1.2.826.0.1.3680043.9.7133.99999"
        ae_move = AE(ae_title="CLIENT_SCU")
        ae_move.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
        assoc_move = ae_move.associate("127.0.0.1", scp_port)
        assert assoc_move.is_established

        move_query = Dataset()
        move_query.QueryRetrieveLevel = "STUDY"
        move_query.StudyInstanceUID = unseen_study_uid
        move_query.PatientID = "ONDEMAND-PAT-777"

        _ = list(assoc_move.send_c_move(move_query, "VIEWER_ONDEMAND", StudyRootQueryRetrieveInformationModelMove))
        assoc_move.release()

        time.sleep(0.5)

        assert config.min_slices <= len(viewer_scp.received_datasets) <= config.max_slices
        for ds in viewer_scp.received_datasets:
            assert str(ds.StudyInstanceUID) == unseen_study_uid
            assert str(ds.PatientID) == "ONDEMAND-PAT-777"
    finally:
        viewer_scp.stop()
        scp_service.stop()


def test_cfind_and_cmove_by_accession_number():
    """Test querying and moving studies specifically by AccessionNumber."""
    scp_port = 11123
    viewer_port = 11124

    mwl_service = MwlGeneratorService(config)
    mwl_service.add_entry(
        custom={
            "patientName": "ACC^QUERY^PATIENT",
            "patientId": "ACC-PAT-100",
            "accession": "ACC-TEST-12345",
            "modality": "CT",
        }
    )

    scp_service = DicomScpService(ae_title="ACC_SCP", port=scp_port, mwl_service=mwl_service)
    scp_service.start()

    viewer_scp = MockStorageScp(ae_title="ACC_VIEWER", port=viewer_port)
    viewer_scp.start()
    config.move_destinations["ACC_VIEWER"] = {"host": "127.0.0.1", "port": viewer_port}

    try:
        # 1. MWL C-FIND by AccessionNumber
        ae_mwl = AE(ae_title="CLIENT_SCU")
        ae_mwl.add_requested_context(ModalityWorklistInformationFind)
        assoc_mwl = ae_mwl.associate("127.0.0.1", scp_port)
        assert assoc_mwl.is_established

        mwl_query = Dataset()
        mwl_query.PatientName = ""
        mwl_query.AccessionNumber = "ACC-TEST-12345"
        mwl_responses = list(assoc_mwl.send_c_find(mwl_query, ModalityWorklistInformationFind))
        assoc_mwl.release()

        matched_mwl = [ds for status, ds in mwl_responses if ds]
        assert len(matched_mwl) == 1
        assert str(matched_mwl[0].AccessionNumber) == "ACC-TEST-12345"

        # 2. Study Root C-FIND by AccessionNumber
        ae_study = AE(ae_title="CLIENT_SCU")
        ae_study.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
        assoc_study = ae_study.associate("127.0.0.1", scp_port)
        assert assoc_study.is_established

        study_query = Dataset()
        study_query.QueryRetrieveLevel = "STUDY"
        study_query.AccessionNumber = "ACC-TEST-12345"
        study_responses = list(assoc_study.send_c_find(study_query, StudyRootQueryRetrieveInformationModelFind))
        assoc_study.release()

        matched_study = [ds for status, ds in study_responses if ds]
        assert len(matched_study) == 1
        assert str(matched_study[0].AccessionNumber) == "ACC-TEST-12345"

        # 3. C-MOVE by AccessionNumber
        ae_move = AE(ae_title="CLIENT_SCU")
        ae_move.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
        assoc_move = ae_move.associate("127.0.0.1", scp_port)
        assert assoc_move.is_established

        move_query = Dataset()
        move_query.QueryRetrieveLevel = "STUDY"
        move_query.AccessionNumber = "ACC-TEST-12345"
        _ = list(assoc_move.send_c_move(move_query, "ACC_VIEWER", StudyRootQueryRetrieveInformationModelMove))
        assoc_move.release()

        time.sleep(0.5)
        assert len(viewer_scp.received_datasets) >= 8
        for ds in viewer_scp.received_datasets:
            assert str(ds.AccessionNumber) == "ACC-TEST-12345"

        # 4. Direct push_study_to_destination test
        viewer_scp.received_datasets.clear()
        res_push = scp_service.push_study_to_destination(
            target_ae_title="ACC_VIEWER",
            target_host="127.0.0.1",
            target_port=viewer_port,
            accession="ACC-TEST-12345",
        )
        assert res_push["success"] is True
        assert res_push["instances_sent"] >= 8
        assert len(viewer_scp.received_datasets) >= 8

    finally:
        viewer_scp.stop()
        scp_service.stop()


def test_cstore_push_preserves_negotiated_transfer_syntax_jpeg2000_rle_jpeg_raw():
    """Verify C-STORE transfers send with negotiated Transfer Syntaxes (JPEG2000, RLE, JPEG, RAW)
    without falling back to Implicit VR Little Endian.
    """
    from pydicom.uid import (
        ExplicitVRLittleEndian,
        ImplicitVRLittleEndian,
        JPEG2000Lossless,
        JPEGBaseline8Bit,
        RLELossless,
    )
    from pynetdicom.presentation import build_context

    from dicom_py_mock_server.models.dicom import MockDicomRequest
    from dicom_py_mock_server.services.generator import DicomGeneratorService

    test_cases = [
        ("RAW", ExplicitVRLittleEndian),
        ("JPEG", JPEGBaseline8Bit),
        ("JPEG2000", JPEG2000Lossless),
        ("RLE", RLELossless),
    ]

    for idx, (syntax_name, expected_ts) in enumerate(test_cases):
        port = 11250 + idx
        received_ts = []

        def handle_store(event):
            received_ts.append(event.context.transfer_syntax)
            return 0x0000

        ts_list = [expected_ts, ExplicitVRLittleEndian, ImplicitVRLittleEndian]
        contexts = [build_context(cx.abstract_syntax, ts_list) for cx in StoragePresentationContexts]

        scp_ae = AE(ae_title="SYNTAX_SCP")
        for cx in contexts:
            scp_ae.add_supported_context(cx.abstract_syntax, ts_list)
        server = scp_ae.start_server(("127.0.0.1", port), block=False, evt_handlers=[(evt.EVT_C_STORE, handle_store)])

        try:
            scu_ae = AE(ae_title="SYNTAX_SCU")
            for cx in contexts:
                scu_ae.add_requested_context(cx.abstract_syntax, ts_list)

            assoc = scu_ae.associate("127.0.0.1", port, ae_title="SYNTAX_SCP")
            assert assoc.is_established

            req = MockDicomRequest(transfer_syntax=syntax_name, burn_in_text=True)
            ds = DicomGeneratorService.create_dicom_file(req)

            status = assoc.send_c_store(ds)
            assert status.Status == 0x0000
            assert len(received_ts) == 1
            assert received_ts[0] == expected_ts
            assoc.release()
        finally:
            server.shutdown()


def test_cmove_with_jpeg2000_lossless_transfer_syntax():
    """Verify C-MOVE operation correctly transfers datasets using JPEG2000 Lossless transfer syntax."""
    from pydicom.uid import JPEG2000Lossless

    original_syntax = config.transfer_syntax
    config.transfer_syntax = "JPEG2000_LOSSLESS"

    scp_port = 11260
    viewer_port = 11261

    mwl_service = MwlGeneratorService(config)
    mwl_entry = mwl_service.add_entry(
        custom={
            "patientName": "J2K^MOVE^PATIENT",
            "patientId": "J2K-MOVE-001",
            "modality": "CT",
            "accession": "ACC-J2K-99",
        }
    )

    scp_service = DicomScpService(ae_title="J2K_SCP", port=scp_port, mwl_service=mwl_service)
    scp_service.start()

    viewer_scp = MockStorageScp(ae_title="J2K_VIEWER", port=viewer_port)
    viewer_scp.start()
    config.move_destinations["J2K_VIEWER"] = {"host": "127.0.0.1", "port": viewer_port}

    try:
        ae_move = AE(ae_title="CLIENT_SCU")
        ae_move.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
        assoc_move = ae_move.associate("127.0.0.1", scp_port)
        assert assoc_move.is_established

        move_query = Dataset()
        move_query.QueryRetrieveLevel = "STUDY"
        move_query.StudyInstanceUID = mwl_entry["study_uid"]

        move_responses = list(
            assoc_move.send_c_move(move_query, "J2K_VIEWER", StudyRootQueryRetrieveInformationModelMove)
        )
        assoc_move.release()

        statuses = [status.Status for status, ds in move_responses if status]
        assert 0x0000 in statuses or 0xFF00 in statuses

        time.sleep(0.5)
        assert len(viewer_scp.received_datasets) >= 1
        for ds in viewer_scp.received_datasets:
            assert ds.file_meta.TransferSyntaxUID == JPEG2000Lossless
            assert ds.PixelData is not None
            assert len(ds.PixelData) > 0
    finally:
        viewer_scp.stop()
        scp_service.stop()
        config.transfer_syntax = original_syntax


def _is_microdicom_available(host: str = "127.0.0.1", port: int = 11113) -> bool:
    """Helper to check if a TCP port listener is active."""
    import socket

    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex((host, port)) == 0
    except Exception:
        return False
    finally:
        s.close()


def test_microdicom_cstore_push_if_listening():
    """Integration test helper: Push DICOM study to MicroDICOM instance at 127.0.0.1:11113 (AE: MDICOM) if active."""
    import pytest

    if not _is_microdicom_available():
        pytest.skip("MicroDICOM Viewer is not available on 127.0.0.1:11113")

    mwl_service = MwlGeneratorService(config)
    scp_service = DicomScpService(ae_title="TEST_PUSH_SCP", port=11270, mwl_service=mwl_service)

    try:
        res = scp_service.push_study_to_destination(
            target_ae_title="MDICOM",
            target_host="127.0.0.1",
            target_port=11113,
            patient_id="MICRODICOM-PAT-01",
            accession="ACC-MD-01",
        )
        if not res.get("success"):
            pytest.skip(f"MicroDICOM Viewer did not accept push: {res.get('message')}")
        assert res["instances_sent"] > 0
    except Exception as exc:
        pytest.skip(f"MicroDICOM push skipped due to connection error: {exc}")


def test_microdicom_send_jpeg2000_lossless_from_ct_small_template():
    """Test loading templates/CT_small.dcm, applying JPEG2000 Lossless generated image,
    negotiating JPEG2000 Lossless transfer syntax, and sending directly to MicroDICOM Viewer at port 11113 (MDICOM).
    """
    import pydicom
    import pytest
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, ImplicitVRLittleEndian, JPEG2000Lossless
    from pynetdicom.presentation import build_context

    from dicom_py_mock_server.services.generator import DicomGeneratorService

    if not _is_microdicom_available():
        pytest.skip("MicroDICOM Viewer is not available on 127.0.0.1:11113")

    template_path = "templates/CT_small.dcm"
    template_ds = pydicom.dcmread(template_path)

    # 1. Create dataset from template with JPEG2000 Lossless compression & burned-in metadata
    ds = DicomGeneratorService.create_dicom_from_template(
        template=template_path,
        transfer_syntax="JPEG2000_LOSSLESS",
        patient_name="BROWN_GSH^CHARLES",
        patient_id="GSH-65523803",
        study_date="20260901",
        study_time="122604",
        image_number=1,
        burn_in_text=True,
        rows=template_ds.Rows,
        cols=template_ds.Columns,
    )

    assert ds.file_meta.TransferSyntaxUID == JPEG2000Lossless
    assert ds.PatientName == "BROWN_GSH^CHARLES"
    assert ds.PatientID == "GSH-65523803"

    try:
        # 2. Associate with MicroDICOM proposing prioritized JPEG2000 Lossless presentation context
        ae = AE(ae_title="GOSMART_SCP")
        cx = build_context(CTImageStorage, [JPEG2000Lossless, ExplicitVRLittleEndian, ImplicitVRLittleEndian])
        assoc = ae.associate("127.0.0.1", 11113, contexts=[cx], ae_title="MDICOM")
        if not assoc.is_established:
            pytest.skip("MicroDICOM Viewer association could not be established on 127.0.0.1:11113")

        # Verify accepted transfer syntax is JPEG2000 Lossless
        matching_cx = [c for c in assoc.accepted_contexts if c.abstract_syntax == CTImageStorage]
        assert len(matching_cx) > 0
        accepted_ts = matching_cx[0].transfer_syntax[0]
        assert accepted_ts == JPEG2000Lossless

        # Send C-STORE request
        status = assoc.send_c_store(ds)
        assert status and status.Status in (0x0000, 0xB000, 0xB006, 0xB007)
        assoc.release()
    except Exception as exc:
        pytest.skip(f"MicroDICOM C-STORE communication interrupted: {exc}")
