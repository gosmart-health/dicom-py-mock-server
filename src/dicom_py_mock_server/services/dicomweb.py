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
    def parse_transfer_syntax_header(
        accept_header: str | None = None,
        query_param: str | None = None,
        direct_header: str | None = None,
    ) -> str | None:
        """Extract requested transfer syntax UID or name from headers or query parameters."""
        if direct_header and str(direct_header).strip():
            val = str(direct_header).strip().strip('"').strip("'")
            if val != "*":
                return val

        if query_param and str(query_param).strip():
            val = str(query_param).strip().strip('"').strip("'")
            if val != "*":
                return val

        if not accept_header:
            return None

        # Look for transfer-syntax="1.2.840.10008.1.2.4.90" or transfer-syntax=JPEG200
        match = re.search(r'transfer-syntax\s*=\s*"?([^";,\s]+)"?', accept_header, re.IGNORECASE)
        if match:
            ts = match.group(1).strip()
            if ts == "*":
                return None
            return ts

        # Check if accept header itself directly specifies a known syntax or UID
        raw_accept = accept_header.strip().strip('"').strip("'")
        if raw_accept.upper() in TRANSFER_SYNTAX_MAP or raw_accept in TRANSFER_SYNTAX_MAP:
            return raw_accept

        return None

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

    def get_study_datasets(self, study_uid: str) -> list[Dataset]:
        """Get all full instance datasets for a StudyInstanceUID."""
        datasets: list[Dataset] = []

        # 1. Search in MWL active entries
        if self.mwl_service:
            matched_entries = self.mwl_service.find_entries(study_uid=study_uid)
            for entry in matched_entries:
                inst_list = DicomGeneratorService.create_instances_from_mwl(entry)
                datasets.extend(inst_list)

        # 2. Check stored files on disk
        if not datasets:
            datasets = [
                ds for ds in self._read_stored_datasets() if str(getattr(ds, "StudyInstanceUID", "")) == str(study_uid)
            ]

        return datasets

    def get_series_datasets(self, study_uid: str, series_uid: str) -> list[Dataset]:
        """Get all full instance datasets for a StudyInstanceUID and SeriesInstanceUID."""
        all_study_ds = self.get_study_datasets(study_uid)
        return [ds for ds in all_study_ds if str(getattr(ds, "SeriesInstanceUID", "")) == str(series_uid)]

    def get_instance_dataset(self, study_uid: str, series_uid: str | None, instance_uid: str) -> Dataset | None:
        """Get single instance dataset matching SOPInstanceUID."""
        all_study_ds = self.get_study_datasets(study_uid)
        for ds in all_study_ds:
            if str(getattr(ds, "SOPInstanceUID", "")) == str(instance_uid):
                if series_uid and str(getattr(ds, "SeriesInstanceUID", "")) != str(series_uid):
                    continue
                return ds
        return None

    @staticmethod
    def get_metadata(datasets: list[Dataset]) -> list[dict[str, Any]]:
        """Extract metadata (omitting PixelData and bulk data) in DICOM JSON format."""
        metadata_list = []
        for ds in datasets:
            ds_copy = ds.copy()
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

        for ds in datasets:
            target_ts = requested_transfer_syntax
            if target_ts:
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

    def get_frame_bytes(self, dataset: Dataset, frame_numbers: list[int]) -> list[bytes]:
        """Extract raw pixel frame bytes for specified frame numbers (1-indexed)."""
        frames: list[bytes] = []
        try:
            arr = dataset.pixel_array
            if arr.ndim == 2:
                # Single frame
                if 1 in frame_numbers:
                    frames.append(arr.tobytes())
            elif arr.ndim == 3:
                for fn in frame_numbers:
                    idx = fn - 1
                    if 0 <= idx < arr.shape[0]:
                        frames.append(arr[idx].tobytes())
        except Exception as exc:
            logger.warning("failed_to_extract_frames", error=str(exc))
        return frames
