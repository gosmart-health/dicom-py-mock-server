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
from dicom_py_mock_server.services.scp import DicomScpService


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
            self.ae.add_supported_context(cx.abstract_syntax)
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
            ae.add_requested_context(cx.abstract_syntax)
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
