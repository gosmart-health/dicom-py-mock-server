"""Service for generating synthetic DICOM objects using pydicom."""

import io
import time
from pathlib import Path

import numpy as np

from PIL import Image, ImageDraw, ImageFont
import structlog
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.uid import (
    CTImageStorage,
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
    JPEGBaseline8Bit,
    JPEG2000,
    JPEG2000Lossless,
    RLELossless,
    generate_uid,
)

from dicom_py_mock_server.config import config
from dicom_py_mock_server.models.dicom import MockDicomRequest, MockDicomResponse, RawImageGeneratorRequest

logger = structlog.get_logger(__name__)


TRANSFER_SYNTAX_MAP = {
    "RAW": ExplicitVRLittleEndian,
    "EXPLICIT_RAW": ExplicitVRLittleEndian,
    "EXPLICIT_VR_LITTLE_ENDIAN": ExplicitVRLittleEndian,
    "1.2.840.10008.1.2.1": ExplicitVRLittleEndian,
    "IMPLICIT_RAW": ImplicitVRLittleEndian,
    "IMPLICIT_VR_LITTLE_ENDIAN": ImplicitVRLittleEndian,
    "1.2.840.10008.1.2": ImplicitVRLittleEndian,
    "JPEG": JPEGBaseline8Bit,
    "JPEG_PROCESS_1": JPEGBaseline8Bit,
    "JPEG_BASELINE": JPEGBaseline8Bit,
    "1.2.840.10008.1.2.4.50": JPEGBaseline8Bit,
    "JPEG2000": JPEG2000Lossless,
    "JPEG2000_LOSSLESS": JPEG2000Lossless,
    "1.2.840.10008.1.2.4.90": JPEG2000Lossless,
    "JPEG2000_LOSSY": JPEG2000,
    "1.2.840.10008.1.2.4.91": JPEG2000,
    "RLE": RLELossless,
    "RLE_LOSSLESS": RLELossless,
    "1.2.840.10008.1.2.5": RLELossless,
}


