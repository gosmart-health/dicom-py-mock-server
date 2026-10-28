"""Service for managing DICOM SCP server using pynetdicom."""

import threading
from pathlib import Path
from typing import Any

import structlog
from pydicom.dataset import Dataset
from pydicom.uid import (
    JPEG2000,
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
    JPEG2000Lossless,
    JPEGBaseline8Bit,
    RLELossless,
)
from pynetdicom import AE, StoragePresentationContexts, evt
from pynetdicom.presentation import build_context
from pynetdicom.sop_class import (
    ModalityWorklistInformationFind,
    PatientRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelGet,
    PatientRootQueryRetrieveInformationModelMove,
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelGet,
    StudyRootQueryRetrieveInformationModelMove,
    Verification,
)

from dicom_py_mock_server.config import config
from dicom_py_mock_server.models.dicom import ScpStatusResponse
from dicom_py_mock_server.services.generator import (
    DicomGeneratorService,
    resolve_transfer_syntax,
)
from dicom_py_mock_server.services.uid_generator import generate_dicom_uid

logger = structlog.get_logger(__name__)


def get_prioritized_transfer_syntaxes(preferred_syntax: str | None = None) -> list[Any]:
    """Get list of supported transfer syntaxes ordered with the preferred syntax first."""
    raw_pref = str(preferred_syntax or getattr(config, "transfer_syntax", "JPEG2000_LOSSLESS")).strip()
    pref = raw_pref.upper()

    all_syntaxes = [
        JPEG2000Lossless,
        JPEG2000,
        RLELossless,
        JPEGBaseline8Bit,
        ExplicitVRLittleEndian,
        ImplicitVRLittleEndian,
    ]

    pref_uid = None
    for ts in all_syntaxes:
        if raw_pref == str(ts):
            pref_uid = ts
            break

    if pref_uid is None:
        if "JPEG2000_LOSSY" in pref:
            pref_uid = JPEG2000
        elif "JPEG2000" in pref:
            pref_uid = JPEG2000Lossless
        elif "JPEG" in pref:
            pref_uid = JPEGBaseline8Bit
        elif "RLE" in pref:
            pref_uid = RLELossless
        elif "RAW" in pref or "EXPLICIT" in pref:
            pref_uid = ExplicitVRLittleEndian
        elif "IMPLICIT" in pref:
            pref_uid = ImplicitVRLittleEndian
        else:
            resolved = resolve_transfer_syntax(raw_pref)
            if resolved in all_syntaxes:
                pref_uid = resolved

    if pref_uid and pref_uid in all_syntaxes:
        return [pref_uid] + [ts for ts in all_syntaxes if ts != pref_uid]
    return all_syntaxes


SUPPORTED_TRANSFER_SYNTAXES = get_prioritized_transfer_syntaxes()


def build_storage_contexts_for_datasets(
    datasets: list[Dataset] | None = None,
    preferred_syntax: str | None = None,
) -> list[Any]:
    """Build Storage presentation contexts proposing the exact transfer syntax of the datasets."""
    sop_to_syntaxes: dict[str, list[Any]] = {}
    first_ds_ts = None

    if datasets:
        for ds in datasets:
            sop_uid = str(getattr(ds, "SOPClassUID", ""))
            ds_ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
            if not ds_ts:
                ds_ts = ImplicitVRLittleEndian if getattr(ds, "is_implicit_VR", True) else ExplicitVRLittleEndian
            if first_ds_ts is None:
                first_ds_ts = ds_ts
            if sop_uid:
                ts_list = sop_to_syntaxes.setdefault(sop_uid, [])
                if ds_ts not in ts_list:
                    ts_list.append(ds_ts)

    if preferred_syntax is not None:
        default_ts = get_prioritized_transfer_syntaxes(preferred_syntax)[0]
    elif first_ds_ts is not None:
        default_ts = first_ds_ts
    else:
        default_ts = get_prioritized_transfer_syntaxes(config.transfer_syntax)[0]

    contexts: list[Any] = []
    seen_sops: set[str] = set()

    for cx in StoragePresentationContexts:
        abs_str = str(cx.abstract_syntax)
        seen_sops.add(abs_str)
        if preferred_syntax is None and abs_str in sop_to_syntaxes:
            contexts.append(build_context(cx.abstract_syntax, sop_to_syntaxes[abs_str]))
        else:
            contexts.append(build_context(cx.abstract_syntax, [default_ts]))

    for sop_str, ts_list in sop_to_syntaxes.items():
        if sop_str not in seen_sops:
            if len(contexts) >= 128:
                contexts.pop()
            contexts.insert(0, build_context(sop_str, [default_ts] if preferred_syntax is not None else ts_list))

    return contexts


