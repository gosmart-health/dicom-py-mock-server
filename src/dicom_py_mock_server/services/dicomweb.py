"""Service implementing DICOMweb QIDO-RS, WADO-RS, and WADO-URI functionality."""

import io
import re
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np
import pydicom
import structlog
from PIL import Image
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, JPEGBaseline8Bit

from dicom_py_mock_server.config import config
from dicom_py_mock_server.services.generator import (
    TRANSFER_SYNTAX_MAP,
    DicomGeneratorService,
    resolve_transfer_syntax,
)
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService

logger = structlog.get_logger(__name__)


class DicomWebService:
    """Service to handle DICOMweb QIDO-RS, WADO-RS, and WADO-URI operations."""

    def __init__(
        self,
        mwl_service: MwlGeneratorService | None = None,
        generator_service: DicomGeneratorService | None = None,
        storage_dir: str | None = None,
        received_dir: str | None = None,
    ) -> None:
        self.mwl_service = mwl_service
        self.generator_service = generator_service or DicomGeneratorService()
        self.storage_dir = Path(storage_dir or config.storage_dir)
        self.received_dir = Path(received_dir or config.received_dir)
        self._study_transfer_syntaxes: dict[str, str] = {}
        self._stress_study_cache: dict[str, list[Dataset]] = {}
        self._study_cache: OrderedDict[tuple[str, str, bool], list[Dataset]] = OrderedDict()
        self._study_cache_max_size: int = 50
        self._stow_datasets: dict[str, Dataset] = {}

    def clear_cache(self, study_uid: str | None = None, clear_stow: bool = False) -> None:
        """Clear cached transfer syntaxes and study instances."""
        if study_uid:
            keys_to_remove = [k for k in self._study_cache if k[0] == str(study_uid)]
            for k in keys_to_remove:
                self._study_cache.pop(k, None)
            self._study_transfer_syntaxes.pop(study_uid, None)
            self._stress_study_cache.pop(study_uid, None)
            if clear_stow:
                self._stow_datasets = {
                    k: v
                    for k, v in self._stow_datasets.items()
                    if str(getattr(v, "StudyInstanceUID", "")) != str(study_uid)
                }
        else:
            self._study_cache.clear()
            self._study_transfer_syntaxes.clear()
            self._stress_study_cache.clear()
            if clear_stow:
                self._stow_datasets.clear()

    def clear_stress_cache(self) -> None:
        """Clear cached transfer syntaxes and study instances for stress mode and WADO requests."""
        self.clear_cache()

    def _get_stored_files(self) -> list[Path]:
        """Get all stored .dcm files on disk."""
        files: list[Path] = []
        if self.storage_dir.exists():
            files.extend([p for p in self.storage_dir.rglob("*.dcm") if p.is_file()])
        if self.received_dir.exists():
            files.extend([p for p in self.received_dir.rglob("*.dcm") if p.is_file()])
        return files

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

        # 3. Collect from STOW-RS stored instances
        for ds in self._stow_datasets.values():
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

        # 3. Collect from STOW-RS stored instances
        for ds in self._stow_datasets.values():
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

        inc_param = (
            query_params.get("includefield") or query_params.get("includeField") or query_params.get("includefields")
        )
        req_fields: set[str] = set()
        include_all = False
        if inc_param:
            if isinstance(inc_param, str):
                raw_tokens = [t.strip() for t in inc_param.split(",") if t.strip()]
            elif isinstance(inc_param, (list, tuple)):
                raw_tokens = []
                for item in inc_param:
                    raw_tokens.extend([t.strip() for t in str(item).split(",") if t.strip()])
            else:
                raw_tokens = []

            for tok in raw_tokens:
                if tok.lower() == "all":
                    include_all = True
                    break
                clean_tok = tok.replace(",", "").replace(":", "")
                req_fields.add(clean_tok.lower())

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

            # Dates and Times (SeriesDate / SeriesTime)
            if "SeriesDate" in ds and ds.SeriesDate:
                out_ds.SeriesDate = ds.SeriesDate
            elif "StudyDate" in ds and ds.StudyDate:
                out_ds.SeriesDate = ds.StudyDate

            if "SeriesTime" in ds and ds.SeriesTime:
                out_ds.SeriesTime = ds.SeriesTime
            elif "StudyTime" in ds and ds.StudyTime:
                out_ds.SeriesTime = ds.StudyTime

            # PresentationCreationDate (0070,0082) & PresentationCreationTime (0070,0083)
            modality_val = str(getattr(ds, "Modality", "")).upper()
            if "PresentationCreationDate" in ds and ds.PresentationCreationDate:
                out_ds.PresentationCreationDate = ds.PresentationCreationDate
            elif modality_val == "PR":
                if "SeriesDate" in out_ds and out_ds.SeriesDate:
                    out_ds.PresentationCreationDate = out_ds.SeriesDate
                elif "StudyDate" in ds and ds.StudyDate:
                    out_ds.PresentationCreationDate = ds.StudyDate

            if "PresentationCreationTime" in ds and ds.PresentationCreationTime:
                out_ds.PresentationCreationTime = ds.PresentationCreationTime
            elif modality_val == "PR":
                if "SeriesTime" in out_ds and out_ds.SeriesTime:
                    out_ds.PresentationCreationTime = out_ds.SeriesTime
                elif "StudyTime" in ds and ds.StudyTime:
                    out_ds.PresentationCreationTime = ds.StudyTime

            # If includefield is specified, also copy any additional requested fields present in ds
            if include_all or req_fields:
                for elem in ds:
                    tag_hex = f"{elem.tag.group:04x}{elem.tag.element:04x}".lower()
                    tag_keyword = elem.keyword.lower() if hasattr(elem, "keyword") else ""
                    if include_all or tag_hex in req_fields or (tag_keyword and tag_keyword in req_fields):
                        if (
                            hasattr(elem, "keyword")
                            and elem.keyword
                            and elem.keyword not in ("PixelData", "OverlayData")
                        ):
                            setattr(out_ds, elem.keyword, elem.value)

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

        # 3. Collect from STOW-RS stored instances
        for ds in self._stow_datasets.values():
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
        modality_q = query_params.get("Modality") or query_params.get("modality")

        matched: list[Dataset] = []
        for ds in instance_datasets:
            if sop_uid_q and not self._matches_filter(getattr(ds, "SOPInstanceUID", None), sop_uid_q):
                continue
            if sop_class_q and not self._matches_filter(getattr(ds, "SOPClassUID", None), sop_class_q):
                continue
            if inst_num and not self._matches_filter(getattr(ds, "InstanceNumber", None), inst_num):
                continue
            if modality_q and not self._matches_filter(getattr(ds, "Modality", None), modality_q):
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
            if "Modality" in ds:
                out_ds.Modality = ds.Modality
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
            for tag in (
                "ContentLabel",
                "ContentDescription",
                "PresentationCreationDate",
                "PresentationCreationTime",
                "ContentCreatorName",
                "ReferencedSeriesSequence",
                "GraphicAnnotationSequence",
                "GraphicLayerSequence",
            ):
                if tag in ds:
                    setattr(out_ds, tag, getattr(ds, tag))

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
        Cached across repetitive WADO requests for the same study/series to avoid redundant transcoding.
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

        # Determine canonical transfer syntax UID for cache key
        lookup_ts = effective_ts
        if not lookup_ts and self.mwl_service:
            matched_entries = self.mwl_service.find_entries(study_uid=study_uid)
            if matched_entries and matched_entries[0].get("transfer_syntax"):
                lookup_ts = matched_entries[0].get("transfer_syntax")
        if not lookup_ts:
            lookup_ts = getattr(config, "transfer_syntax", "JPEG2000_LOSSLESS")

        target_ts_uid = str(resolve_transfer_syntax(lookup_ts))
        cache_key = (str(study_uid), target_ts_uid, is_stress)

        if cache_key in self._study_cache:
            cached = self._study_cache[cache_key]
            if num_instances is None or len(cached) >= num_instances:
                self._study_cache.move_to_end(cache_key)
                logger.debug(
                    "wado_study_cache_hit",
                    study_uid=study_uid,
                    transfer_syntax=target_ts_uid,
                    cached_instances=len(cached),
                    requested_instances=num_instances,
                )
                if num_instances is not None and len(cached) > num_instances:
                    return cached[:num_instances]
                return cached

        logger.debug(
            "wado_study_cache_miss",
            study_uid=study_uid,
            transfer_syntax=target_ts_uid,
            requested_instances=num_instances,
        )

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
        disk_datasets = [
            ds for ds in self._read_stored_datasets() if str(getattr(ds, "StudyInstanceUID", "")) == str(study_uid)
        ]
        if disk_datasets:
            existing_sops = {str(getattr(d, "SOPInstanceUID", "")) for d in datasets}
            for d_ds in disk_datasets:
                if str(getattr(d_ds, "SOPInstanceUID", "")) not in existing_sops:
                    datasets.append(d_ds)

        # 3. Check in-memory STOW-RS received datasets
        stow_instances = [
            ds for ds in self._stow_datasets.values() if str(getattr(ds, "StudyInstanceUID", "")) == str(study_uid)
        ]
        if stow_instances:
            existing_sops = {str(getattr(d, "SOPInstanceUID", "")) for d in datasets}
            for s_ds in stow_instances:
                if str(getattr(s_ds, "SOPInstanceUID", "")) not in existing_sops:
                    datasets.append(s_ds)

        if is_stress and datasets:
            self._stress_study_cache[study_uid] = datasets

        if datasets:
            self._study_cache[cache_key] = datasets
            self._study_cache.move_to_end(cache_key)
            if len(self._study_cache) > self._study_cache_max_size:
                self._study_cache.popitem(last=False)

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
        metadata_list = []
        for ds in datasets:
            # Fast copy omitting PixelData to avoid duplicating large byte arrays
            if (0x7FE0, 0x0010) in ds or (0x7FE0, 0x0001) in ds:
                ds_copy = Dataset({k: v for k, v in ds.items() if k not in ((0x7FE0, 0x0010), (0x7FE0, 0x0001))})
                if hasattr(ds, "file_meta"):
                    ds_copy.file_meta = ds.file_meta
            else:
                ds_copy = Dataset(ds)
                if hasattr(ds, "file_meta"):
                    ds_copy.file_meta = ds.file_meta

            has_pixel_data = (0x7FE0, 0x0010) in ds or (0x7FE0, 0x0008) in ds or (0x7FE0, 0x0009) in ds
            if requested_transfer_syntax and has_pixel_data:
                target_uid = resolve_transfer_syntax(requested_transfer_syntax)
                if hasattr(ds_copy, "file_meta"):
                    ds_copy.file_meta.TransferSyntaxUID = target_uid
                if target_uid == JPEGBaseline8Bit:
                    ds_copy.BitsAllocated = 8
                    ds_copy.BitsStored = 8
                    ds_copy.HighBit = 7
                    ds_copy.WindowCenter = 128
                    ds_copy.WindowWidth = 256
                    ds_copy.PhotometricInterpretation = "MONOCHROME2"
                    ds_copy.SamplesPerPixel = 1
                    ds_copy.PixelRepresentation = 0
            elif not has_pixel_data:
                if hasattr(ds_copy, "file_meta") and ds_copy.file_meta:
                    curr_ts = getattr(ds_copy.file_meta, "TransferSyntaxUID", None)
                    if not curr_ts or str(curr_ts) not in (str(ExplicitVRLittleEndian), "1.2.840.10008.1.2"):
                        ds_copy.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
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
            has_pixel_data = (0x7FE0, 0x0010) in ds or (0x7FE0, 0x0008) in ds or (0x7FE0, 0x0009) in ds
            target_ts = effective_target_ts if has_pixel_data else None
            if target_ts and getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None) != target_ts:
                ds = DicomGeneratorService.apply_transfer_syntax(ds, target_ts)
            elif not has_pixel_data:
                if not hasattr(ds, "file_meta") or ds.file_meta is None:
                    ds.file_meta = FileMetaDataset()
                curr_ts = getattr(ds.file_meta, "TransferSyntaxUID", None)
                if not curr_ts or str(curr_ts) not in (str(ExplicitVRLittleEndian), "1.2.840.10008.1.2"):
                    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

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
        has_pixel_data = (0x7FE0, 0x0010) in dataset or (0x7FE0, 0x0008) in dataset or (0x7FE0, 0x0009) in dataset
        if not has_pixel_data:
            raise ValueError("Dataset contains no pixel data to render")

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

        try:
            from pydicom.encaps import generate_frames
        except ImportError:
            from pydicom.encaps import generate_pixel_data_frame as generate_frames  # type: ignore

        from pydicom.uid import (
            JPEG2000,
            ExplicitVRLittleEndian,
            JPEG2000Lossless,
            JPEGBaseline8Bit,
            RLELossless,
        )

        from dicom_py_mock_server.services.generator import resolve_transfer_syntax

        has_pixel_data = (0x7FE0, 0x0010) in dataset or (0x7FE0, 0x0008) in dataset or (0x7FE0, 0x0009) in dataset
        if not has_pixel_data:
            return [], "application/octet-stream"

        current_ts = getattr(getattr(dataset, "file_meta", None), "TransferSyntaxUID", None)
        if requested_transfer_syntax:
            target_uid = resolve_transfer_syntax(requested_transfer_syntax)
        else:
            target_uid = current_ts or ExplicitVRLittleEndian

        if target_uid in (JPEG2000Lossless, JPEG2000):
            media_type = "image/jp2"
        elif target_uid == RLELossless:
            media_type = "image/rle"
        elif target_uid == JPEGBaseline8Bit:
            media_type = "image/jpeg"
        else:
            media_type = "application/octet-stream"

        # Optimization: If dataset is already encapsulated in the requested transfer syntax,
        # extract the requested frames directly without decompressing and re-encoding.
        if current_ts == target_uid and getattr(target_uid, "is_encapsulated", False) and hasattr(dataset, "PixelData"):
            try:
                all_enc_frames = list(generate_frames(dataset.PixelData))
                frames = []
                for fn in frame_numbers:
                    idx = fn - 1
                    if 0 <= idx < len(all_enc_frames):
                        frames.append(all_enc_frames[idx])
                if frames:
                    return frames, media_type
            except Exception as exc:
                logger.warning("direct_encapsulated_frame_extraction_failed", error=str(exc))

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
            samples_per_pixel = getattr(dataset, "SamplesPerPixel", 1)
            if samples_per_pixel == 3 and arr.shape[-1] == 3:
                if 1 in frame_numbers:
                    frame_arrays.append(arr)
            else:
                for fn in frame_numbers:
                    idx = fn - 1
                    if 0 <= idx < arr.shape[0]:
                        frame_arrays.append(arr[idx])
        elif arr.ndim == 4:
            for fn in frame_numbers:
                idx = fn - 1
                if 0 <= idx < arr.shape[0]:
                    frame_arrays.append(arr[idx])

        if not frame_arrays:
            return [], "application/octet-stream"

        if target_uid == JPEGBaseline8Bit:
            for f_arr in frame_arrays:
                if f_arr.dtype == np.uint8:
                    f_arr8 = f_arr
                else:
                    arr_min = float(f_arr.min())
                    arr_max = float(f_arr.max())
                    if arr_max > arr_min:
                        scaled = ((f_arr.astype(np.float32) - arr_min) / (arr_max - arr_min)) * 255.0
                        f_arr8 = np.clip(scaled, 0, 255).astype(np.uint8)
                    else:
                        f_arr8 = np.zeros(f_arr.shape, dtype=np.uint8)
                mode = "RGB" if f_arr8.ndim == 3 and f_arr8.shape[-1] == 3 else "L"
                img = Image.fromarray(f_arr8, mode=mode)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=95)
                frames.append(buf.getvalue())
        elif target_uid in (JPEG2000Lossless, JPEG2000):
            for f_arr in frame_arrays:
                is_16bit = f_arr.itemsize == 2 or f_arr.dtype in (np.int16, np.uint16)
                is_signed = np.issubdtype(f_arr.dtype, np.signedinteger)

                temp_ds = Dataset()
                temp_ds.Rows, temp_ds.Columns = f_arr.shape[:2]
                bits_alloc = getattr(dataset, "BitsAllocated", 16 if is_16bit else 8)
                if is_16bit and bits_alloc < 16:
                    bits_alloc = 16
                temp_ds.BitsAllocated = bits_alloc
                temp_ds.BitsStored = getattr(dataset, "BitsStored", bits_alloc)
                temp_ds.HighBit = getattr(dataset, "HighBit", temp_ds.BitsStored - 1)
                temp_ds.PixelRepresentation = getattr(dataset, "PixelRepresentation", 1 if is_signed else 0)
                temp_ds.SamplesPerPixel = getattr(dataset, "SamplesPerPixel", 1)
                temp_ds.PhotometricInterpretation = getattr(dataset, "PhotometricInterpretation", "MONOCHROME2")
                if hasattr(dataset, "PlanarConfiguration"):
                    temp_ds.PlanarConfiguration = dataset.PlanarConfiguration
                temp_ds.PixelData = f_arr.tobytes()
                temp_ds.file_meta = FileMetaDataset()
                temp_ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                try:
                    if target_uid == JPEG2000:
                        temp_ds.compress(JPEG2000, j2k_cr=[10], generate_instance_uid=False)
                    else:
                        temp_ds.compress(JPEG2000Lossless, generate_instance_uid=False)
                    enc_frame = next(generate_frames(temp_ds.PixelData))
                    frames.append(enc_frame)
                except Exception as exc:
                    logger.warning("j2k_frame_compression_failed_falling_back_to_raw", error=str(exc))
                    frames.append(f_arr.tobytes())
                    media_type = "application/octet-stream"
        elif target_uid == RLELossless:
            for f_arr in frame_arrays:
                is_16bit = f_arr.itemsize == 2 or f_arr.dtype in (np.int16, np.uint16)
                is_signed = np.issubdtype(f_arr.dtype, np.signedinteger)

                temp_ds = Dataset()
                temp_ds.Rows, temp_ds.Columns = f_arr.shape[:2]
                bits_alloc = getattr(dataset, "BitsAllocated", 16 if is_16bit else 8)
                if is_16bit and bits_alloc < 16:
                    bits_alloc = 16
                temp_ds.BitsAllocated = bits_alloc
                temp_ds.BitsStored = getattr(dataset, "BitsStored", bits_alloc)
                temp_ds.HighBit = getattr(dataset, "HighBit", temp_ds.BitsStored - 1)
                temp_ds.PixelRepresentation = getattr(dataset, "PixelRepresentation", 1 if is_signed else 0)
                temp_ds.SamplesPerPixel = getattr(dataset, "SamplesPerPixel", 1)
                temp_ds.PhotometricInterpretation = getattr(dataset, "PhotometricInterpretation", "MONOCHROME2")
                if hasattr(dataset, "PlanarConfiguration"):
                    temp_ds.PlanarConfiguration = dataset.PlanarConfiguration
                temp_ds.PixelData = f_arr.tobytes()
                temp_ds.file_meta = FileMetaDataset()
                temp_ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                try:
                    temp_ds.compress(RLELossless, generate_instance_uid=False)
                    enc_frame = next(generate_frames(temp_ds.PixelData))
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

    # ---------------------------------------------------------------------------
    # STOW-RS (Store Instances) Implementation
    # ---------------------------------------------------------------------------

    def parse_stow_payload(self, body: bytes, content_type: str) -> list[Dataset]:
        """Parse DICOM datasets from a STOW-RS request body.

        Supports standard multipart/related (type="application/dicom"), multipart/form-data,
        and direct application/dicom or raw binary DICOM datasets.
        """
        if not body:
            return []

        datasets: list[Dataset] = []
        boundary_match = re.search(r'boundary=(?:"([^"]+)"|([^\s;,]+))', content_type, re.IGNORECASE)

        if boundary_match:
            raw_boundary = boundary_match.group(1) if boundary_match.group(1) is not None else boundary_match.group(2)
            boundary_bytes = raw_boundary.strip().encode("latin1")
            delimiter = b"--" + boundary_bytes

            parts = body.split(delimiter)
            for raw_part in parts:
                part = raw_part.strip()
                if not part or part == b"--" or part.startswith(b"--"):
                    continue

                # Split headers and body
                if b"\r\n\r\n" in part:
                    _, _, part_body = part.partition(b"\r\n\r\n")
                elif b"\n\n" in part:
                    _, _, part_body = part.partition(b"\n\n")
                else:
                    part_body = part

                if part_body.endswith(b"\r\n"):
                    part_body = part_body[:-2]
                elif part_body.endswith(b"\n"):
                    part_body = part_body[:-1]

                if not part_body:
                    continue

                try:
                    ds = pydicom.dcmread(io.BytesIO(part_body), force=True)
                    datasets.append(ds)
                except Exception as exc:
                    logger.warning("stow_payload_part_parse_failed", error=str(exc))
        else:
            # Try reading the entire body as a single Part-10 DICOM or raw dataset
            try:
                ds = pydicom.dcmread(io.BytesIO(body), force=True)
                datasets.append(ds)
            except Exception as exc:
                logger.warning("stow_payload_direct_parse_failed", error=str(exc))

        return datasets

    def store_instance(
        self,
        dataset: Dataset,
        target_study_uid: str | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Store a single DICOM instance to disk (Part-10) and memory.

        Returns (referenced_sop_dict, failed_sop_dict).
        """
        sop_class_uid = str(getattr(dataset, "SOPClassUID", "")).strip()
        sop_instance_uid = str(getattr(dataset, "SOPInstanceUID", "")).strip()
        study_uid = str(getattr(dataset, "StudyInstanceUID", "")).strip()
        series_uid = str(getattr(dataset, "SeriesInstanceUID", "")).strip()

        if not sop_class_uid or not sop_instance_uid or not study_uid:
            return None, {
                "ReferencedSOPClassUID": sop_class_uid or "1.2.840.10008.5.1.4.1.1.2",
                "ReferencedSOPInstanceUID": sop_instance_uid or "0",
                "FailureReason": 0x0110,  # Processing failure
            }

        if target_study_uid and study_uid != target_study_uid:
            logger.warning(
                "stow_study_instance_uid_mismatch",
                target_study_uid=target_study_uid,
                dataset_study_uid=study_uid,
                sop_instance_uid=sop_instance_uid,
            )
            return None, {
                "ReferencedSOPClassUID": sop_class_uid,
                "ReferencedSOPInstanceUID": sop_instance_uid,
                "FailureReason": 0x0122,  # Referenced Study does not match
            }

        dup_policy = getattr(config, "stow_duplicate_handling", "accept").lower().strip()
        is_duplicate = sop_instance_uid in self._stow_datasets
        warning_reason: int | None = None

        if is_duplicate:
            if dup_policy == "reject":
                logger.warning(
                    "stow_duplicate_instance_rejected",
                    sop_instance_uid=sop_instance_uid,
                    study_uid=study_uid,
                )
                return None, {
                    "ReferencedSOPClassUID": sop_class_uid,
                    "ReferencedSOPInstanceUID": sop_instance_uid,
                    "FailureReason": 0x0111,  # Duplicate SOP Instance
                }
            elif dup_policy == "warn":
                warning_reason = 0xB000  # Coercion of Data Elements / Duplicate

        # Ensure Part-10 File Meta Information
        if not hasattr(dataset, "file_meta") or not dataset.file_meta:
            dataset.file_meta = FileMetaDataset()
        if not getattr(dataset.file_meta, "MediaStorageSOPClassUID", None):
            dataset.file_meta.MediaStorageSOPClassUID = sop_class_uid
        if not getattr(dataset.file_meta, "MediaStorageSOPInstanceUID", None):
            dataset.file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
        if not getattr(dataset.file_meta, "TransferSyntaxUID", None):
            dataset.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

        # Save Part-10 file to received folder: ./received/{study}/{series}/{sop}.dcm
        study_folder = study_uid if study_uid else "unknown_study"
        series_folder = series_uid if series_uid else "unknown_series"
        out_dir = self.received_dir / study_folder / series_folder
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            file_path = out_dir / f"{sop_instance_uid}.dcm"
            dataset.save_as(file_path, enforce_file_format=True)
        except Exception as exc:
            logger.error("stow_file_save_failed", path=str(out_dir), error=str(exc))
            return None, {
                "ReferencedSOPClassUID": sop_class_uid,
                "ReferencedSOPInstanceUID": sop_instance_uid,
                "FailureReason": 0x0110,
            }

        # Cache in memory
        self._stow_datasets[sop_instance_uid] = dataset
        self.clear_cache(study_uid)

        logger.info(
            "stow_instance_stored",
            sop_instance_uid=sop_instance_uid,
            study_uid=study_uid,
            series_uid=series_uid,
            path=str(file_path),
            is_duplicate=is_duplicate,
            warning_reason=warning_reason,
        )

        retrieve_url = f"/dicomweb/studies/{study_uid}/series/{series_uid}/instances/{sop_instance_uid}"
        ref_dict: dict[str, Any] = {
            "ReferencedSOPClassUID": sop_class_uid,
            "ReferencedSOPInstanceUID": sop_instance_uid,
            "RetrieveURL": retrieve_url,
        }
        if warning_reason is not None:
            ref_dict["WarningReason"] = warning_reason

        return ref_dict, None

    def process_stow_request(
        self,
        target_study_uid: str | None,
        content_type: str | None,
        body: bytes,
    ) -> tuple[int, dict[str, Any]]:
        """Process a STOW-RS request and return (status_code, dicom_json_response)."""
        if not body or len(body) == 0:
            resp_ds = Dataset()
            resp_ds.FailedSOPSequence = []
            f_item = Dataset()
            f_item.ReferencedSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
            f_item.ReferencedSOPInstanceUID = "0"
            f_item.FailureReason = 0x0110
            resp_ds.FailedSOPSequence.append(f_item)
            return 400, resp_ds.to_json_dict(suppress_invalid_tags=True)

        datasets = self.parse_stow_payload(body, content_type or "")
        if not datasets:
            resp_ds = Dataset()
            resp_ds.FailedSOPSequence = []
            f_item = Dataset()
            f_item.ReferencedSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
            f_item.ReferencedSOPInstanceUID = "0"
            f_item.FailureReason = 0x0110
            resp_ds.FailedSOPSequence.append(f_item)
            return 400, resp_ds.to_json_dict(suppress_invalid_tags=True)

        referenced_sops: list[dict[str, Any]] = []
        failed_sops: list[dict[str, Any]] = []

        for ds in datasets:
            ref_item, failed_item = self.store_instance(ds, target_study_uid=target_study_uid)
            if ref_item:
                referenced_sops.append(ref_item)
            if failed_item:
                failed_sops.append(failed_item)

        if not referenced_sops:
            all_conflicts = all(f.get("FailureReason") in (0x0122, 0x0111) for f in failed_sops)
            status_code = 409 if all_conflicts else 400
        elif failed_sops:
            status_code = 202
        else:
            status_code = 200

        resp_ds = Dataset()
        if referenced_sops:
            resp_ds.ReferencedSOPSequence = []
            for ref in referenced_sops:
                item = Dataset()
                item.ReferencedSOPClassUID = ref["ReferencedSOPClassUID"]
                item.ReferencedSOPInstanceUID = ref["ReferencedSOPInstanceUID"]
                if "RetrieveURL" in ref:
                    item.RetrieveURL = ref["RetrieveURL"]
                if "WarningReason" in ref:
                    item.WarningReason = int(ref["WarningReason"])
                resp_ds.ReferencedSOPSequence.append(item)

        if failed_sops:
            resp_ds.FailedSOPSequence = []
            for fl in failed_sops:
                item = Dataset()
                item.ReferencedSOPClassUID = fl["ReferencedSOPClassUID"]
                item.ReferencedSOPInstanceUID = fl["ReferencedSOPInstanceUID"]
                item.FailureReason = int(fl["FailureReason"])
                resp_ds.FailedSOPSequence.append(item)

        return status_code, resp_ds.to_json_dict(suppress_invalid_tags=True)