class DicomGeneratorService:
    """Service to create pydicom Datasets from Pydantic request models."""

    @staticmethod
    def burn_metadata_text(
        rows: int,
        cols: int,
        patient_name: str,
        patient_id: str,
        study_date: str,
        study_time: str,
        image_number: int,
        background_val: int = 500,
        text_val: int = 60000,
    ) -> np.ndarray:
        """Burn metadata strings into a 16-bit uint16 image matrix from top-left with ~24px height."""
        # Create base array with subtle pattern or background
        base_arr = np.zeros((rows, cols), dtype=np.uint16)
        for r in range(rows):
            for c in range(cols):
                base_arr[r, c] = (r // 2 + c // 2 + background_val) % 4096

        img = Image.fromarray(base_arr)
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.load_default(size=24)
        except Exception:
            font = ImageFont.load_default()

        labels = [
            f"Patient Name: {patient_name}",
            f"Patient ID: {patient_id}",
            f"Study Date: {study_date} {study_time}",
            f"Image: {image_number}",
        ]

        x = 16
        y = 16
        for line in labels:
            draw.text((x, y), line, fill=text_val, font=font)
            if hasattr(font, "getbbox"):
                bbox = font.getbbox(line)
                line_height = bbox[3] - bbox[1] if bbox else 24
            else:
                line_height = 24
            y += max(line_height, 24) + 6

        return np.array(img, dtype=np.uint16)

    @classmethod
    def apply_transfer_syntax(cls, ds: FileDataset, syntax_name: str | None = None) -> FileDataset:
        """Convert or set dataset Transfer Syntax UID and encode pixel data accordingly."""
        target_name = (syntax_name or getattr(config, "transfer_syntax", "RAW")).upper().strip()
        target_uid = TRANSFER_SYNTAX_MAP.get(target_name, ExplicitVRLittleEndian)

        if target_uid in (ExplicitVRLittleEndian, ImplicitVRLittleEndian):
            ds.file_meta.TransferSyntaxUID = target_uid
            # Enforce uncompressed pixel representation
            arr = np.frombuffer(ds.PixelData, dtype=np.uint16) if isinstance(ds.PixelData, bytes) else ds.pixel_array
            ds.PixelData = arr.astype(np.uint16).tobytes()
            return ds

        if target_uid == JPEGBaseline8Bit:
            # JPEG Process 1 is 8-bit baseline
            arr16 = np.frombuffer(ds.PixelData, dtype=np.uint16).reshape((ds.Rows, ds.Columns))
            arr8 = (arr16 >> 8).astype(np.uint8) if arr16.max() > 255 else arr16.astype(np.uint8)
            img = Image.fromarray(arr8)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=95)
            jpeg_bytes = buf.getvalue()

            ds.file_meta.TransferSyntaxUID = JPEGBaseline8Bit
            ds.BitsAllocated = 8
            ds.BitsStored = 8
            ds.HighBit = 7
            ds.PixelData = encapsulate([jpeg_bytes])
            return ds

        if target_uid in (JPEG2000Lossless, JPEG2000, RLELossless):
            try:
                ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                ds.compress(target_uid)
                return ds
            except Exception as exc:
                logger.warning(
                    "compression_failed_falling_back_to_raw",
                    target_uid=str(target_uid),
                    error=str(exc),
                )
                ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                return ds

        ds.file_meta.TransferSyntaxUID = target_uid
        return ds

    @classmethod
    def create_dicom_file(cls, request: MockDicomRequest, instance_number: int = 1) -> FileDataset:
        """Create a single pydicom FileDataset populated with metadata and pixel data."""
        study_uid = request.study.study_instance_uid or generate_uid()
        series_uid = request.series.series_instance_uid or generate_uid()
        sop_instance_uid = generate_uid()

        # File Meta Information
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = CTImageStorage
        file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

        # Dataset initialization
        ds = FileDataset("mock.dcm", {}, file_meta=file_meta, preamble=b"\x00" * 128)

        # Patient Module
        patient_id = request.patient.patient_id
        patient_name = request.patient.patient_name
        ds.PatientID = patient_id
        ds.PatientName = patient_name
        if request.patient.patient_birth_date:
            ds.PatientBirthDate = request.patient.patient_birth_date
        if request.patient.patient_sex:
            ds.PatientSex = request.patient.patient_sex

        # General Study Module
        study_date = request.study.study_date or time.strftime("%Y%m%d")
        study_time = request.study.study_time or time.strftime("%H%M%S")
        ds.StudyInstanceUID = study_uid
        ds.StudyDate = study_date
        ds.StudyTime = study_time
        ds.AccessionNumber = request.study.accession_number or ""
        ds.StudyDescription = request.study.study_description or ""

        # General Series Module
        ds.SeriesInstanceUID = series_uid
        ds.Modality = request.series.modality
        ds.SeriesNumber = request.series.series_number
        ds.SeriesDescription = request.series.series_description or ""

        # SOP Common Module
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = sop_instance_uid
        ds.InstanceNumber = instance_number

        # Image Pixel Module
        rows = request.rows
        cols = request.columns
        ds.Rows = rows
        ds.Columns = cols
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"

        if request.burn_in_text:
            pixel_matrix = cls.burn_metadata_text(
                rows=rows,
                cols=cols,
                patient_name=patient_name,
                patient_id=patient_id,
                study_date=study_date,
                study_time=study_time,
                image_number=instance_number,
            )
        else:
            pixel_matrix = np.zeros((rows, cols), dtype=np.uint16)
            for r in range(rows):
                for c in range(cols):
                    pixel_matrix[r, c] = (r + c + instance_number * 10) % 65536

        ds.PixelData = pixel_matrix.tobytes()

        # Swap transfer syntax if specified or configured
        syntax_to_apply = request.transfer_syntax or getattr(config, "transfer_syntax", "RAW")
        ds = cls.apply_transfer_syntax(ds, syntax_to_apply)

        return ds

    @classmethod
    def create_raw_dicom_file(cls, raw_req: RawImageGeneratorRequest) -> FileDataset:
        """Create a 16-bit 512x512 DICOM file with burned-in metadata strings from explicit parameters."""
        mock_req = MockDicomRequest(
            patient={"patient_id": raw_req.patient_id, "patient_name": raw_req.patient_name},
            study={"study_date": raw_req.study_date, "study_time": raw_req.study_time},
            num_instances=1,
            rows=raw_req.rows,
            columns=raw_req.columns,
            transfer_syntax=raw_req.transfer_syntax,
            burn_in_text=True,
        )
        return cls.create_dicom_file(mock_req, instance_number=raw_req.image_number)

    @classmethod
    def create_instances_from_mwl(cls, mwl_record: dict[str, Any], num_instances: int = 8) -> list[FileDataset]:
        """Synthesize DICOM image FileDatasets on the fly matching an MWL record."""
        json_e = mwl_record.get("json_entry", {})
        patient_id = mwl_record.get("patient_id", "MOCK_PATIENT_ID")
        patient_name = mwl_record.get("patient_name", "MOCK^PATIENT")
        study_uid = mwl_record.get("study_uid") or generate_uid()
        accession = mwl_record.get("accession", "")
        modality = mwl_record.get("modality", "CT")

        sps_seq = json_e.get("00400100", {}).get("Value", [{}])[0]
        study_date = sps_seq.get("00400002", {}).get("Value", [time.strftime("%Y%m%d")])[0]
        study_time = sps_seq.get("00400003", {}).get("Value", [time.strftime("%H%M%S")])[0]
        study_desc = json_e.get("00081030", {}).get("Value", ["Synthetic Study"])[0]
        patient_sex = json_e.get("00100040", {}).get("Value", ["U"])[0]
        patient_dob = json_e.get("00100030", {}).get("Value", [""])[0]

        series_uid = generate_uid()
        mock_req = MockDicomRequest(
            patient={
                "patient_id": patient_id,
                "patient_name": patient_name,
                "patient_birth_date": patient_dob if patient_dob else None,
                "patient_sex": patient_sex if patient_sex else None,
            },
            study={
                "study_instance_uid": study_uid,
                "study_date": study_date,
                "study_time": study_time,
                "accession_number": accession,
                "study_description": study_desc,
            },
            series={
                "series_instance_uid": series_uid,
                "modality": modality,
                "series_number": 1,
                "series_description": f"{modality} Series",
            },
            num_instances=num_instances,
            burn_in_text=True,
        )

        datasets = []
        for i in range(1, num_instances + 1):
            ds = cls.create_dicom_file(mock_req, instance_number=i)
            datasets.append(ds)
        return datasets

    def generate_and_save(self, request: MockDicomRequest, target_dir: str) -> MockDicomResponse:
        """Generate a batch of DICOM files and save them to target_dir."""
        out_path = Path(target_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        study_uid = request.study.study_instance_uid or generate_uid()
        series_uid = request.series.series_instance_uid or generate_uid()

        # Update request object with UIDs if generated
        request.study.study_instance_uid = study_uid
        request.series.series_instance_uid = series_uid

        saved_files: list[str] = []

        for i in range(1, request.num_instances + 1):
            ds = self.create_dicom_file(request, instance_number=i)
            filename = out_path / f"instance_{i:04d}_{ds.SOPInstanceUID}.dcm"
            ds.save_as(filename, enforce_file_format=True)
            saved_files.append(str(filename.resolve()))

        logger.info(
            "dicom_generation_completed",
            patient_id=request.patient.patient_id,
            study_uid=study_uid,
            series_uid=series_uid,
            num_instances=len(saved_files),
            transfer_syntax=request.transfer_syntax or getattr(config, "transfer_syntax", "RAW"),
        )

        return MockDicomResponse(
            success=True,
            message=f"Generated {len(saved_files)} DICOM files",
            patient_id=request.patient.patient_id,
            study_instance_uid=study_uid,
            series_instance_uid=series_uid,
            generated_instances=len(saved_files),
            file_paths=saved_files,
        )