def adapt_dataset_for_accepted_context(ds: Any, accepted_contexts: list[Any]) -> Any:
    """Adapt dataset transfer syntax to match the negotiated context accepted by the peer."""
    sop_class = getattr(ds, "SOPClassUID", None)
    if not sop_class:
        return ds

    ds_ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
    accepted_ts = None
    for cx in accepted_contexts:
        if cx.abstract_syntax == sop_class and cx.transfer_syntax:
            if ds_ts and ds_ts in cx.transfer_syntax:
                return ds
            if accepted_ts is None:
                accepted_ts = cx.transfer_syntax[0]

    if accepted_ts and ds_ts != accepted_ts:
        ds = DicomGeneratorService.apply_transfer_syntax(ds, str(accepted_ts))
    return ds


def _extract_identifier_tag(identifier: Any, tag_name: str) -> str | None:
    """Extract a tag string or backslash-joined multi-value string from a DICOM Identifier."""
    if identifier and tag_name in identifier:
        val = getattr(identifier, tag_name, None)
        if val is not None:
            if isinstance(val, (list, tuple)):
                joined = "\\".join(str(v).strip() for v in val if str(v).strip())
                return joined if joined else None
            val_str = str(val).strip()
            if val_str:
                return val_str
    return None


def _matches_uid_value(candidate: str, filter_val: str) -> bool:
    """Check if a UID matches a single UID or backslash-separated list of UIDs."""
    if not filter_val:
        return True
    parts = [p.strip() for p in str(filter_val).split("\\") if p.strip()]
    if not parts:
        return True
    return str(candidate).strip() in parts


