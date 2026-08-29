"""Service for managing DICOM SCP server using pynetdicom."""

from pathlib import Path
from typing import Any

import structlog
from pydicom.uid import generate_uid
from pynetdicom import AE, StoragePresentationContexts, evt
from pynetdicom.sop_class import (
    ModalityWorklistInformationFind,
    PatientRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelMove,
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove,
    Verification,
)

from dicom_py_mock_server.config import config
from dicom_py_mock_server.models.dicom import ScpStatusResponse
from dicom_py_mock_server.services.generator import DicomGeneratorService

logger = structlog.get_logger(__name__)


class DicomScpService:
    """Manager for pynetdicom Application Entity (AE) DICOM SCP service."""

    def __init__(
        self,
        ae_title: str = "MOCK_SCP",
        port: int = 11112,
        mwl_service=None,
    ) -> None:
        self.ae_title = ae_title
        self.port = port
        self.mwl_service = mwl_service
        self.ae: AE | None = None
        self.server = None
        self.is_running = False

    def _handle_echo(self, event: evt.Event) -> int:
        """Handle C-ECHO request."""
        requestor_ae = getattr(event.assoc.requestor, "ae_title", "UNKNOWN") if event.assoc else "UNKNOWN"
        logger.info("dicom_c_echo_received", requestor_ae=requestor_ae)
        return 0x0000  # Success

    def _handle_find(self, event: evt.Event):
        """Handle C-FIND request for MWL and Study Root models."""
        requestor_ae = getattr(event.assoc.requestor, "ae_title", "UNKNOWN") if event.assoc else "UNKNOWN"
        sop_class = str(getattr(event.request, "AffectedSOPClassUID", ""))
        logger.info("dicom_c_find_received", requestor_ae=requestor_ae, sop_class=sop_class)

        if not self.mwl_service:
            yield (0x0000, None)
            return

        identifier = getattr(event, "identifier", None)

        if sop_class == str(ModalityWorklistInformationFind) or "4.31" in sop_class:
            # Modality Worklist C-FIND
            study_uid = (
                str(identifier.get("StudyInstanceUID", ""))
                if identifier and "StudyInstanceUID" in identifier and identifier.StudyInstanceUID
                else None
            )
            patient_id = (
                str(identifier.get("PatientID", ""))
                if identifier and "PatientID" in identifier and identifier.PatientID
                else None
            )
            accession = (
                str(identifier.get("AccessionNumber", ""))
                if identifier and "AccessionNumber" in identifier and identifier.AccessionNumber
                else None
            )

            if study_uid or patient_id or accession:
                matched_entries = self.mwl_service.find_entries(
                    study_uid=study_uid, patient_id=patient_id, accession=accession
                )
                for entry in matched_entries:
                    yield (0xFF00, entry["dataset"])
            else:
                for ds in self.mwl_service.get_datasets():
                    yield (0xFF00, ds)

            yield (0x0000, None)
        else:
            # Study Root / Patient Root C-FIND
            study_uid = (
                str(identifier.get("StudyInstanceUID", ""))
                if identifier and "StudyInstanceUID" in identifier and identifier.StudyInstanceUID
                else None
            )
            patient_id = (
                str(identifier.get("PatientID", ""))
                if identifier and "PatientID" in identifier and identifier.PatientID
                else None
            )
            accession = (
                str(identifier.get("AccessionNumber", ""))
                if identifier and "AccessionNumber" in identifier and identifier.AccessionNumber
                else None
            )

            matched_entries = self.mwl_service.find_entries(
                study_uid=study_uid, patient_id=patient_id, accession=accession
            )
            if not matched_entries and not study_uid and not patient_id and not accession:
                # If no specific key passed, return all active MWL entries converted to Study C-FIND responses
                self.mwl_service.purge_expired_entries()
                matched_entries = self.mwl_service._entries

            for entry in matched_entries:
                cfind_ds = self.mwl_service.to_study_cfind_dataset(entry)
                yield (0xFF00, cfind_ds)

            yield (0x0000, None)

    def _handle_move(self, event: evt.Event):
        """Handle C-MOVE request and push DICOM image instances to move destination."""
        move_destination = event.move_destination
        requestor_ae = getattr(event.assoc.requestor, "ae_title", "UNKNOWN") if event.assoc else "UNKNOWN"
        requestor_address = getattr(event.assoc.requestor, "address", "127.0.0.1") if event.assoc else "127.0.0.1"

        logger.info(
            "dicom_c_move_received",
            requestor_ae=requestor_ae,
            move_destination=move_destination,
            requestor_address=requestor_address,
        )

        # Resolve destination IP and port
        dest_info = config.move_destinations.get(move_destination)
        if dest_info:
            addr = dest_info.get("host", requestor_address)
            port = int(dest_info.get("port", 11113))
        else:
            addr = requestor_address
            port = 11113

        if not addr or not port:
            logger.error("dicom_c_move_destination_unknown", move_destination=move_destination)
            yield (None, None)
            return

        # 1st yield: (addr, port, kwargs) including Storage presentation contexts for outgoing C-STORE association
        yield (addr, port, {"contexts": StoragePresentationContexts})

        identifier = getattr(event, "identifier", None)
        study_uid = (
            str(identifier.get("StudyInstanceUID", ""))
            if identifier and "StudyInstanceUID" in identifier and identifier.StudyInstanceUID
            else None
        )
        patient_id = (
            str(identifier.get("PatientID", ""))
            if identifier and "PatientID" in identifier and identifier.PatientID
            else None
        )
        accession = (
            str(identifier.get("AccessionNumber", ""))
            if identifier and "AccessionNumber" in identifier and identifier.AccessionNumber
            else None
        )

        matched_entries = []
        if self.mwl_service:
            matched_entries = self.mwl_service.find_entries(
                study_uid=study_uid, patient_id=patient_id, accession=accession
            )
            if not matched_entries and not study_uid and not patient_id and not accession:
                self.mwl_service.purge_expired_entries()
                matched_entries = self.mwl_service._entries
            elif not matched_entries and (study_uid or patient_id or accession):
                # Dynamically synthesize a mock study matching the requested query parameters
                new_entry = self.mwl_service.add_entry(
                    custom={
                        "studyUid": study_uid,
                        "patientId": patient_id,
                        "accession": accession,
                    }
                )
                matched_entries = [new_entry]

        if not matched_entries:
            logger.warning("dicom_c_move_no_matching_studies", study_uid=study_uid, patient_id=patient_id)
            yield 0
            return

        all_datasets = []
        for entry in matched_entries:
            datasets = DicomGeneratorService.create_instances_from_mwl(entry)
            all_datasets.extend(datasets)

        total_instances = len(all_datasets)
        # 2nd yield: total sub-operations count
        yield total_instances

        # 3rd+ yields: (status, dataset) pairs
        for idx, ds in enumerate(all_datasets, 1):
            if event.is_cancelled:
                logger.warning("dicom_c_move_cancelled")
                yield (0xFE00, None)
                return

            patient_name = str(getattr(ds, "PatientName", ""))
            patient_id_val = str(getattr(ds, "PatientID", ""))
            study_inst_uid = str(getattr(ds, "StudyInstanceUID", ""))
            series_inst_uid = str(getattr(ds, "SeriesInstanceUID", ""))
            sop_inst_uid = str(getattr(ds, "SOPInstanceUID", ""))
            instance_num = int(getattr(ds, "InstanceNumber", idx))

            logger.info(
                "dicom_c_store_instance_pushed",
                patient_name=patient_name,
                patient_id=patient_id_val,
                study_instance_uid=study_inst_uid,
                series_instance_uid=series_inst_uid,
                sop_instance_uid=sop_inst_uid,
                instance_number=f"{instance_num}/{total_instances}",
                move_destination=move_destination,
                dest_host=addr,
                dest_port=port,
            )

            yield (0xFF00, ds)

    def _handle_store(self, event: evt.Event) -> int:
        """Handle incoming C-STORE request and save DICOM file to storage_dir."""
        requestor_ae = getattr(event.assoc.requestor, "ae_title", "UNKNOWN") if event.assoc else "UNKNOWN"
        logger.info("dicom_c_store_received", requestor_ae=requestor_ae)
        try:
            ds = event.dataset
            ds.file_meta = event.file_meta
            out_dir = Path(config.storage_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            sop_uid = (
                getattr(ds, "SOPInstanceUID", None)
                or getattr(event.file_meta, "MediaStorageSOPInstanceUID", None)
                or generate_uid()
            )
            file_path = out_dir / f"stored_{sop_uid}.dcm"
            ds.save_as(file_path, enforce_file_format=True)
            logger.info("dicom_c_store_saved", path=str(file_path), sop_instance_uid=str(sop_uid))
        except Exception as exc:
            logger.warning("dicom_c_store_save_failed", error=str(exc))
        return 0x0000  # Success

    def start(self, host: str = "0.0.0.0") -> ScpStatusResponse:
        """Start the DICOM SCP server in non-blocking mode."""
        if self.is_running and self.server:
            return self.get_status()

        self.ae = AE(ae_title=self.ae_title)

        # Supported Presentation Contexts
        self.ae.add_supported_context(Verification)
        self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelFind)
        self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
        self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelMove)
        self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelMove)
        self.ae.add_supported_context(ModalityWorklistInformationFind)
        for cx in StoragePresentationContexts:
            self.ae.add_supported_context(cx.abstract_syntax)
            self.ae.add_requested_context(cx.abstract_syntax)

        handlers = [
            (evt.EVT_C_ECHO, self._handle_echo),
            (evt.EVT_C_FIND, self._handle_find),
            (evt.EVT_C_MOVE, self._handle_move),
            (evt.EVT_C_STORE, self._handle_store),
        ]

        self.server = self.ae.start_server((host, self.port), block=False, evt_handlers=handlers)
        self.is_running = True
        logger.info("dicom_scp_server_started", host=host, port=self.port, ae_title=self.ae_title)
        return self.get_status()

    def stop(self) -> ScpStatusResponse:
        """Stop the DICOM SCP server."""
        if self.server:
            self.server.shutdown()
            self.server = None
        self.is_running = False
        logger.info("dicom_scp_server_stopped", ae_title=self.ae_title)
        return self.get_status()

    def get_status(self) -> ScpStatusResponse:
        """Get current status of DICOM SCP server."""
        return ScpStatusResponse(
            ae_title=self.ae_title,
            port=self.port,
            is_running=self.is_running,
            supported_services=["C-ECHO", "C-FIND", "C-MOVE", "C-STORE", "MWL-FIND"],
        )

    def push_study_to_destination(
        self,
        target_ae_title: str,
        target_host: str = "127.0.0.1",
        target_port: int = 11113,
        patient_id: str | None = None,
        accession: str | None = None,
        study_uid: str | None = None,
    ) -> dict[str, Any]:
        """Push a study (matching patient_id, accession, or study_uid) to a target DICOM Storage SCP."""
        matched_entries = []
        if self.mwl_service:
            matched_entries = self.mwl_service.find_entries(
                study_uid=study_uid, patient_id=patient_id, accession=accession
            )
            if not matched_entries and not study_uid and not patient_id and not accession:
                self.mwl_service.purge_expired_entries()
                matched_entries = self.mwl_service._entries
            elif not matched_entries and (study_uid or patient_id or accession):
                # Dynamically synthesize on demand
                new_entry = self.mwl_service.add_entry(
                    custom={
                        "studyUid": study_uid,
                        "patientId": patient_id,
                        "accession": accession,
                    }
                )
                matched_entries = [new_entry]

        if not matched_entries:
            return {
                "success": False,
                "message": "No studies found matching query criteria to move",
                "instances_sent": 0,
                "target_ae_title": target_ae_title,
                "target_host": target_host,
                "target_port": target_port,
            }

        all_datasets = []
        for entry in matched_entries:
            datasets = DicomGeneratorService.create_instances_from_mwl(entry)
            all_datasets.extend(datasets)

        # Connect as SCU to target
        ae = AE(ae_title=self.ae_title)
        for cx in StoragePresentationContexts:
            ae.add_requested_context(cx.abstract_syntax)

        assoc = ae.associate(target_host, target_port, ae_title=target_ae_title)
        if not assoc.is_established:
            err_msg = (
                f"Failed to establish association with target AE '{target_ae_title}' at {target_host}:{target_port}"
            )
            logger.error(
                "dicom_move_push_association_failed",
                target_ae=target_ae_title,
                host=target_host,
                port=target_port,
            )
            return {
                "success": False,
                "message": err_msg,
                "instances_sent": 0,
                "target_ae_title": target_ae_title,
                "target_host": target_host,
                "target_port": target_port,
            }

        sent_count = 0
        try:
            for ds in all_datasets:
                status = assoc.send_c_store(ds)
                if status and status.Status in (0x0000, 0xB000, 0xB006, 0xB007):
                    sent_count += 1
                else:
                    logger.warning("dicom_c_store_push_failed", status=hex(status.Status) if status else "None")
        finally:
            assoc.release()

        first_entry = matched_entries[0]
        return {
            "success": True,
            "message": f"Successfully moved {sent_count} instances to {target_ae_title} ({target_host}:{target_port})",
            "instances_sent": sent_count,
            "patient_id": first_entry.get("patient_id"),
            "patient_name": first_entry.get("patient_name"),
            "accession": first_entry.get("accession"),
            "study_instance_uid": first_entry.get("study_uid"),
            "target_ae_title": target_ae_title,
            "target_host": target_host,
            "target_port": target_port,
        }
