"""Service implementing DICOMweb QIDO-RS, WADO-RS, and WADO-URI functionality."""

import io
import re
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pydicom
import structlog
from PIL import Image
from pydicom.dataset import Dataset

from dicom_py_mock_server.config import config
from dicom_py_mock_server.services.generator import TRANSFER_SYNTAX_MAP, DicomGeneratorService
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService

logger = structlog.get_logger(__name__)


class DicomWebService:
    """Service to handle DICOMweb QIDO-RS, WADO-RS, and WADO-URI operations."""

    def __init__(
        self,
        mwl_service: MwlGeneratorService | None = None,
        generator_service: DicomGeneratorService | None = None,
        storage_dir: str | None = None,
    ) -> None:
        self.mwl_service = mwl_service
        self.generator_service = generator_service or DicomGeneratorService()
        self.storage_dir = Path(storage_dir or config.storage_dir)
        self._study_transfer_syntaxes: dict[str, str] = {}
        self._stress_study_cache: dict[str, list[Dataset]] = {}

    def clear_stress_cache(self) -> None:
        """Clear cached transfer syntaxes and study instances for stress mode."""
        self._study_transfer_syntaxes.clear()
        self._stress_study_cache.clear()

    def _get_stored_files(self) -> list[Path]:
        """Get all stored .dcm files on disk."""
        if not self.storage_dir.exists():
            return []
        return [p for p in self.storage_dir.rglob("*.dcm") if p.is_file()]

    def _read_stored_datasets(self) -> list[Dataset]:
        """Read all stored DICOM datasets from storage directory."""
        datasets: list[Dataset] = []
        for file_path in self._get_stored_files():
            try:
                ds = pydicom.dcmread(file_path, force=True)
                datasets.append(ds)
            except Exception as exc:
                logger.warning("failed_to_read_stored_dicom", path=str(file_path), error=str(exc))
        return datasets

    @staticmethod
    def _matches_filter(val: Any, query: str | None) -> bool:
        """Helper to match DICOM attribute value against query with wildcard and case insensitivity."""
        if query is None or not str(query).strip() or str(query).strip() == "*":
            return True
        if val is None:
            return False
        v_str = str(val).strip()
        q_str = str(query).strip()
        if v_str == q_str:
            return True
        if "*" in q_str or "?" in q_str:
            import fnmatch

            return fnmatch.fnmatch(v_str.upper(), q_str.upper())
        return v_str.upper() == q_str.upper()

    @staticmethod
    def _extract_candidates_from_list(val_str: str | None) -> list[str]:
        """Split a comma- or semicolon-separated string into non-empty stripped tokens."""
        if not val_str:
            return []
        tokens = [t.strip().strip('"').strip("'") for t in re.split(r"[,;]", val_str) if t.strip()]
        return [t for t in tokens if t and t != "*"]

    @staticmethod
    def parse_transfer_syntax_header(
        accept_header: str | None = None,
        query_param: str | None = None,
        direct_header: str | None = None,
    ) -> str | None:
        """Extract requested transfer syntax UID or name from headers or query parameters.

        Supports both standard semicolon-separated parameters (e.g. `multipart/related;
        type=\"application/dicom\"; transfer-syntax=...`) and comma-separated items/parameters,
        as well as lists of acceptable syntaxes.
        """
        resolved: str | None = None
        if direct_header and str(direct_header).strip():
            candidates = DicomWebService._extract_candidates_from_list(str(direct_header))
            for cand in candidates:
                if cand in TRANSFER_SYNTAX_MAP or cand.upper() in TRANSFER_SYNTAX_MAP:
                    resolved = cand
                    break
            if not resolved and candidates:
                resolved = candidates[0]

        if not resolved and query_param and str(query_param).strip():
            candidates = DicomWebService._extract_candidates_from_list(str(query_param))
            for cand in candidates:
                if cand in TRANSFER_SYNTAX_MAP or cand.upper() in TRANSFER_SYNTAX_MAP:
                    resolved = cand
                    break
            if not resolved and candidates:
                resolved = candidates[0]

        if not resolved and accept_header:
            # 1. Look for transfer-syntax parameter(s), supporting both semicolon and comma delimiters
            ts_matches = re.finditer(r'transfer-syntax\s*=\s*(?:"([^"]+)"|([^\s;,]+))', accept_header, re.IGNORECASE)
            for m in ts_matches:
                raw_ts = m.group(1) if m.group(1) is not None else m.group(2)
                for ts_token in DicomWebService._extract_candidates_from_list(raw_ts):
                    if ts_token:
                        resolved = ts_token
                        break
                if resolved:
                    break

            # 2. Check for type parameter(s) (e.g. image/jpeg, image/jp2, image/rle, application/octet-stream)
            if not resolved:
                type_matches = re.finditer(r'type\s*=\s*(?:"([^"]+)"|([^\s;,]+))', accept_header, re.IGNORECASE)
                for tm in type_matches:
                    raw_type = tm.group(1) if tm.group(1) is not None else tm.group(2)
                    for media_type_token in DicomWebService._extract_candidates_from_list(raw_type):
                        media_type = media_type_token.lower()
                        if media_type in ("image/jpeg", "image/jpg"):
                            resolved = "1.2.840.10008.1.2.4.50"
                            break
                        elif media_type in ("image/jp2", "image/jpx", "image/j2c"):
                            resolved = "1.2.840.10008.1.2.4.90"
                            break
                        elif media_type in ("image/rle", "image/dicom-rle"):
                            resolved = "1.2.840.10008.1.2.5"
                            break
                        elif media_type == "application/octet-stream":
                            resolved = "1.2.840.10008.1.2.1"
                            break
                    if resolved:
                        break

            # 3. Check direct media types in Accept (e.g. image/jpeg, image/jp2, image/rle, application/octet-stream)
            if not resolved:
                accept_lower = accept_header.lower()
                if "image/jpeg" in accept_lower or "image/jpg" in accept_lower:
                    resolved = "1.2.840.10008.1.2.4.50"
                elif "image/jp2" in accept_lower or "image/jpx" in accept_lower:
                    resolved = "1.2.840.10008.1.2.4.90"
                elif "image/rle" in accept_lower:
                    resolved = "1.2.840.10008.1.2.5"
                elif "application/octet-stream" in accept_lower and "application/dicom" not in accept_lower:
                    resolved = "1.2.840.10008.1.2.1"
                else:
                    # Check each comma- or semicolon-separated token in the Accept header directly
                    for token in DicomWebService._extract_candidates_from_list(accept_header):
                        if token.upper() in TRANSFER_SYNTAX_MAP or token in TRANSFER_SYNTAX_MAP:
                            resolved = token
                            break

        logger.info(
            "dicomweb_transfer_syntax_parsed",
            accept_header=accept_header,
            direct_header=direct_header,
            query_param=query_param,
            resolved_transfer_syntax=resolved,
        )
        return resolved

    def search_studies(self, query_params: dict[str, Any]) -> list[dict[str, Any]]:
        """QIDO-RS: Search for studies matching query parameters and return DICOM JSON."""
        study_datasets: list[Dataset] = []
        seen_study_uids: set[str] = set()

        # 1. Collect from active MWL generator entries
        if self.mwl_service:
            self.mwl_service.purge_expired_entries()
            for entry in self.mwl_service._entries:
                study_ds = self.mwl_service.to_study_cfind_dataset(entry)
                study_uid = str(getattr(study_ds, "StudyInstanceUID", ""))
                if study_uid and study_uid not in seen_study_uids:
                    seen_study_uids.add(study_uid)
                    study_datasets.append(study_ds)

        # 2. Collect from disk storage
        for ds in self._read_stored_datasets():
            study_uid = str(getattr(ds, "StudyInstanceUID", ""))
            if study_uid and study_uid not in seen_study_uids:
                seen_study_uids.add(study_uid)
                study_datasets.append(ds)

        # Apply filtering
        patient_id = query_params.get("PatientID") or query_params.get("patientID") or query_params.get("patient_id")
        patient_name = (
            query_params.get("PatientName") or query_params.get("patientName") or query_params.get("patient_name")
        )
        accession = (
            query_params.get("AccessionNumber") or query_params.get("accessionNumber") or query_params.get("accession")
        )
        study_uid_q = (
            query_params.get("StudyInstanceUID")
            or query_params.get("studyInstanceUID")
            or query_params.get("study_uid")
        )
        study_date = query_params.get("StudyDate") or query_params.get("studyDate") or query_params.get("study_date")
        modalities = (
            query_params.get("ModalitiesInStudy") or query_params.get("modality") or query_params.get("Modality")
        )
        study_desc = (
            query_params.get("StudyDescription")
            or query_params.get("studyDescription")
            or query_params.get("study_desc")
        )

        matched: list[Dataset] = []
        for ds in study_datasets:
            if patient_id and not self._matches_filter(getattr(ds, "PatientID", None), patient_id):
                continue
            if patient_name and not self._matches_filter(getattr(ds, "PatientName", None), patient_name):
                continue
            if accession and not self._matches_filter(getattr(ds, "AccessionNumber", None), accession):
                continue
            if study_uid_q and not self._matches_filter(getattr(ds, "StudyInstanceUID", None), study_uid_q):
                continue
            if study_date and not self._matches_filter(getattr(ds, "StudyDate", None), study_date):
                continue
            if study_desc and not self._matches_filter(getattr(ds, "StudyDescription", None), study_desc):
                continue
            if modalities:
                ds_mod = getattr(ds, "ModalitiesInStudy", None) or getattr(ds, "Modality", None)
                if not self._matches_filter(ds_mod, modalities):
                    continue
            matched.append(ds)

        # Apply offset and limit (supporting standard limit and variations like ?limit-100)
        offset = int(query_params.get("offset", 0) or 0)
        limit = query_params.get("limit") or query_params.get("Limit")
        if limit is None:
            for k in query_params:
                m = re.match(r"^limit[-_:=](\d+)$", k, re.IGNORECASE)
                if m:
                    limit = m.group(1)
                    break
        if limit is not None:
            try:
                limit_val = int(limit)
                matched = matched[offset : offset + limit_val]
            except ValueError:
                pass
        elif offset > 0:
            matched = matched[offset:]

        # Convert to DICOM JSON
        result = []
        for ds in matched:
            out_ds = Dataset()
            out_ds.StudyInstanceUID = getattr(ds, "StudyInstanceUID", "")
            if "PatientID" in ds:
                out_ds.PatientID = ds.PatientID
            if "PatientName" in ds:
                out_ds.PatientName = ds.PatientName
            if "PatientBirthDate" in ds:
                out_ds.PatientBirthDate = ds.PatientBirthDate
            if "PatientSex" in ds:
                out_ds.PatientSex = ds.PatientSex
            if "StudyDate" in ds:
                out_ds.StudyDate = ds.StudyDate
            if "StudyTime" in ds:
                out_ds.StudyTime = ds.StudyTime
            if "AccessionNumber" in ds:
                out_ds.AccessionNumber = ds.AccessionNumber
            if "StudyDescription" in ds:
                out_ds.StudyDescription = ds.StudyDescription
            if "InstitutionName" in ds:
                out_ds.InstitutionName = ds.InstitutionName
            if "ReferringPhysicianName" in ds:
                out_ds.ReferringPhysicianName = ds.ReferringPhysicianName
            if "ModalitiesInStudy" in ds:
                out_ds.ModalitiesInStudy = ds.ModalitiesInStudy
            elif "Modality" in ds:
                out_ds.ModalitiesInStudy = ds.Modality
            if "NumberOfStudyRelatedSeries" in ds:
                out_ds.NumberOfStudyRelatedSeries = ds.NumberOfStudyRelatedSeries
            if "NumberOfStudyRelatedInstances" in ds:
                out_ds.NumberOfStudyRelatedInstances = ds.NumberOfStudyRelatedInstances

            result.append(out_ds.to_json_dict(suppress_invalid_tags=True))

        return result

    def search_series(self, study_uid: str | None, query_params: dict[str, Any]) -> list[dict[str, Any]]:
        """QIDO-RS: Search for series matching query parameters and return DICOM JSON."""
        series_datasets: list[Dataset] = []
        seen_series_uids: set[str] = set()

        # 1. Collect from active MWL generator entries
        if self.mwl_service:
            self.mwl_service.purge_expired_entries()
            for entry in self.mwl_service._entries:
                if study_uid and not self._matches_filter(entry.get("study_uid"), study_uid):
                    continue
                series_ds = self.mwl_service.to_series_cfind_dataset(entry)
                s_uid = str(getattr(series_ds, "SeriesInstanceUID", ""))
                if s_uid and s_uid not in seen_series_uids:
                    seen_series_uids.add(s_uid)
                    series_datasets.append(series_ds)

        # 2. Collect from disk storage
        for ds in self._read_stored_datasets():
            if study_uid and not self._matches_filter(getattr(ds, "StudyInstanceUID", None), study_uid):
                continue
            s_uid = str(getattr(ds, "SeriesInstanceUID", ""))
            if s_uid and s_uid not in seen_series_uids:
                seen_series_uids.add(s_uid)
                series_datasets.append(ds)

        # Apply filtering
        modality = query_params.get("Modality") or query_params.get("modality")
        series_uid_q = query_params.get("SeriesInstanceUID") or query_params.get("seriesInstanceUID")
        series_desc = query_params.get("SeriesDescription") or query_params.get("seriesDescription")
        series_num = query_params.get("SeriesNumber") or query_params.get("seriesNumber")

        matched: list[Dataset] = []
        for ds in series_datasets:
            if modality and not self._matches_filter(getattr(ds, "Modality", None), modality):
                continue
            if series_uid_q and not self._matches_filter(getattr(ds, "SeriesInstanceUID", None), series_uid_q):
                continue
            if series_desc and not self._matches_filter(getattr(ds, "SeriesDescription", None), series_desc):
                continue
            if series_num and not self._matches_filter(getattr(ds, "SeriesNumber", None), series_num):
                continue
            matched.append(ds)

        # Apply offset and limit
        offset = int(query_params.get("offset", 0) or 0)
        limit = query_params.get("limit")
        if limit is not None:
            limit = int(limit)
            matched = matched[offset : offset + limit]
        elif offset > 0:
            matched = matched[offset:]

        result = []
        for ds in matched:
            out_ds = Dataset()
            out_ds.StudyInstanceUID = getattr(ds, "StudyInstanceUID", study_uid or "")
            out_ds.SeriesInstanceUID = getattr(ds, "SeriesInstanceUID", "")
            if "Modality" in ds:
                out_ds.Modality = ds.Modality
            if "SeriesNumber" in ds:
                out_ds.SeriesNumber = int(ds.SeriesNumber)
            if "SeriesDescription" in ds:
                out_ds.SeriesDescription = ds.SeriesDescription
            if "PerformingPhysicianName" in ds:
                out_ds.PerformingPhysicianName = ds.PerformingPhysicianName
            if "InstitutionName" in ds:
                out_ds.InstitutionName = ds.InstitutionName
            if "NumberOfSeriesRelatedInstances" in ds:
                out_ds.NumberOfSeriesRelatedInstances = int(ds.NumberOfSeriesRelatedInstances)

            result.append(out_ds.to_json_dict(suppress_invalid_tags=True))

        return result

    def search_instances(
        self, study_uid: str | None, series_uid: str | None, query_params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """QIDO-RS: Search for instances matching query parameters and return DICOM JSON."""
        instance_datasets: list[Dataset] = []
        seen_sop_uids: set[str] = set()

        # 1. Collect from active MWL generator entries
        if self.mwl_service:
            self.mwl_service.purge_expired_entries()
            for entry in self.mwl_service._entries:
                if study_uid and not self._matches_filter(entry.get("study_uid"), study_uid):
                    continue
                if series_uid and not self._matches_filter(entry.get("series_uid"), series_uid):
                    continue
                img_datasets = self.mwl_service.to_image_cfind_datasets(entry)
                for img_ds in img_datasets:
                    sop_uid = str(getattr(img_ds, "SOPInstanceUID", ""))
                    if sop_uid and sop_uid not in seen_sop_uids:
                        seen_sop_uids.add(sop_uid)
                        instance_datasets.append(img_ds)

        # 2. Collect from disk storage
        for ds in self._read_stored_datasets():
            if study_uid and not self._matches_filter(getattr(ds, "StudyInstanceUID", None), study_uid):
                continue
            if series_uid and not self._matches_filter(getattr(ds, "SeriesInstanceUID", None), series_uid):
                continue
            sop_uid = str(getattr(ds, "SOPInstanceUID", ""))
            if sop_uid and sop_uid not in seen_sop_uids:
                seen_sop_uids.add(sop_uid)
                instance_datasets.append(ds)

        # Apply filtering
        sop_uid_q = query_params.get("SOPInstanceUID") or query_params.get("sopInstanceUID")
        sop_class_q = query_params.get("SOPClassUID") or query_params.get("sopClassUID")
        inst_num = query_params.get("InstanceNumber") or query_params.get("instanceNumber")

        matched: list[Dataset] = []
        for ds in instance_datasets:
            if sop_uid_q and not self._matches_filter(getattr(ds, "SOPInstanceUID", None), sop_uid_q):
                continue
            if sop_class_q and not self._matches_filter(getattr(ds, "SOPClassUID", None), sop_class_q):
                continue
            if inst_num and not self._matches_filter(getattr(ds, "InstanceNumber", None), inst_num):
                continue
            matched.append(ds)

        # Apply offset and limit
        offset = int(query_params.get("offset", 0) or 0)
        limit = query_params.get("limit")
        if limit is not None:
            limit = int(limit)
            matched = matched[offset : offset + limit]
        elif offset > 0:
            matched = matched[offset:]

        result = []
        for ds in matched:
            out_ds = Dataset()
            out_ds.StudyInstanceUID = getattr(ds, "StudyInstanceUID", study_uid or "")
            out_ds.SeriesInstanceUID = getattr(ds, "SeriesInstanceUID", series_uid or "")
            out_ds.SOPInstanceUID = getattr(ds, "SOPInstanceUID", "")
            out_ds.SOPClassUID = getattr(ds, "SOPClassUID", "1.2.840.10008.5.1.4.1.1.2")
            if "InstanceNumber" in ds:
                out_ds.InstanceNumber = int(ds.InstanceNumber)
            if "Rows" in ds:
                out_ds.Rows = int(ds.Rows)
            if "Columns" in ds:
                out_ds.Columns = int(ds.Columns)
            if "BitsAllocated" in ds:
                out_ds.BitsAllocated = int(ds.BitsAllocated)
            if "BitsStored" in ds:
                out_ds.BitsStored = int(ds.BitsStored)
            if "HighBit" in ds:
                out_ds.HighBit = int(ds.HighBit)
            if "PixelRepresentation" in ds:
                out_ds.PixelRepresentation = int(ds.PixelRepresentation)

            result.append(out_ds.to_json_dict(suppress_invalid_tags=True))

        return result

    def get_study_datasets(
        self,
        study_uid: str,
        num_instances: int | None = None,
        requested_transfer_syntax: str | None = None,
        stress: bool | None = None,
    ) -> list[Dataset]:
        """Get all full instance datasets for a StudyInstanceUID.

        If num_instances is specified, limits or configures the number of slices to generate/retrieve (up to 1024).
        Otherwise, follows the actual number of slices generated for the study without arbitrary clamping.
        In stress mode, uses the transfer syntax from the first image request and reuses the single compressed frame.
        """
        is_stress = stress if stress is not None else getattr(config, "stress", False)

        if is_stress:
            if study_uid in self._study_transfer_syntaxes:
                effective_ts = self._study_transfer_syntaxes[study_uid]
            else:
                effective_ts = requested_transfer_syntax or getattr(config, "transfer_syntax", "JPEG2000_LOSSLESS")
                self._study_transfer_syntaxes[study_uid] = effective_ts

            if study_uid in self._stress_study_cache:
                cached = self._stress_study_cache[study_uid]
                if num_instances is not None and len(cached) > num_instances:
                    return cached[:num_instances]
                return cached
        else:
            effective_ts = requested_transfer_syntax

        datasets: list[Dataset] = []

        # 1. Search in MWL active entries
        if self.mwl_service:
            matched_entries = self.mwl_service.find_entries(study_uid=study_uid)
            for entry in matched_entries:
                entry_instances = num_instances or entry.get("num_instances")
                inst_list = DicomGeneratorService.create_instances_from_mwl(
                    entry,
                    num_instances=entry_instances,
                    transfer_syntax=effective_ts,
                    stress=is_stress,
                )
                datasets.extend(inst_list)

        # 2. Check stored files on disk
        if not datasets:
            datasets = [
                ds for ds in self._read_stored_datasets() if str(getattr(ds, "StudyInstanceUID", "")) == str(study_uid)
            ]

        if is_stress and datasets:
            self._stress_study_cache[study_uid] = datasets

        if num_instances is not None and len(datasets) > num_instances:
            datasets = datasets[:num_instances]

        return datasets

    def get_series_datasets(
        self,
        study_uid: str,
        series_uid: str,
        num_instances: int | None = None,
        requested_transfer_syntax: str | None = None,
        stress: bool | None = None,
    ) -> list[Dataset]:
        """Get all full instance datasets for a StudyInstanceUID and SeriesInstanceUID."""
        all_study_ds = self.get_study_datasets(
            study_uid,
            num_instances=num_instances,
            requested_transfer_syntax=requested_transfer_syntax,
            stress=stress,
        )
        matched = [ds for ds in all_study_ds if str(getattr(ds, "SeriesInstanceUID", "")) == str(series_uid)]
        if num_instances is not None and len(matched) > num_instances:
            matched = matched[:num_instances]
        return matched

    def get_instance_dataset(
        self,
        study_uid: str,
        series_uid: str | None,
        instance_uid: str,
        requested_transfer_syntax: str | None = None,
        stress: bool | None = None,
    ) -> Dataset | None:
        """Get single instance dataset matching SOPInstanceUID."""
        all_study_ds = self.get_study_datasets(
            study_uid,
            requested_transfer_syntax=requested_transfer_syntax,
            stress=stress,
        )
        for ds in all_study_ds:
            if str(getattr(ds, "SOPInstanceUID", "")) == str(instance_uid):
                if series_uid and str(getattr(ds, "SeriesInstanceUID", "")) != str(series_uid):
                    continue
                return ds
        return None

    @staticmethod
    def get_metadata(datasets: list[Dataset], requested_transfer_syntax: str | None = None) -> list[dict[str, Any]]:
        """Extract metadata (omitting PixelData and bulk data) in DICOM JSON format."""
        import copy

        metadata_list = []
        for ds in datasets:
            ds_copy = copy.deepcopy(ds)
            if requested_transfer_syntax:
                ds_copy = DicomGeneratorService.apply_transfer_syntax(ds_copy, requested_transfer_syntax)
            # Remove pixel data element (0x7FE0, 0x0010) and pixel data provider url
            if (0x7FE0, 0x0010) in ds_copy:
                del ds_copy[0x7FE0, 0x0010]
            if (0x7FE0, 0x0001) in ds_copy:
                del ds_copy[0x7FE0, 0x0001]
            metadata_list.append(ds_copy.to_json_dict(suppress_invalid_tags=True))
        return metadata_list

    def encode_multipart_related(
        self,
        datasets: list[Dataset],
        requested_transfer_syntax: str | None = None,
        boundary: str | None = None,
    ) -> tuple[bytes, str]:
        """Encode list of datasets into MIME multipart/related; type="application/dicom" payload.

        Returns (payload_bytes, content_type_header).
        """
        if boundary is None:
            boundary = f"dicom_boundary_{uuid.uuid4().hex}"

        parts: list[bytes] = []

        is_stress = getattr(config, "stress", False)
        study_uid = str(getattr(datasets[0], "StudyInstanceUID", "")) if datasets else ""
        if is_stress and study_uid in self._study_transfer_syntaxes:
            effective_target_ts = self._study_transfer_syntaxes[study_uid]
        else:
            effective_target_ts = requested_transfer_syntax

        for ds in datasets:
            target_ts = effective_target_ts
            if target_ts and getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None) != target_ts:
                ds = DicomGeneratorService.apply_transfer_syntax(ds, target_ts)

            # Get transfer syntax from dataset file_meta
            ts_uid = str(getattr(ds.file_meta, "TransferSyntaxUID", "1.2.840.10008.1.2.1"))

            buf = io.BytesIO()
            ds.save_as(buf, enforce_file_format=True)
            dcm_bytes = buf.getvalue()

            part_header = (
                f"--{boundary}\r\n"
                f"Content-Type: application/dicom; transfer-syntax={ts_uid}\r\n"
                f"Content-Length: {len(dcm_bytes)}\r\n\r\n"
            ).encode("utf-8")

            parts.append(part_header + dcm_bytes + b"\r\n")

        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        payload = b"".join(parts)
        content_type = f'multipart/related; type="application/dicom"; boundary="{boundary}"'

        return payload, content_type

    def render_instance(
        self,
        dataset: Dataset,
        frame: int = 1,
        image_format: str = "JPEG",
        quality: int = 85,
    ) -> tuple[bytes, str]:
        """Render pixel array of DICOM dataset to JPEG/PNG bytes."""
        try:
            arr = dataset.pixel_array
        except Exception:
            # Fallback if pixel_array extraction fails
            rows = getattr(dataset, "Rows", 512)
            cols = getattr(dataset, "Columns", 512)
            arr = np.zeros((rows, cols), dtype=np.uint8)

        if arr.ndim == 3 and arr.shape[0] > 1:
            # Multi-frame dataset
            idx = max(0, min(frame - 1, arr.shape[0] - 1))
            arr = arr[idx]

        # Normalize pixel values to 0-255 uint8
        arr_min = float(arr.min())
        arr_max = float(arr.max())
        if arr_max > arr_min:
            norm_arr = ((arr - arr_min) / (arr_max - arr_min) * 255.0).astype(np.uint8)
        else:
            norm_arr = np.zeros(arr.shape, dtype=np.uint8)

        img = Image.fromarray(norm_arr)
        if img.mode != "L" and img.mode != "RGB":
            img = img.convert("L")

        buf = io.BytesIO()
        fmt = image_format.upper()
        if fmt in ("JPG", "JPEG"):
            img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=quality)
            media_type = "image/jpeg"
        else:
            img.save(buf, format="PNG")
            media_type = "image/png"

        return buf.getvalue(), media_type

    def get_encoded_frames(
        self,
        dataset: Dataset,
        frame_numbers: list[int],
        requested_transfer_syntax: str | None = None,
    ) -> tuple[list[bytes], str]:
        """Extract and encode pixel frames for specified frame numbers (1-indexed).

        Returns (encoded_frame_bytes_list, content_type_str).
        """
        from pydicom.dataset import FileMetaDataset
        from pydicom.encaps import generate_pixel_data_frame
        from pydicom.uid import (
            JPEG2000,
            ExplicitVRLittleEndian,
            JPEG2000Lossless,
            JPEGBaseline8Bit,
            RLELossless,
        )

        from dicom_py_mock_server.services.generator import resolve_transfer_syntax

        frames: list[bytes] = []
        try:
            arr = dataset.pixel_array
        except Exception as exc:
            logger.warning("failed_to_extract_pixel_array_for_frames", error=str(exc))
            return [], "application/octet-stream"

        frame_arrays: list[np.ndarray] = []
        if arr.ndim == 2:
            if 1 in frame_numbers:
                frame_arrays.append(arr)
        elif arr.ndim == 3:
            for fn in frame_numbers:
                idx = fn - 1
                if 0 <= idx < arr.shape[0]:
                    frame_arrays.append(arr[idx])

        if not frame_arrays:
            return [], "application/octet-stream"

        if requested_transfer_syntax:
            target_uid = resolve_transfer_syntax(requested_transfer_syntax)
        else:
            target_uid = getattr(getattr(dataset, "file_meta", None), "TransferSyntaxUID", ExplicitVRLittleEndian)

        if target_uid == JPEGBaseline8Bit:
            media_type = "image/jpeg"
            for f_arr in frame_arrays:
                if f_arr.dtype == np.uint8 or f_arr.max() <= 255:
                    f_arr8 = f_arr.astype(np.uint8)
                else:
                    f_arr8 = (f_arr >> 4).astype(np.uint8)
                img = Image.fromarray(f_arr8, mode="L")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=95)
                frames.append(buf.getvalue())
        elif target_uid in (JPEG2000Lossless, JPEG2000):
            media_type = "image/jp2"
            for f_arr in frame_arrays:
                temp_ds = Dataset()
                temp_ds.Rows, temp_ds.Columns = f_arr.shape
                temp_ds.BitsAllocated = 16 if f_arr.dtype == np.uint16 else 8
                temp_ds.BitsStored = 12 if f_arr.dtype == np.uint16 else 8
                temp_ds.HighBit = 11 if f_arr.dtype == np.uint16 else 7
                temp_ds.PixelRepresentation = 0
                temp_ds.SamplesPerPixel = 1
                temp_ds.PhotometricInterpretation = "MONOCHROME2"
                temp_ds.PixelData = f_arr.tobytes()
                temp_ds.file_meta = FileMetaDataset()
                temp_ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                try:
                    if target_uid == JPEG2000:
                        temp_ds.compress(JPEG2000, j2k_cr=[10], generate_instance_uid=False)
                    else:
                        temp_ds.compress(JPEG2000Lossless, generate_instance_uid=False)
                    enc_frame = next(generate_pixel_data_frame(temp_ds.PixelData))
                    frames.append(enc_frame)
                except Exception as exc:
                    logger.warning("j2k_frame_compression_failed_falling_back_to_raw", error=str(exc))
                    frames.append(f_arr.tobytes())
                    media_type = "application/octet-stream"
        elif target_uid == RLELossless:
            media_type = "image/rle"
            for f_arr in frame_arrays:
                temp_ds = Dataset()
                temp_ds.Rows, temp_ds.Columns = f_arr.shape
                temp_ds.BitsAllocated = 16 if f_arr.dtype == np.uint16 else 8
                temp_ds.BitsStored = 12 if f_arr.dtype == np.uint16 else 8
                temp_ds.HighBit = 11 if f_arr.dtype == np.uint16 else 7
                temp_ds.PixelRepresentation = 0
                temp_ds.SamplesPerPixel = 1
                temp_ds.PhotometricInterpretation = "MONOCHROME2"
                temp_ds.PixelData = f_arr.tobytes()
                temp_ds.file_meta = FileMetaDataset()
                temp_ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                try:
                    temp_ds.compress(RLELossless, generate_instance_uid=False)
                    enc_frame = next(generate_pixel_data_frame(temp_ds.PixelData))
                    frames.append(enc_frame)
                except Exception as exc:
                    logger.warning("rle_frame_compression_failed_falling_back_to_raw", error=str(exc))
                    frames.append(f_arr.tobytes())
                    media_type = "application/octet-stream"
        else:
            media_type = "application/octet-stream"
            for f_arr in frame_arrays:
                frames.append(f_arr.tobytes())

        return frames, media_type

    def get_frame_bytes(self, dataset: Dataset, frame_numbers: list[int]) -> list[bytes]:
        """Extract raw pixel frame bytes for specified frame numbers (1-indexed)."""
        frames, _ = self.get_encoded_frames(dataset, frame_numbers, requested_transfer_syntax=None)
        return frames