class DicomScpService:
    """Manager for pynetdicom Application Entity (AE) DICOM SCP service."""

    def __init__(
        self,
        ae_title: str = "MOCK_SCP",
        port: int = 11112,
        mwl_service=None,
        dicomweb_service=None,
    ) -> None:
        self.ae_title = ae_title
        self.port = port
        self.mwl_service = mwl_service
        self.dicomweb_service = dicomweb_service
        self.ae: AE | None = None
        self.server = None
        self.is_running = False
        self.auto_push_ae: str = getattr(config, "auto_push_ae", "")
        self.auto_push_host: str = getattr(config, "auto_push_host", "127.0.0.1")
        self.auto_push_port: int = int(getattr(config, "auto_push_port", 11113))
        self.auto_push_sec: float = float(getattr(config, "auto_push_sec", 0.0))
        self._is_auto_pushing: bool = False
        self._auto_push_thread: threading.Thread | None = None
        self._auto_push_stop_event: threading.Event = threading.Event()
        self._auto_push_queue: list[dict[str, Any]] = []

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
            study_uid = _extract_identifier_tag(identifier, "StudyInstanceUID")
            series_uid = _extract_identifier_tag(identifier, "SeriesInstanceUID")
            sop_uid_filter = _extract_identifier_tag(identifier, "SOPInstanceUID")
            patient_id = _extract_identifier_tag(identifier, "PatientID")
            patient_name = _extract_identifier_tag(identifier, "PatientName")
            accession = _extract_identifier_tag(identifier, "AccessionNumber")
            study_date = _extract_identifier_tag(identifier, "StudyDate")
            modality = _extract_identifier_tag(identifier, "Modality") or _extract_identifier_tag(
                identifier, "ModalitiesInStudy"
            )
            study_description = _extract_identifier_tag(identifier, "StudyDescription")
            series_description = _extract_identifier_tag(identifier, "SeriesDescription")
            series_number = _extract_identifier_tag(identifier, "SeriesNumber")

            qr_level = "STUDY"
            if identifier and "QueryRetrieveLevel" in identifier and identifier.QueryRetrieveLevel:
                qr_level = str(identifier.QueryRetrieveLevel).strip().upper()
            elif sop_class == str(PatientRootQueryRetrieveInformationModelFind) and not study_uid and not series_uid:
                # Default to STUDY if not specified, unless only patient keys are present
                qr_level = "STUDY"

            matched_entries = self.mwl_service.find_study_series_entries(
                study_uid=study_uid,
                series_uid=series_uid,
                patient_id=patient_id,
                patient_name=patient_name,
                accession=accession,
                study_date=study_date,
                modality=modality,
                study_description=study_description,
                series_description=series_description,
                series_number=series_number,
            )

            all_known_entries = self.mwl_service.get_all_study_series_entries()

            seen_uids: set[str] = set()
            for entry in matched_entries:
                if qr_level == "PATIENT":
                    p_id = str(entry.get("patient_id", ""))
                    if p_id and p_id not in seen_uids:
                        seen_uids.add(p_id)
                        patient_entries = [e for e in all_known_entries if str(e.get("patient_id", "")) == p_id]
                        cfind_ds = self.mwl_service.to_patient_cfind_dataset(entry, related_entries=patient_entries)
                        yield (0xFF00, cfind_ds)
                elif qr_level == "SERIES":
                    s_uid = str(entry.get("series_uid", ""))
                    if s_uid and s_uid not in seen_uids:
                        seen_uids.add(s_uid)
                        cfind_ds = self.mwl_service.to_series_cfind_dataset(entry)
                        yield (0xFF00, cfind_ds)
                elif qr_level in ("IMAGE", "INSTANCE"):
                    image_datasets = self.mwl_service.to_image_cfind_datasets(entry)
                    for img_ds in image_datasets:
                        sop_uid = str(getattr(img_ds, "SOPInstanceUID", ""))
                        if sop_uid_filter and not (
                            self.mwl_service._matches_filter(sop_uid, sop_uid_filter)
                            or _matches_uid_value(sop_uid, sop_uid_filter)
                        ):
                            continue
                        if sop_uid and sop_uid not in seen_uids:
                            seen_uids.add(sop_uid)
                            yield (0xFF00, img_ds)
                else:
                    st_uid = str(entry.get("study_uid", ""))
                    if st_uid and st_uid not in seen_uids:
                        seen_uids.add(st_uid)
                        study_entries = [e for e in all_known_entries if str(e.get("study_uid", "")) == st_uid]
                        cfind_ds = self.mwl_service.to_study_cfind_dataset(entry, related_series_entries=study_entries)
                        yield (0xFF00, cfind_ds)

            # Query STOW-RS received instances
            if self.dicomweb_service and hasattr(self.dicomweb_service, "_stow_datasets"):
                for ds in self.dicomweb_service._stow_datasets.values():
                    if study_uid and not self.mwl_service._matches_filter(
                        getattr(ds, "StudyInstanceUID", ""), study_uid
                    ):
                        continue
                    if series_uid and not self.mwl_service._matches_filter(
                        getattr(ds, "SeriesInstanceUID", ""), series_uid
                    ):
                        continue
                    if patient_id and not self.mwl_service._matches_filter(getattr(ds, "PatientID", ""), patient_id):
                        continue
                    if patient_name and not self.mwl_service._matches_filter(
                        getattr(ds, "PatientName", ""), patient_name
                    ):
                        continue
                    if accession and not self.mwl_service._matches_filter(
                        getattr(ds, "AccessionNumber", ""), accession
                    ):
                        continue
                    if study_date and not self.mwl_service._matches_date_filter(
                        getattr(ds, "StudyDate", ""), study_date
                    ):
                        continue
                    if modality and not self.mwl_service._matches_filter(getattr(ds, "Modality", ""), modality):
                        continue

                    if qr_level == "PATIENT":
                        p_id = str(getattr(ds, "PatientID", ""))
                        if p_id and p_id not in seen_uids:
                            seen_uids.add(p_id)
                            out_ds = Dataset()
                            out_ds.QueryRetrieveLevel = "PATIENT"
                            out_ds.PatientID = p_id
                            out_ds.PatientName = getattr(ds, "PatientName", "")
                            out_ds.PatientBirthDate = getattr(ds, "PatientBirthDate", "")
                            out_ds.PatientSex = getattr(ds, "PatientSex", "")
                            yield (0xFF00, out_ds)
                    elif qr_level == "SERIES":
                        s_uid = str(getattr(ds, "SeriesInstanceUID", ""))
                        if s_uid and s_uid not in seen_uids:
                            seen_uids.add(s_uid)
                            out_ds = Dataset()
                            out_ds.QueryRetrieveLevel = "SERIES"
                            out_ds.StudyInstanceUID = getattr(ds, "StudyInstanceUID", "")
                            out_ds.SeriesInstanceUID = s_uid
                            out_ds.Modality = getattr(ds, "Modality", "OT")
                            out_ds.SeriesNumber = getattr(ds, "SeriesNumber", 1)
                            yield (0xFF00, out_ds)
                    elif qr_level in ("IMAGE", "INSTANCE"):
                        sop_uid = str(getattr(ds, "SOPInstanceUID", ""))
                        if sop_uid_filter and not (
                            self.mwl_service._matches_filter(sop_uid, sop_uid_filter)
                            or _matches_uid_value(sop_uid, sop_uid_filter)
                        ):
                            continue
                        if sop_uid and sop_uid not in seen_uids:
                            seen_uids.add(sop_uid)
                            yield (0xFF00, ds)
                    else:
                        st_uid = str(getattr(ds, "StudyInstanceUID", ""))
                        if st_uid and st_uid not in seen_uids:
                            seen_uids.add(st_uid)
                            out_ds = Dataset()
                            out_ds.QueryRetrieveLevel = "STUDY"
                            out_ds.StudyInstanceUID = st_uid
                            out_ds.PatientID = getattr(ds, "PatientID", "")
                            out_ds.PatientName = getattr(ds, "PatientName", "")
                            out_ds.StudyDate = getattr(ds, "StudyDate", "")
                            out_ds.AccessionNumber = getattr(ds, "AccessionNumber", "")
                            yield (0xFF00, out_ds)

            yield (0x0000, None)

    def _resolve_retrieve_datasets(
        self,
        study_uid: str | None = None,
        series_uid: str | None = None,
        sop_uid: str | None = None,
        patient_id: str | None = None,
        accession: str | None = None,
    ) -> list[Dataset]:
        """Resolve datasets matching C-MOVE or C-GET query parameters."""
        stow_matched: list[Dataset] = []
        if self.dicomweb_service and hasattr(self.dicomweb_service, "_stow_datasets"):
            for ds in self.dicomweb_service._stow_datasets.values():
                if study_uid and not _matches_uid_value(str(getattr(ds, "StudyInstanceUID", "")), study_uid):
                    continue
                if series_uid and not _matches_uid_value(str(getattr(ds, "SeriesInstanceUID", "")), series_uid):
                    continue
                if sop_uid and not _matches_uid_value(str(getattr(ds, "SOPInstanceUID", "")), sop_uid):
                    continue
                if patient_id and str(getattr(ds, "PatientID", "")) != str(patient_id):
                    continue
                if accession and str(getattr(ds, "AccessionNumber", "")) != str(accession):
                    continue
                stow_matched.append(ds)

        if stow_matched:
            return stow_matched

        matched_entries: list[dict[str, Any]] = []
        if self.mwl_service:
            matched_entries = self.mwl_service.find_study_series_entries(
                study_uid=study_uid, series_uid=series_uid, patient_id=patient_id, accession=accession
            )
            if not matched_entries and (study_uid or patient_id or accession):
                # Dynamically synthesize a mock study matching the requested query parameters
                new_entry = self.mwl_service.add_entry(
                    custom={
                        "studyUid": study_uid,
                        "patientId": patient_id,
                        "accession": accession,
                    }
                )
                matched_entries = [new_entry] if new_entry else []

        if not matched_entries:
            return []

        all_datasets: list[Dataset] = []
        for entry in matched_entries:
            datasets = DicomGeneratorService.create_instances_from_mwl(entry)
            for ds in datasets:
                if sop_uid and not _matches_uid_value(str(getattr(ds, "SOPInstanceUID", "")), sop_uid):
                    continue
                all_datasets.append(ds)

        return all_datasets

    def _handle_get(self, event: evt.Event):
        """Handle C-GET request and return DICOM image instances over the same association."""
        requestor_ae = getattr(event.assoc.requestor, "ae_title", "UNKNOWN") if event.assoc else "UNKNOWN"
        requestor_address = getattr(event.assoc.requestor, "address", "127.0.0.1") if event.assoc else "127.0.0.1"
        sop_class = str(getattr(event.request, "AffectedSOPClassUID", ""))

        identifier = getattr(event, "identifier", None)
        study_uid = _extract_identifier_tag(identifier, "StudyInstanceUID")
        series_uid = _extract_identifier_tag(identifier, "SeriesInstanceUID")
        sop_uid = _extract_identifier_tag(identifier, "SOPInstanceUID")
        patient_id = _extract_identifier_tag(identifier, "PatientID")
        accession = _extract_identifier_tag(identifier, "AccessionNumber")

        logger.info(
            "dicom_c_get_received",
            requestor_ae=requestor_ae,
            requestor_address=requestor_address,
            sop_class=sop_class,
            study_uid=study_uid,
            series_uid=series_uid,
            sop_uid=sop_uid,
            patient_id=patient_id,
        )

        all_datasets = self._resolve_retrieve_datasets(
            study_uid=study_uid,
            series_uid=series_uid,
            sop_uid=sop_uid,
            patient_id=patient_id,
            accession=accession,
        )

        if not all_datasets:
            logger.warning("dicom_c_get_no_matching_studies", study_uid=study_uid, patient_id=patient_id)
            yield 0
            return

        total_instances = len(all_datasets)
        # 1st yield: total sub-operations count
        yield total_instances

        accepted_contexts = getattr(event.assoc, "accepted_contexts", []) if event.assoc else []
        if accepted_contexts:
            dataset_sops = {str(getattr(ds, "SOPClassUID", "")) for ds in all_datasets if getattr(ds, "SOPClassUID", None)}
            for cx in accepted_contexts:
                if str(cx.abstract_syntax) in dataset_sops and not getattr(cx, "as_scu", False):
                    cx._as_scu = True

        # 2nd+ yields: (status, dataset) pairs sent over the existing association
        for idx, ds in enumerate(all_datasets, 1):
            if event.is_cancelled:
                logger.warning("dicom_c_get_cancelled")
                yield (0xFE00, None)
                return

            if accepted_contexts:
                ds = adapt_dataset_for_accepted_context(ds, accepted_contexts)

            patient_name = str(getattr(ds, "PatientName", ""))
            patient_id_val = str(getattr(ds, "PatientID", ""))
            study_inst_uid = str(getattr(ds, "StudyInstanceUID", ""))
            series_inst_uid = str(getattr(ds, "SeriesInstanceUID", ""))
            sop_inst_uid = str(getattr(ds, "SOPInstanceUID", ""))
            instance_num = int(getattr(ds, "InstanceNumber", idx))

            ts_uid = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
            ts_name = getattr(ts_uid, "name", str(ts_uid)) if ts_uid else "Unknown"

            logger.info(
                "dicom_c_get_instance_sent",
                patient_name=patient_name,
                patient_id=patient_id_val,
                study_instance_uid=study_inst_uid,
                series_instance_uid=series_inst_uid,
                sop_instance_uid=sop_inst_uid,
                instance_number=f"{instance_num}/{total_instances}",
                transfer_syntax=ts_name,
                transfer_syntax_uid=str(ts_uid) if ts_uid else None,
                requestor_ae=requestor_ae,
                requestor_address=requestor_address,
            )

            yield (0xFF00, ds)

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

        identifier = getattr(event, "identifier", None)
        study_uid = _extract_identifier_tag(identifier, "StudyInstanceUID")
        series_uid = _extract_identifier_tag(identifier, "SeriesInstanceUID")
        sop_uid = _extract_identifier_tag(identifier, "SOPInstanceUID")
        patient_id = _extract_identifier_tag(identifier, "PatientID")
        accession = _extract_identifier_tag(identifier, "AccessionNumber")

        all_datasets = self._resolve_retrieve_datasets(
            study_uid=study_uid,
            series_uid=series_uid,
            sop_uid=sop_uid,
            patient_id=patient_id,
            accession=accession,
        )

        if not all_datasets:
            logger.warning("dicom_c_move_no_matching_studies", study_uid=study_uid, patient_id=patient_id)
            storage_contexts = build_storage_contexts_for_datasets()
            yield (addr, port, {"contexts": storage_contexts})
            yield 0
            return

        # 1st yield: (addr, port, kwargs) including Storage presentation contexts matching the datasets' transfer syntax
        storage_contexts = build_storage_contexts_for_datasets(all_datasets)
        yield (addr, port, {"contexts": storage_contexts})

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

            ts_uid = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
            ts_name = getattr(ts_uid, "name", str(ts_uid)) if ts_uid else "Unknown"

            logger.info(
                "dicom_c_store_instance_pushed",
                patient_name=patient_name,
                patient_id=patient_id_val,
                study_instance_uid=study_inst_uid,
                series_instance_uid=series_inst_uid,
                sop_instance_uid=sop_inst_uid,
                instance_number=f"{instance_num}/{total_instances}",
                transfer_syntax=ts_name,
                transfer_syntax_uid=str(ts_uid) if ts_uid else None,
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
                or generate_dicom_uid()
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
        self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelGet)
        self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelGet)
        self.ae.add_supported_context(ModalityWorklistInformationFind)
        target_syntax = get_prioritized_transfer_syntaxes(config.transfer_syntax)[0]
        seen_sops: set[str] = set()
        for cx in StoragePresentationContexts:
            seen_sops.add(str(cx.abstract_syntax))
            self.ae.add_supported_context(
                cx.abstract_syntax,
                SUPPORTED_TRANSFER_SYNTAXES,
                scp_role=True,
                scu_role=True,
            )
            self.ae.add_requested_context(cx.abstract_syntax, [target_syntax])

        if self.mwl_service and hasattr(self.mwl_service, "template_modalities"):
            for mod_info in self.mwl_service.template_modalities.values():
                sop_uid = mod_info.get("sop_class_uid") if isinstance(mod_info, dict) else None
                if sop_uid and str(sop_uid) not in seen_sops:
                    seen_sops.add(str(sop_uid))
                    self.ae.add_supported_context(
                        str(sop_uid),
                        SUPPORTED_TRANSFER_SYNTAXES,
                        scp_role=True,
                        scu_role=True,
                    )

        handlers = [
            (evt.EVT_C_ECHO, self._handle_echo),
            (evt.EVT_C_FIND, self._handle_find),
            (evt.EVT_C_GET, self._handle_get),
            (evt.EVT_C_MOVE, self._handle_move),
            (evt.EVT_C_STORE, self._handle_store),
        ]

        for attempt in range(3):
            try:
                self.server = self.ae.start_server((host, self.port), block=False, evt_handlers=handlers)
                self.is_running = True
                logger.info("dicom_scp_server_started", host=host, port=self.port, ae_title=self.ae_title)
                return self.get_status()
            except OSError as exc:
                if attempt == 2:
                    raise exc
                import time

                time.sleep(0.2)

    def stop(self) -> ScpStatusResponse:
        """Stop the DICOM SCP server and any active auto-push task."""
        self.stop_auto_push()
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
            supported_services=["C-ECHO", "C-FIND", "C-GET", "C-MOVE", "C-STORE", "MWL-FIND"],
            auto_push_ae=self.auto_push_ae,
            auto_push_host=self.auto_push_host,
            auto_push_port=self.auto_push_port,
            auto_push_sec=self.auto_push_sec,
            is_auto_pushing=self._is_auto_pushing,
        )

    def push_datasets_to_destination(
        self,
        datasets: list[Dataset],
        target_ae_title: str,
        target_host: str = "127.0.0.1",
        target_port: int = 11113,
        preferred_syntax: str | None = None,
    ) -> dict[str, Any]:
        """Send a list of DICOM datasets to target Storage SCP via C-STORE association."""
        dest_info = config.move_destinations.get(target_ae_title)
        if dest_info:
            target_host = dest_info.get("host", target_host)
            target_port = int(dest_info.get("port", target_port))

        if not datasets:
            return {
                "success": False,
                "message": "No datasets provided to push",
                "instances_sent": 0,
                "target_ae_title": target_ae_title,
                "target_host": target_host,
                "target_port": target_port,
            }

        first_ds = datasets[0]
        ae = AE(ae_title=self.ae_title)
        ae.requested_contexts = build_storage_contexts_for_datasets(datasets, preferred_syntax=preferred_syntax)

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
            for ds in datasets:
                ds = adapt_dataset_for_accepted_context(ds, assoc.accepted_contexts)
                status = assoc.send_c_store(ds)
                if status and status.Status in (0x0000, 0xB000, 0xB006, 0xB007):
                    sent_count += 1
                else:
                    logger.warning("dicom_c_store_push_failed", status=hex(status.Status) if status else "None")
        finally:
            assoc.release()

        return {
            "success": True,
            "message": f"Successfully moved {sent_count} instances to {target_ae_title} ({target_host}:{target_port})",
            "instances_sent": sent_count,
            "patient_id": getattr(first_ds, "PatientID", None),
            "patient_name": str(getattr(first_ds, "PatientName", "")) if hasattr(first_ds, "PatientName") else None,
            "accession": getattr(first_ds, "AccessionNumber", None),
            "study_instance_uid": getattr(first_ds, "StudyInstanceUID", None),
            "target_ae_title": target_ae_title,
            "target_host": target_host,
            "target_port": target_port,
        }

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
        dest_info = config.move_destinations.get(target_ae_title)
        if dest_info:
            target_host = dest_info.get("host", target_host)
            target_port = int(dest_info.get("port", target_port))

        stow_matched: list[Dataset] = []
        if self.dicomweb_service and hasattr(self.dicomweb_service, "_stow_datasets"):
            for ds in self.dicomweb_service._stow_datasets.values():
                if study_uid and str(getattr(ds, "StudyInstanceUID", "")) != str(study_uid):
                    continue
                if patient_id and str(getattr(ds, "PatientID", "")) != str(patient_id):
                    continue
                if accession and str(getattr(ds, "AccessionNumber", "")) != str(accession):
                    continue
                stow_matched.append(ds)

        if stow_matched:
            all_datasets = stow_matched
            preferred_syntax = None
            matched_entries = []
        else:
            matched_entries = []
            if self.mwl_service:
                matched_entries = self.mwl_service.find_study_series_entries(
                    study_uid=study_uid, patient_id=patient_id, accession=accession
                )
                if not matched_entries and (study_uid or patient_id or accession):
                    # Dynamically synthesize on demand
                    new_entry = self.mwl_service.add_entry(
                        custom={
                            "studyUid": study_uid,
                            "patientId": patient_id,
                            "accession": accession,
                        }
                    )
                    matched_entries = [new_entry] if new_entry else []

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
            preferred_syntax = matched_entries[0].get("transfer_syntax")

        res = self.push_datasets_to_destination(
            datasets=all_datasets,
            target_ae_title=target_ae_title,
            target_host=target_host,
            target_port=target_port,
            preferred_syntax=preferred_syntax,
        )

        if matched_entries:
            first_entry = matched_entries[0]
            res["patient_id"] = first_entry.get("patient_id")
            res["patient_name"] = first_entry.get("patient_name")
            res["accession"] = first_entry.get("accession")
            res["study_instance_uid"] = first_entry.get("study_uid")

        return res

    move_study = push_study_to_destination

    def enqueue_auto_push_study(self, entry: dict[str, Any]) -> None:
        """Enqueue an MWL record/study to be pushed during auto-push."""
        self._auto_push_queue.append(entry)

    def _push_one_auto_study(self) -> dict[str, Any] | None:
        """Generate a study (series and images) and push to the auto_push_ae destination."""
        if not self.auto_push_ae:
            return None

        entry = self._auto_push_queue.pop(0) if self._auto_push_queue else None
        if entry is None and self.mwl_service:
            gen_mode = str(getattr(self.mwl_service.config, "generator_mode", "internal")).strip().lower()
            if gen_mode == "fhir":
                logger.debug("dicom_auto_push_fhir_queue_empty_idling")
                return None
            entry = self.mwl_service.add_entry()

        if not entry:
            logger.warning("dicom_auto_push_no_study_available")
            return None

        datasets = DicomGeneratorService.create_instances_from_mwl(entry)
        preferred_syntax = entry.get("transfer_syntax")

        target_host = self.auto_push_host or "127.0.0.1"
        target_port = self.auto_push_port or 11113

        res = self.push_datasets_to_destination(
            datasets=datasets,
            target_ae_title=self.auto_push_ae,
            target_host=target_host,
            target_port=target_port,
            preferred_syntax=preferred_syntax,
        )
        logger.info(
            "dicom_auto_push_study_sent",
            success=res.get("success"),
            instances_sent=res.get("instances_sent"),
            target_ae_title=self.auto_push_ae,
            target_host=target_host,
            target_port=target_port,
            patient_id=entry.get("patient_id"),
            accession=entry.get("accession"),
            study_uid=entry.get("study_uid"),
        )
        return res

    def _auto_push_worker(self) -> None:
        """Background thread worker pushing generated studies to configured destination every interval_sec."""
        logger.info(
            "dicom_auto_push_loop_started",
            ae_title=self.auto_push_ae,
            host=self.auto_push_host,
            port=self.auto_push_port,
            interval_sec=self.auto_push_sec,
        )
        try:
            while not self._auto_push_stop_event.is_set() and self.auto_push_ae and self.auto_push_sec > 0:
                if self._auto_push_stop_event.wait(timeout=self.auto_push_sec):
                    break
                if not self.auto_push_ae or self.auto_push_sec <= 0 or self._auto_push_stop_event.is_set():
                    break

                try:
                    self._push_one_auto_study()
                except Exception as exc:
                    logger.error("dicom_auto_push_iteration_failed", error=str(exc))
        except Exception as exc:
            logger.error("dicom_auto_push_loop_error", error=str(exc))
        finally:
            self._is_auto_pushing = False
            logger.info("dicom_auto_push_loop_stopped")

    _auto_push_loop = _auto_push_worker

    def configure_auto_push(
        self,
        target_ae_title: str | None = None,
        interval_sec: float | None = None,
        target_host: str = "127.0.0.1",
        target_port: int = 11113,
        ae_title: str | None = None,
        intervalSec: float | None = None,
        targetAeTitle: str | None = None,
        targetHost: str | None = None,
        targetPort: int | None = None,
    ) -> dict[str, Any]:
        """Configure auto-push destination and interval in seconds."""
        resolved_ae = (targetAeTitle or target_ae_title or ae_title or "").strip()
        sec_val = intervalSec if intervalSec is not None else (interval_sec if interval_sec is not None else 0.0)
        resolved_sec = float(sec_val)
        resolved_host = (targetHost or target_host or "127.0.0.1").strip()
        port_val = targetPort if targetPort is not None else target_port
        resolved_port = int(port_val) if port_val else 11113

        self.auto_push_ae = resolved_ae
        self.auto_push_sec = max(0.0, resolved_sec)
        self.auto_push_host = resolved_host
        self.auto_push_port = resolved_port

        # If host and port were left at defaults but target_ae exists in config.move_destinations:
        if resolved_host == "127.0.0.1" and resolved_port == 11113 and self.auto_push_ae in config.move_destinations:
            dest_info = config.move_destinations[self.auto_push_ae]
            self.auto_push_host = dest_info.get("host", self.auto_push_host)
            self.auto_push_port = int(dest_info.get("port", self.auto_push_port))

        config.auto_push_ae = self.auto_push_ae
        config.auto_push_host = self.auto_push_host
        config.auto_push_port = self.auto_push_port
        config.auto_push_sec = self.auto_push_sec

        if self.auto_push_sec > 0 and self.auto_push_ae:
            self.start_auto_push(
                target_ae_title=self.auto_push_ae,
                interval_sec=self.auto_push_sec,
                target_host=self.auto_push_host,
                target_port=self.auto_push_port,
            )
            message = (
                f"Auto push configured to '{self.auto_push_ae}' ({self.auto_push_host}:{self.auto_push_port}) "
                f"every {self.auto_push_sec} seconds."
            )
        else:
            self.stop_auto_push()
            message = "Auto push disabled."

        return {
            "success": True,
            "message": message,
            "intervalSec": self.auto_push_sec,
            "interval_sec": self.auto_push_sec,
            "targetAeTitle": self.auto_push_ae,
            "target_ae_title": self.auto_push_ae,
            "ae_title": self.auto_push_ae,
            "targetHost": self.auto_push_host,
            "target_host": self.auto_push_host,
            "targetPort": self.auto_push_port,
            "target_port": self.auto_push_port,
            "is_auto_pushing": self._is_auto_pushing,
        }

    def start_auto_push(
        self,
        target_ae_title: str | None = None,
        interval_sec: float | None = None,
        target_host: str | None = None,
        target_port: int | None = None,
        ae_title: str | None = None,
        intervalSec: float | None = None,
        targetAeTitle: str | None = None,
        targetHost: str | None = None,
        targetPort: int | None = None,
    ) -> dict[str, Any]:
        """Start the background auto-push loop."""
        resolved_ae = targetAeTitle or target_ae_title or ae_title
        if resolved_ae is not None:
            self.auto_push_ae = resolved_ae.strip()
            config.auto_push_ae = self.auto_push_ae
        resolved_host = targetHost or target_host
        if resolved_host is not None:
            self.auto_push_host = resolved_host.strip()
            config.auto_push_host = self.auto_push_host
        resolved_port = targetPort if targetPort is not None else target_port
        if resolved_port is not None:
            self.auto_push_port = int(resolved_port)
            config.auto_push_port = self.auto_push_port
        sec_val = intervalSec if intervalSec is not None else interval_sec
        if sec_val is not None:
            self.auto_push_sec = max(0.0, float(sec_val))
            config.auto_push_sec = self.auto_push_sec

        if not self.auto_push_ae or self.auto_push_sec <= 0:
            return self.get_auto_push_status()

        self.stop_auto_push()
        self._auto_push_stop_event.clear()
        self._is_auto_pushing = True
        self._auto_push_thread = threading.Thread(
            target=self._auto_push_worker,
            name="dicom-auto-push-worker",
            daemon=True,
        )
        self._auto_push_thread.start()

        return self.get_auto_push_status()

    def stop_auto_push(self) -> dict[str, Any]:
        """Stop background auto-push loop."""
        self._is_auto_pushing = False
        if hasattr(self, "_auto_push_stop_event"):
            self._auto_push_stop_event.set()
        if hasattr(self, "_auto_push_thread") and self._auto_push_thread and self._auto_push_thread.is_alive():
            self._auto_push_thread.join(timeout=0.2)
            self._auto_push_thread = None
        return self.get_auto_push_status()

    def set_event_loop(self, loop: Any = None) -> None:
        """Compatibility no-op for event loop setting."""
        pass

    def get_auto_push_status(self) -> dict[str, Any]:
        """Get current status of auto-push service."""
        return {
            "success": True,
            "message": (
                f"Auto push active to '{self.auto_push_ae}' ({self.auto_push_host}:{self.auto_push_port}) "
                f"every {self.auto_push_sec} seconds."
                if self._is_auto_pushing and self.auto_push_ae and self.auto_push_sec > 0
                else "Auto push is currently disabled."
            ),
            "intervalSec": self.auto_push_sec,
            "interval_sec": self.auto_push_sec,
            "targetAeTitle": self.auto_push_ae,
            "target_ae_title": self.auto_push_ae,
            "ae_title": self.auto_push_ae,
            "targetHost": self.auto_push_host,
            "target_host": self.auto_push_host,
            "targetPort": self.auto_push_port,
            "target_port": self.auto_push_port,
            "is_auto_pushing": self._is_auto_pushing,
        }
