"""Service for generating synthetic DICOM objects using pydicom."""

import copy
import functools
import io
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from PIL import Image, ImageDraw, ImageFont
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.uid import (
    JPEG2000,
    UID,
    CTImageStorage,
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
    JPEG2000Lossless,
    JPEGBaseline8Bit,
    RLELossless,
)

from dicom_py_mock_server.config import config
from dicom_py_mock_server.models.dicom import (
    MockDicomRequest,
    MockDicomResponse,
    RawImageGeneratorRequest,
)
from dicom_py_mock_server.services.uid_generator import (
    generate_series_uid,
    generate_sop_instance_uid,
    generate_study_uid,
)

logger = structlog.get_logger(__name__)

TRANSFER_SYNTAX_MAP = {
    # Raw / Uncompressed Little Endian
    "RAW": ExplicitVRLittleEndian,
    "EXPLICIT_RAW": ExplicitVRLittleEndian,
    "EXPLICIT_VR_LITTLE_ENDIAN": ExplicitVRLittleEndian,
    "1.2.840.10008.1.2.1": ExplicitVRLittleEndian,
    "IMPLICIT_RAW": ImplicitVRLittleEndian,
    "IMPLICIT_VR_LITTLE_ENDIAN": ImplicitVRLittleEndian,
    "1.2.840.10008.1.2": ImplicitVRLittleEndian,
    # JPEG Baseline (Process 1)
    "JPEG": JPEGBaseline8Bit,
    "JPEG_PROCESS_1": JPEGBaseline8Bit,
    "JPEG_BASELINE": JPEGBaseline8Bit,
    "1.2.840.10008.1.2.4.50": JPEGBaseline8Bit,
    # JPEG 2000 Lossless
    "JPEG2000": JPEG2000Lossless,
    "JPEG200": JPEG2000Lossless,
    "JPEG2000_LOSSLESS": JPEG2000Lossless,
    "JPEG200_LOSSLESS": JPEG2000Lossless,
    "JPEG2000LOSSLESS": JPEG2000Lossless,
    "JPEG200LOSSLESS": JPEG2000Lossless,
    "1.2.840.10008.1.2.4.90": JPEG2000Lossless,
    # JPEG 2000 Lossy
    "JPEG2000_LOSSY": JPEG2000,
    "JPEG200_LOSSY": JPEG2000,
    "JPEG2000LOSSY": JPEG2000,
    "JPEG200LOSSY": JPEG2000,
    "1.2.840.10008.1.2.4.91": JPEG2000,
    # RLE Lossless
    "RLE": RLELossless,
    "RLE_LOSSLESS": RLELossless,
    "RLELOSSLESS": RLELossless,
    "1.2.840.10008.1.2.5": RLELossless,
}


def resolve_transfer_syntax(syntax_name: str | None) -> UID:
    """Resolve a transfer syntax name, alias, or UID string to a pydicom UID."""
    if not syntax_name or not str(syntax_name).strip():
        return ExplicitVRLittleEndian
    name = str(syntax_name).strip().strip('"').strip("'")
    if name in TRANSFER_SYNTAX_MAP:
        return TRANSFER_SYNTAX_MAP[name]
    norm = name.upper().replace("-", "_").replace(" ", "_")
    if norm in TRANSFER_SYNTAX_MAP:
        return TRANSFER_SYNTAX_MAP[norm]
    norm_no_under = norm.replace("_", "")
    if norm_no_under in TRANSFER_SYNTAX_MAP:
        return TRANSFER_SYNTAX_MAP[norm_no_under]
    return ExplicitVRLittleEndian


MODALITY_STUDY_DESCRIPTIONS: dict[str, list[str]] = {
    "CT": [
        "CT Chest without Contrast",
        "CT Chest with Contrast",
        "CT Abdomen and Pelvis with Contrast",
        "CT Abdomen and Pelvis without Contrast",
        "CT Head / Brain without Contrast",
        "CT Head / Brain with Contrast",
        "CT Angiography Chest (PE Protocol)",
        "CT Cervical Spine without Contrast",
        "CT Lumbar Spine without Contrast",
        "CT Sinus / Maxillofacial Complete",
        "CT Soft Tissue Neck with Contrast",
        "CT Extremity Lower Right without Contrast",
    ],
    "MR": [
        "MRI Brain without Contrast",
        "MRI Brain with and without Contrast",
        "MRI Lumbar Spine without Contrast",
        "MRI Cervical Spine without Contrast",
        "MRI Knee Joint Right without Contrast",
        "MRI Knee Joint Left without Contrast",
        "MRI Shoulder Joint Right without Contrast",
        "MRI Shoulder Joint Left without Contrast",
        "MRI Abdomen with and without Contrast",
        "MRI Pelvis Female with and without Contrast",
        "MRI MRCP (Abdomen)",
        "MRA Head and Neck without Contrast",
    ],
    "DX": [
        "XR Chest 1 View AP",
        "XR Chest 2 Views PA and Lateral",
        "XR Abdomen 1 View (KUB)",
        "XR Pelvis 1 View AP",
        "XR Right Knee 2 Views",
        "XR Left Knee 2 Views",
        "XR Right Shoulder 2 Views",
        "XR Left Shoulder 2 Views",
        "XR Lumbar Spine 2 or 3 Views",
        "XR Cervical Spine 2 or 3 Views",
        "XR Right Hand 3 Views",
        "XR Left Hand 3 Views",
    ],
    "CR": [
        "CR Chest 1 View AP Portable",
        "CR Chest 2 Views PA and Lateral",
        "CR Abdomen 1 View (KUB)",
        "CR Pelvis 1 View AP",
        "CR Right Knee 2 Views",
        "CR Left Knee 2 Views",
        "CR Right Shoulder 2 Views",
        "CR Left Shoulder 2 Views",
        "CR Lumbar Spine 2 or 3 Views",
        "CR Cervical Spine 2 or 3 Views",
        "CR Right Foot 3 Views",
        "CR Left Foot 3 Views",
    ],
    "US": [
        "US Abdomen Complete",
        "US Right Upper Quadrant (Gallbladder/Liver)",
        "US Renal and Bladder Retroperitoneal",
        "US Pelvic Complete (Transabdominal)",
        "US Thyroid and Soft Tissue Neck",
        "US Scrotum and Testicles with Doppler",
        "US Carotid Duplex Bilateral",
        "US Lower Extremity Venous Duplex Right",
        "US Lower Extremity Venous Duplex Left",
        "US Echocardiography Transthoracic Complete",
        "US Breast Bilateral Diagnostic",
        "US Soft Tissue Mass or Structure",
    ],
    "MG": [
        "MG Screening Mammogram Bilateral",
        "MG Diagnostic Mammogram Bilateral",
        "MG Diagnostic Mammogram Right",
        "MG Diagnostic Mammogram Left",
        "MG Digital Breast Tomosynthesis (3D) Bilateral",
        "MG Digital Breast Tomosynthesis (3D) Right",
        "MG Digital Breast Tomosynthesis (3D) Left",
        "MG Spot Compression Right Breast",
        "MG Spot Compression Left Breast",
        "MG Magnification Views Right Breast",
        "MG Magnification Views Left Breast",
        "MG Post-Biopsy Clip Placement Check",
    ],
    "NM": [
        "NM Whole Body Bone Scan",
        "NM Thyroid Uptake and Scan",
        "NM Myocardial Perfusion Rest and Stress",
        "NM Hepatobiliary Scan (HIDA)",
        "NM Renal Function Scan (MAG3)",
        "NM Gastric Emptying Study",
        "NM Parathyroid Scan SPECT",
        "NM Lung Ventilation and Perfusion (V/Q)",
        "NM Gastrointestinal Bleeding Study",
        "NM Lymphoscintigraphy Sentinel Node",
        "NM Brain SPECT Perfusion",
        "NM White Blood Cell Scan (WBC)",
    ],
    "PT": [
        "PET/CT Whole Body (Skull Base to Mid-Thigh)",
        "PET/CT Total Body (Vertex to Toes)",
        "PET/CT Brain (Metabolic / Dementia)",
        "PET/CT Myocardial Viability FDG",
        "PET/CT Melanoma Whole Body Protocol",
        "PET/CT Lymphoma Staging and Restaging",
        "PET/CT Lung Cancer Staging",
        "PET/CT Head and Neck Diagnostic",
        "PET/CT Colorectal Cancer Restaging",
        "PET/CT PSMA Prostate Cancer Scan",
        "PET/CT Dotatate Neuroendocrine Tumor Scan",
        "PET/CT Bone Marrow / Musculoskeletal Evaluation",
    ],
    "PET": [
        "PET/CT Whole Body (Skull Base to Mid-Thigh)",
        "PET/CT Total Body (Vertex to Toes)",
        "PET/CT Brain (Metabolic / Dementia)",
        "PET/CT Myocardial Viability FDG",
        "PET/CT Melanoma Whole Body Protocol",
        "PET/CT Lymphoma Staging and Restaging",
        "PET/CT Lung Cancer Staging",
        "PET/CT Head and Neck Diagnostic",
        "PET/CT Colorectal Cancer Restaging",
        "PET/CT PSMA Prostate Cancer Scan",
        "PET/CT Dotatate Neuroendocrine Tumor Scan",
        "PET/CT Bone Marrow / Musculoskeletal Evaluation",
    ],
    "XA": [
        "XA Coronary Angiography Diagnostic",
        "XA Left Heart Catheterization",
        "XA Peripheral Angiogram Lower Extremity Right",
        "XA Peripheral Angiogram Lower Extremity Left",
        "XA Cerebral Angiography 4 Vessels",
        "XA Renal Arteriography Bilateral",
        "XA Hepatic Arteriogram with Embolization",
        "XA Abdominal Aortogram with Runoff",
        "XA Pulmonary Angiography",
        "XA Upper Extremity Arteriogram Right",
        "XA Upper Extremity Arteriogram Left",
        "XA Dialysis Fistula / Graft Evaluation",
    ],
    "RF": [
        "RF Barium Swallow / Esophagram",
        "RF Upper GI Series with Small Bowel Follow-Through",
        "RF Modified Barium Swallow (Speech Pathology)",
        "RF Voiding Cystourethrogram (VCUG)",
        "RF Lumbar Puncture under Fluoroscopy",
        "RF Joint Injection Right Hip under Fluoroscopy",
        "RF Joint Injection Left Hip under Fluoroscopy",
        "RF Joint Injection Right Shoulder under Fluoroscopy",
        "RF Joint Injection Left Shoulder under Fluoroscopy",
        "RF Hysterosalpingogram (HSG)",
        "RF Small Bowel Enteroclysis",
        "RF T-Tube Cholangiogram",
    ],
    "OT": [
        "Endoscopy Upper GI Diagnostic",
        "Colonoscopy Diagnostic Complete",
        "Dermatology Lesion Digital Photography",
        "Ophthalmology Fundus Photography",
        "12-Lead Electrocardiogram Rest",
        "Secondary Capture Clinical Document",
        "Laparoscopy Diagnostic Procedure",
        "Bronchoscopy Flexible Diagnostic",
        "Colposcopy with Biopsy Imaging",
        "Intraoperative Imaging Capture",
        "Pathology Gross Specimen Photography",
        "Clinical General Examination Capture",
    ],
}

DEFAULT_STUDY_DESCRIPTIONS: list[str] = [
    "Diagnostic Imaging Examination",
    "Routine Diagnostic Study",
    "Follow-up Imaging Evaluation",
    "Pre-Operative Assessment Study",
    "Post-Operative Evaluation Study",
    "Screening Examination",
    "Consultation Imaging Study",
    "Emergency Diagnostic Evaluation",
    "Comprehensive Organ Study",
    "Baseline Imaging Survey",
    "Clinical Protocol Study",
    "Focused Area Diagnostic Scan",
]


def get_modality_study_descriptions(modality: str) -> list[str]:
    """Return the list of modality-aligned study descriptions."""
    mod = modality.upper().strip() if modality else ""
    return MODALITY_STUDY_DESCRIPTIONS.get(mod, DEFAULT_STUDY_DESCRIPTIONS)


def get_random_study_description(modality: str) -> str:
    """Return a randomly selected, modality-appropriate Study Description."""
    descriptions = get_modality_study_descriptions(modality)
    return random.choice(descriptions)


class DicomGeneratorService:
    """Service to create pydicom Datasets from Pydantic request models."""

    @staticmethod
    @functools.lru_cache(maxsize=32)
    def create_precomputed_background(rows: int, cols: int, is_8bit: bool = False) -> np.ndarray:
        """Create and cache pre-computed DICOM background matrix with W/L test patterns.

        Top half contains subtle background texture.
        Bottom half is divided into 4 gradient squares spanning the dynamic range:
          - 12-bit (0..4095): [0..1023], [1024..2047], [2048..3071], [3072..4095]
          - 8-bit (0..255): [0..63], [64..127], [128..191], [192..255]
        Each square contains vertical lines where all pixels in each column have the identical value,
        progressing from left to right.
        """
        dtype = np.uint8 if is_8bit else np.uint16
        max_val = 256 if is_8bit else 4096
        arr = np.zeros((rows, cols), dtype=dtype)

        half_rows = rows // 2

        # Top half: subtle texture
        for r in range(half_rows):
            for c in range(cols):
                arr[r, c] = (r // 2 + c // 2 + (50 if is_8bit else 500)) % (max_val // 8)

        # Bottom half: 4 gradient squares with horizontal progression
        num_squares = 4
        seg_size = max_val // num_squares

        for k in range(num_squares):
            c_start = k * cols // num_squares
            c_end = (k + 1) * cols // num_squares if k < num_squares - 1 else cols
            sq_width = c_end - c_start
            v_start = k * seg_size
            v_end = ((k + 1) * seg_size) - 1

            if sq_width > 1:
                for x in range(sq_width):
                    val = int(round(v_start + x * (v_end - v_start) / (sq_width - 1)))
                    arr[half_rows:rows, c_start + x] = val
            elif sq_width == 1:
                arr[half_rows:rows, c_start] = v_start

        return arr

    @classmethod
    def burn_metadata_text(
        cls,
        rows: int,
        cols: int,
        patient_name: str,
        patient_id: str,
        study_date: str,
        study_time: str,
        image_number: int,
        is_8bit: bool = False,
        background_val: int | None = None,
        text_val: int | None = None,
        include_slice_overlay: bool | None = None,
        base_image: np.ndarray | None = None,
    ) -> np.ndarray:
        """Burn metadata strings into image matrix from top-left.

        If base_image is provided, draws annotations directly on top of base_image.
        Otherwise, renders on top of precomputed gradient background.
        """
        if base_image is not None:
            base_arr = base_image.copy()
            orig_dtype = base_arr.dtype
            if orig_dtype == np.uint8 or is_8bit:
                img = Image.fromarray(base_arr.astype(np.uint8), mode="L")
                if text_val is None:
                    text_val = 255
            elif orig_dtype in (np.int16, np.int32, np.uint16):
                img = Image.fromarray(base_arr.astype(np.int32), mode="I")
                if text_val is None:
                    max_val = int(base_arr.max()) if base_arr.size > 0 else 0
                    text_val = max_val if max_val > 0 else (2000 if orig_dtype == np.int16 else 4095)
            else:
                img = Image.fromarray(base_arr)
                if text_val is None:
                    text_val = 255 if is_8bit else 4095
        else:
            base_arr = cls.create_precomputed_background(rows, cols, is_8bit=is_8bit).copy()
            orig_dtype = np.uint8 if is_8bit else np.uint16
            img = Image.fromarray(base_arr)
            if text_val is None:
                text_val = 255 if is_8bit else 4095

        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.load_default(size=18)
        except Exception:
            font = ImageFont.load_default()

        labels = [
            f"Patient Name: {patient_name}",
            f"Patient ID: {patient_id}",
            f"Study Date: {study_date} {study_time}",
        ]
        should_overlay = (
            include_slice_overlay if include_slice_overlay is not None else not getattr(config, "stress", False)
        )
        if should_overlay:
            labels.append(f"Image: {image_number}")

        x = 16
        y = 16
        for line in labels:
            draw.text((x, y), line, fill=text_val, font=font)
            if hasattr(font, "getbbox"):
                bbox = font.getbbox(line)
                line_height = bbox[3] - bbox[1] if bbox else 18
            else:
                line_height = 18
            y += max(line_height, 18) + 6

        return np.array(img).astype(orig_dtype)

    @classmethod
    def apply_transfer_syntax(cls, ds: FileDataset, syntax_name: str | None = None) -> FileDataset:
        """Convert or set dataset Transfer Syntax UID and encode pixel data accordingly."""
        target_uid = resolve_transfer_syntax(syntax_name or getattr(config, "transfer_syntax", "JPEG2000_LOSSLESS"))

        current_uid = getattr(ds.file_meta, "TransferSyntaxUID", None)
        if not current_uid:
            current_uid = ImplicitVRLittleEndian if getattr(ds, "is_implicit_VR", True) else ExplicitVRLittleEndian
            if hasattr(ds, "file_meta"):
                ds.file_meta.TransferSyntaxUID = current_uid

        orig_name = getattr(current_uid, "name", str(current_uid))
        target_name = getattr(target_uid, "name", str(target_uid))

        if current_uid == target_uid:
            logger.debug(
                "transfer_syntax_matched",
                original_transfer_syntax=orig_name,
                ending_transfer_syntax=target_name,
                original_transfer_syntax_uid=str(current_uid),
                ending_transfer_syntax_uid=str(target_uid),
            )
            return ds

        modality = str(getattr(ds, "Modality", ""))
        instance_number = getattr(ds, "InstanceNumber", None)
        logger.info(
            "transfer_syntax_conversion",
            original_transfer_syntax=orig_name,
            ending_transfer_syntax=target_name,
            original_transfer_syntax_uid=str(current_uid),
            ending_transfer_syntax_uid=str(target_uid),
            modality=modality,
            instance_number=instance_number,
        )

        if current_uid not in (ExplicitVRLittleEndian, ImplicitVRLittleEndian, None):
            try:
                ds.decompress()
            except Exception as exc:
                logger.warning("decompress_failed_before_syntax_conversion", error=str(exc))

        if target_uid in (ExplicitVRLittleEndian, ImplicitVRLittleEndian):
            ds.file_meta.TransferSyntaxUID = target_uid
            ds.LossyImageCompression = "00"
            if not isinstance(getattr(ds, "PixelData", None), (bytes, bytearray)):
                try:
                    arr = ds.pixel_array
                    if getattr(ds, "BitsAllocated", 16) == 8:
                        ds.PixelData = arr.astype(np.uint8).tobytes()
                    elif getattr(ds, "PixelRepresentation", 0) == 1:
                        ds.PixelData = arr.astype(np.int16).tobytes()
                    else:
                        ds.PixelData = arr.astype(np.uint16).tobytes()
                except Exception:
                    pass
        elif target_uid == JPEGBaseline8Bit:
            # JPEG Process 1 is 8-bit baseline
            try:
                arr = ds.pixel_array
            except Exception:
                if isinstance(ds.PixelData, bytes):
                    if getattr(ds, "BitsAllocated", 16) == 8:
                        arr = np.frombuffer(ds.PixelData, dtype=np.uint8)
                    else:
                        arr = np.frombuffer(ds.PixelData, dtype=np.uint16)
                else:
                    arr = np.array(ds.PixelData)

            if arr.ndim == 1 and hasattr(ds, "Rows") and hasattr(ds, "Columns"):
                arr = arr.reshape((ds.Rows, ds.Columns))

            if arr.dtype == np.uint8 or arr.max() <= 255:
                arr8 = arr.astype(np.uint8)
            else:
                arr8 = (arr >> 4).astype(np.uint8)

            img = Image.fromarray(arr8, mode="L")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=95)
            jpeg_bytes = buf.getvalue()

            ds.file_meta.TransferSyntaxUID = JPEGBaseline8Bit
            ds.PhotometricInterpretation = "MONOCHROME2"
            ds.SamplesPerPixel = 1
            ds.PixelRepresentation = 0
            ds.BitsAllocated = 8
            ds.BitsStored = 8
            ds.HighBit = 7
            ds.WindowCenter = 128
            ds.WindowWidth = 256
            ds.RescaleIntercept = "0"
            ds.RescaleSlope = "1"
            ds.add_new(0x00280106, "US", 0)
            ds.add_new(0x00280107, "US", 255)
            if (0x0028, 0x0120) in ds:
                del ds[0x0028, 0x0120]
            if (0x0028, 0x0006) in ds:
                del ds[0x0028, 0x0006]
            ds.LossyImageCompression = "01"
            ds.LossyImageCompressionMethod = "ISO_10918_1"
            ds.PixelData = encapsulate([jpeg_bytes])

        elif target_uid in (JPEG2000Lossless, JPEG2000, RLELossless):
            try:
                ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                if target_uid == JPEG2000Lossless:
                    ds.compress(JPEG2000Lossless, generate_instance_uid=False)
                    ds.LossyImageCompression = "00"
                elif target_uid == JPEG2000:
                    ds.compress(JPEG2000, j2k_cr=[10], generate_instance_uid=False)
                    ds.LossyImageCompression = "01"
                    ds.LossyImageCompressionMethod = "ISO_15444_1"
                elif target_uid == RLELossless:
                    ds.compress(RLELossless, generate_instance_uid=False)
                    ds.LossyImageCompression = "00"
            except Exception as exc:
                logger.warning(
                    "compression_failed_falling_back_to_raw",
                    target_uid=str(target_uid),
                    error=str(exc),
                )
                ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        else:
            ds.file_meta.TransferSyntaxUID = target_uid

        # Synchronize internal encoding flags with TransferSyntaxUID for pynetdicom compatibility
        is_implicit = target_uid == ImplicitVRLittleEndian
        ds._read_implicit = is_implicit
        ds._read_little = True
        return ds

    @classmethod
    def create_dicom_file(
        cls,
        request: MockDicomRequest,
        instance_number: int = 1,
        stress: bool | None = None,
        include_slice_overlay: bool | None = None,
    ) -> FileDataset:
        """Create a single pydicom FileDataset populated with metadata and pixel data."""
        patient_id = request.patient.patient_id
        patient_name = request.patient.patient_name
        accession = request.study.accession_number or ""
        study_uid = request.study.study_instance_uid or generate_study_uid(patient_name, patient_id, accession)
        series_uid = request.series.series_instance_uid or generate_series_uid(study_uid, request.series.series_number)
        sop_instance_uid = generate_sop_instance_uid(series_uid, instance_number)

        # File Meta Information
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = CTImageStorage
        file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

        # Dataset initialization
        ds = FileDataset(
            "mock.dcm",
            {},
            file_meta=file_meta,
            preamble=b"\x00" * 128,
        )
        ds._read_implicit = False
        ds._read_little = True

        # Patient Module
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
        ds.StudyDescription = request.study.study_description or get_random_study_description(request.series.modality)
        ds.InstitutionName = request.study.institution_name or getattr(config, "institution_name", "GO SMART CLINIC")

        if request.study.referring_physician_name:
            ds.ReferringPhysicianName = request.study.referring_physician_name
        if request.study.reading_physician_name:
            ds.NameOfPhysiciansReadingStudy = request.study.reading_physician_name

        # General Series Module
        ds.SeriesInstanceUID = series_uid
        ds.Modality = request.series.modality
        ds.SeriesNumber = request.series.series_number
        ds.SeriesDescription = request.series.series_description or f"{request.series.modality} Series"
        ds.NumberOfSeriesRelatedInstances = request.num_instances

        perf_name = request.series.performing_physician_name or request.study.performing_physician_name
        if perf_name:
            ds.PerformingPhysicianName = perf_name

        # General Study Module
        ds.NumberOfStudyRelatedSeries = 1
        ds.NumberOfStudyRelatedInstances = request.num_instances

        # SOP Common Module
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = sop_instance_uid
        ds.InstanceNumber = instance_number
        ds.Modality = request.series.modality

        # Check target transfer syntax for JPEG 8-bit mode
        syntax_to_apply = request.transfer_syntax or getattr(config, "transfer_syntax", "JPEG2000_LOSSLESS")
        target_uid = resolve_transfer_syntax(syntax_to_apply)
        is_jpeg_8bit = target_uid == JPEGBaseline8Bit

        # Image Pixel Module
        rows = request.rows
        cols = request.columns
        ds.Rows = rows
        ds.Columns = cols
        ds.PixelRepresentation = 0
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.RescaleIntercept = "0"
        ds.RescaleSlope = "1"

        if is_jpeg_8bit:
            ds.BitsAllocated = 8
            ds.BitsStored = 8
            ds.HighBit = 7
            ds.WindowCenter = 128
            ds.WindowWidth = 256
            ds.SmallestImagePixelValue = 0
            ds.LargestImagePixelValue = 255
        else:
            ds.BitsAllocated = 16
            ds.BitsStored = 12
            ds.HighBit = 11
            ds.WindowCenter = 2048
            ds.WindowWidth = 4096
            ds.SmallestImagePixelValue = 0
            ds.LargestImagePixelValue = 4095

        is_stress = (
            stress
            if stress is not None
            else (request.stress if request.stress is not None else getattr(config, "stress", False))
        )
        slice_overlay = (
            include_slice_overlay
            if include_slice_overlay is not None
            else (request.include_slice_overlay if request.include_slice_overlay is not None else not is_stress)
        )

        is_synthetic = getattr(config, "synthetic_mode", False)
        should_burn = request.burn_in_text if request.burn_in_text is not None else is_synthetic

        if should_burn:
            pixel_matrix = cls.burn_metadata_text(
                rows=rows,
                cols=cols,
                patient_name=patient_name,
                patient_id=patient_id,
                study_date=study_date,
                study_time=study_time,
                image_number=instance_number,
                is_8bit=is_jpeg_8bit,
                include_slice_overlay=slice_overlay,
            )
        else:
            pixel_matrix = cls.create_precomputed_background(rows, cols, is_8bit=is_jpeg_8bit).copy()

        ds.PixelData = pixel_matrix.tobytes()

        # Swap transfer syntax if specified or configured
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
            stress=raw_req.stress,
            include_slice_overlay=raw_req.include_slice_overlay,
        )
        return cls.create_dicom_file(
            mock_req,
            instance_number=raw_req.image_number,
            stress=raw_req.stress,
            include_slice_overlay=raw_req.include_slice_overlay,
        )

    @classmethod
    def create_dicom_from_template(
        cls,
        template: FileDataset | str | Path,
        transfer_syntax: str | None = None,
        patient_name: str | None = None,
        patient_id: str | None = None,
        study_date: str | None = None,
        study_time: str | None = None,
        image_number: int = 1,
        burn_in_text: bool | None = None,
        rows: int = 512,
        cols: int = 512,
        institution_name: str | None = None,
        referring_physician_name: str | None = None,
        performing_physician_name: str | None = None,
        reading_physician_name: str | None = None,
        study_description: str | None = None,
        accession_number: str | None = None,
        modality: str | None = None,
        stress: bool | None = None,
        include_slice_overlay: bool | None = None,
        preserve_pixel_data: bool = False,
    ) -> FileDataset:
        """Create a synthetic DICOM dataset based on a base template DICOM file/dataset.

        Swaps pixel data with precomputed background and burned metadata strings,
        resolves tag VR ambiguities for explicit transfer syntax compliance,
        and encodes with the requested transfer syntax.
        """
        import pydicom
        from pydicom.dataset import FileMetaDataset
        from pydicom.uid import ExplicitVRLittleEndian, ImplicitVRLittleEndian

        if isinstance(template, (str, Path)):
            ds = pydicom.dcmread(template, force=True)
        else:
            ds = copy.deepcopy(template)

        if not hasattr(ds, "file_meta") or not getattr(ds.file_meta, "TransferSyntaxUID", None):
            if not hasattr(ds, "file_meta"):
                ds.file_meta = FileMetaDataset()
            ds.file_meta.TransferSyntaxUID = (
                ImplicitVRLittleEndian if getattr(ds, "is_implicit_VR", True) else ExplicitVRLittleEndian
            )

        syntax_name = transfer_syntax or getattr(config, "transfer_syntax", "JPEG2000_LOSSLESS")
        target_uid = resolve_transfer_syntax(syntax_name)
        is_8bit = target_uid == JPEGBaseline8Bit

        p_name = patient_name or (str(ds.PatientName) if hasattr(ds, "PatientName") else "MOCK_PATIENT")
        p_id = patient_id or (str(ds.PatientID) if hasattr(ds, "PatientID") else "MOCK_ID")
        s_date = study_date or (str(ds.StudyDate) if hasattr(ds, "StudyDate") else time.strftime("%Y%m%d"))
        s_time = study_time or (str(ds.StudyTime) if hasattr(ds, "StudyTime") else time.strftime("%H%M%S"))

        ds.PatientName = p_name
        ds.PatientID = p_id
        ds.StudyDate = s_date
        ds.StudyTime = s_time

        if institution_name:
            ds.InstitutionName = institution_name
        if referring_physician_name:
            ds.ReferringPhysicianName = referring_physician_name
        if performing_physician_name:
            ds.PerformingPhysicianName = performing_physician_name
        if reading_physician_name:
            ds.NameOfPhysiciansReadingStudy = reading_physician_name
        if study_description:
            ds.StudyDescription = study_description
        if accession_number:
            ds.AccessionNumber = accession_number
        if modality:
            ds.Modality = modality

        is_synthetic = getattr(config, "synthetic_mode", False)
        should_burn = is_synthetic if burn_in_text is None else burn_in_text

        if preserve_pixel_data and hasattr(ds, "PixelData") and ds.PixelData:
            if not should_burn:
                if getattr(ds.file_meta, "TransferSyntaxUID", None) == target_uid:
                    # Direct passthrough: pixels and transfer syntax already match
                    return ds
                # Transfer syntax differs: convert directly on ds without unpacking/repacking pixel array
                return cls.apply_transfer_syntax(ds, syntax_name)

            orig_pixel_array = ds.pixel_array
            rows = orig_pixel_array.shape[0]
            cols = orig_pixel_array.shape[1]
            ds.Rows = rows
            ds.Columns = cols
            pixel_matrix = cls.burn_metadata_text(
                rows=rows,
                cols=cols,
                patient_name=p_name,
                patient_id=p_id,
                study_date=s_date,
                study_time=s_time,
                image_number=image_number,
                is_8bit=(orig_pixel_array.dtype == np.uint8),
                base_image=orig_pixel_array,
                include_slice_overlay=include_slice_overlay,
            )
        else:
            ds.Rows = rows
            ds.Columns = cols
            if should_burn:
                pixel_matrix = cls.burn_metadata_text(
                    rows=rows,
                    cols=cols,
                    patient_name=p_name,
                    patient_id=p_id,
                    study_date=s_date,
                    study_time=s_time,
                    image_number=image_number,
                    is_8bit=is_8bit,
                    include_slice_overlay=include_slice_overlay,
                )
            else:
                pixel_matrix = cls.create_precomputed_background(rows, cols, is_8bit=is_8bit).copy()

            ds.PixelRepresentation = 0
            ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            ds.RescaleIntercept = "0"
            ds.RescaleSlope = "1"

            if is_8bit:
                ds.BitsAllocated = 8
                ds.BitsStored = 8
                ds.HighBit = 7
                ds.WindowCenter = 128
                ds.WindowWidth = 256
                ds.add_new(0x00280106, "US", 0)
                ds.add_new(0x00280107, "US", 255)
            else:
                ds.BitsAllocated = 16
                ds.BitsStored = 12
                ds.HighBit = 11
                ds.WindowCenter = 2048
                ds.WindowWidth = 4096
                ds.add_new(0x00280106, "US", 0)
                ds.add_new(0x00280107, "US", 4095)

            if (0x0028, 0x0120) in ds:
                del ds[0x0028, 0x0120]

        ds.PixelData = pixel_matrix.tobytes()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        ds = cls.apply_transfer_syntax(ds, syntax_name)
        return ds

    @classmethod
    def create_instances_from_mwl(
        cls,
        mwl_record: dict[str, Any],
        num_instances: int | None = None,
        transfer_syntax: str | None = None,
        stress: bool | None = None,
    ) -> list[FileDataset]:
        """Synthesize DICOM image FileDatasets on the fly matching an MWL record."""
        import random

        target_syntax = (
            transfer_syntax
            or mwl_record.get("transfer_syntax")
            or getattr(config, "transfer_syntax", "JPEG2000_LOSSLESS")
        )
        is_stress = (
            stress
            if stress is not None
            else (
                mwl_record.get("stress") if mwl_record.get("stress") is not None else getattr(config, "stress", False)
            )
        )
        slice_overlay = not is_stress
        is_synthetic = getattr(config, "synthetic_mode", False)
        burn_in = mwl_record.get("burn_in_text") if mwl_record.get("burn_in_text") is not None else is_synthetic

        template_series = mwl_record.get("template_series")
        template_ds = mwl_record.get("template_dataset")

        if num_instances is None:
            num_instances = mwl_record.get("num_instances")
        if num_instances is None:
            if not getattr(config, "synthetic_mode", False) and template_series:
                num_instances = template_series.slice_count
            else:
                num_instances = random.randint(getattr(config, "min_slices", 8), getattr(config, "max_slices", 24))
        json_e = mwl_record.get("json_entry", {})
        patient_id = mwl_record.get("patient_id") or f"{getattr(config, 'id_prefix', 'GSH-')}MOCK_PATIENT_ID"
        patient_name = mwl_record.get("patient_name") or f"MOCK{getattr(config, 'patient_suffix', '_GSH')}^PATIENT"
        accession = mwl_record.get("accession") or f"{getattr(config, 'id_prefix', 'GSH-')}ACC-001"
        study_uid = mwl_record.get("study_uid") or generate_study_uid(patient_name, patient_id, accession)
        modality = mwl_record.get("modality", "CT")

        sps_seq = json_e.get("00400100", {}).get("Value", [{}])[0]
        study_date = sps_seq.get("00400002", {}).get("Value", [time.strftime("%Y%m%d")])[0]
        study_time = sps_seq.get("00400003", {}).get("Value", [time.strftime("%H%M%S")])[0]
        if not is_synthetic:
            if mwl_record.get("study_description") is not None:
                study_desc = mwl_record["study_description"]
            elif template_series and template_series.study_description is not None:
                study_desc = template_series.study_description
            elif template_ds and hasattr(template_ds, "StudyDescription") and template_ds.StudyDescription:
                study_desc = str(template_ds.StudyDescription).strip() or None
            elif "00081030" in json_e and json_e["00081030"].get("Value"):
                val = json_e["00081030"]["Value"][0]
                study_desc = val if val else None
            else:
                study_desc = None
        else:
            study_desc = (
                mwl_record.get("study_description")
                or json_e.get("00081030", {}).get("Value", [None])[0]
                or get_random_study_description(modality)
            )
        patient_sex = json_e.get("00100040", {}).get("Value", ["U"])[0]
        patient_dob = json_e.get("00100030", {}).get("Value", [""])[0]

        # Extract physician and institution metadata
        ref_phys = mwl_record.get("referring_physician")
        if not ref_phys and "00080090" in json_e and json_e["00080090"].get("Value"):
            ref_raw = json_e["00080090"]["Value"][0]
            ref_phys = ref_raw.get("Alphabetic", "") if isinstance(ref_raw, dict) else ref_raw

        perf_phys = mwl_record.get("performing_physician")
        if not perf_phys and "00081050" in json_e and json_e["00081050"].get("Value"):
            perf_raw = json_e["00081050"]["Value"][0]
            perf_phys = perf_raw.get("Alphabetic", "") if isinstance(perf_raw, dict) else perf_raw
        if not perf_phys and "00400100" in json_e:
            sps_raw_perf = sps_seq.get("00400006", {}).get("Value", [""])[0]
            perf_phys = sps_raw_perf.get("Alphabetic", "") if isinstance(sps_raw_perf, dict) else sps_raw_perf

        read_phys = mwl_record.get("reading_physician")
        if not read_phys and "00081060" in json_e and json_e["00081060"].get("Value"):
            read_raw = json_e["00081060"]["Value"][0]
            read_phys = read_raw.get("Alphabetic", "") if isinstance(read_raw, dict) else read_raw

        inst_name = (
            mwl_record.get("institution_name")
            or json_e.get("00080080", {}).get("Value", [getattr(config, "institution_name", "GO SMART CLINIC")])[0]
        )

        mwl_ds = mwl_record.get("dataset")
        if mwl_ds:
            if not ref_phys and hasattr(mwl_ds, "ReferringPhysicianName"):
                ref_phys = str(mwl_ds.ReferringPhysicianName)
            if not perf_phys and hasattr(mwl_ds, "PerformingPhysicianName"):
                perf_phys = str(mwl_ds.PerformingPhysicianName)
            if not read_phys and hasattr(mwl_ds, "NameOfPhysiciansReadingStudy"):
                read_phys = str(mwl_ds.NameOfPhysiciansReadingStudy)
            if not inst_name and hasattr(mwl_ds, "InstitutionName"):
                inst_name = str(mwl_ds.InstitutionName)

        series_number = int(mwl_record.get("series_number") or 1)
        series_uid = mwl_record.get("series_uid") or generate_series_uid(study_uid, series_number)
        series_desc = mwl_record.get("series_description") or f"{modality} Series"

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
                "institution_name": inst_name,
                "referring_physician_name": ref_phys,
                "reading_physician_name": read_phys,
                "performing_physician_name": perf_phys,
            },
            series={
                "series_instance_uid": series_uid,
                "modality": modality,
                "series_number": series_number,
                "series_description": series_desc,
                "performing_physician_name": perf_phys,
            },
            num_instances=num_instances,
            transfer_syntax=target_syntax,
            burn_in_text=burn_in,
            stress=is_stress,
            include_slice_overlay=slice_overlay,
        )

        slices = []
        if template_series and template_series.slices:
            slices = template_series.slices
        elif template_ds:
            slices = [template_ds]
        else:
            templates_dir = Path(getattr(config, "templates_path", "./templates"))
            if templates_dir.exists() and templates_dir.is_dir():
                for p in sorted(templates_dir.rglob("*")):
                    if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in (".dcm", ".dicom"):
                        try:
                            import pydicom

                            temp_read = pydicom.dcmread(p, force=True)
                            temp_mod = str(getattr(temp_read, "Modality", "")).strip().upper()
                            if temp_mod == modality and hasattr(temp_read, "PixelData") and temp_read.PixelData:
                                slices.append(temp_read)
                                break
                        except Exception:
                            pass

        rows = int(mwl_record.get("rows") or (slices[0].Rows if slices and hasattr(slices[0], "Rows") else 512))
        cols = int(
            mwl_record.get("columns")
            or mwl_record.get("cols")
            or (slices[0].Columns if slices and hasattr(slices[0], "Columns") else 512)
        )

        if slices:
            if not is_synthetic and study_desc is None:
                for s in slices:
                    val = getattr(s, "StudyDescription", None)
                    if val is not None and str(val).strip():
                        study_desc = str(val).strip()
                        break
            m_count = len(slices)
            datasets = []
            template_ts = getattr(getattr(slices[0], "file_meta", None), "TransferSyntaxUID", None)
            if not template_ts:
                template_ts = (
                    ImplicitVRLittleEndian if getattr(slices[0], "is_implicit_VR", True) else ExplicitVRLittleEndian
                )
            target_ts = resolve_transfer_syntax(target_syntax)
            orig_ts_name = getattr(template_ts, "name", str(template_ts))
            target_ts_name = getattr(target_ts, "name", str(target_ts))
            t_start_series = time.perf_counter()

            logger.info(
                "generating_template_series_instances",
                modality=modality,
                slice_count=num_instances,
                original_transfer_syntax=orig_ts_name,
                ending_transfer_syntax=target_ts_name,
                original_transfer_syntax_uid=str(template_ts),
                ending_transfer_syntax_uid=str(target_ts),
                requires_conversion=(template_ts != target_ts),
            )
            if is_stress and num_instances > 1:
                first_slice = slices[0]
                ds1 = cls.create_dicom_from_template(
                    template=first_slice,
                    transfer_syntax=target_syntax,
                    patient_name=patient_name,
                    patient_id=patient_id,
                    study_date=study_date,
                    study_time=study_time,
                    image_number=1,
                    burn_in_text=burn_in,
                    rows=int(getattr(first_slice, "Rows", rows)),
                    cols=int(getattr(first_slice, "Columns", cols)),
                    institution_name=inst_name,
                    referring_physician_name=ref_phys,
                    performing_physician_name=perf_phys,
                    reading_physician_name=read_phys,
                    study_description=study_desc,
                    accession_number=accession,
                    modality=modality,
                    stress=True,
                    include_slice_overlay=False,
                    preserve_pixel_data=True,
                )
                ds1.PatientID = patient_id
                ds1.PatientName = patient_name
                if patient_dob:
                    ds1.PatientBirthDate = patient_dob
                if patient_sex:
                    ds1.PatientSex = patient_sex
                ds1.StudyInstanceUID = study_uid
                ds1.StudyDate = study_date
                ds1.StudyTime = study_time
                ds1.AccessionNumber = accession
                if study_desc is not None:
                    ds1.StudyDescription = study_desc
                elif not is_synthetic:
                    if hasattr(first_slice, "StudyDescription") and first_slice.StudyDescription:
                        ds1.StudyDescription = str(first_slice.StudyDescription)
                    elif hasattr(ds1, "StudyDescription"):
                        del ds1.StudyDescription
                if inst_name:
                    ds1.InstitutionName = inst_name
                if ref_phys:
                    ds1.ReferringPhysicianName = ref_phys
                if read_phys:
                    ds1.NameOfPhysiciansReadingStudy = read_phys
                ds1.SeriesInstanceUID = series_uid
                ds1.Modality = modality
                ds1.SeriesNumber = series_number
                ds1.SeriesDescription = series_desc
                if perf_phys:
                    ds1.PerformingPhysicianName = perf_phys
                sop_inst_uid = generate_sop_instance_uid(series_uid, 1)
                ds1.SOPInstanceUID = sop_inst_uid
                if getattr(ds1, "file_meta", None):
                    ds1.file_meta.MediaStorageSOPInstanceUID = sop_inst_uid
                ds1.InstanceNumber = 1
                ds1.NumberOfSeriesRelatedInstances = num_instances
                ds1.NumberOfStudyRelatedSeries = 1
                ds1.NumberOfStudyRelatedInstances = num_instances
                datasets.append(ds1)

                for i in range(2, num_instances + 1):
                    ds = copy.deepcopy(ds1)
                    sop_inst_uid = generate_sop_instance_uid(series_uid, i)
                    ds.SOPInstanceUID = sop_inst_uid
                    if getattr(ds, "file_meta", None):
                        ds.file_meta.MediaStorageSOPInstanceUID = sop_inst_uid
                    ds.InstanceNumber = i
                    datasets.append(ds)
                logger.info(
                    "generated_template_series_instances",
                    modality=modality,
                    instances_count=len(datasets),
                    original_transfer_syntax=orig_ts_name,
                    ending_transfer_syntax=target_ts_name,
                    original_transfer_syntax_uid=str(template_ts),
                    ending_transfer_syntax_uid=str(target_ts),
                    duration_seconds=round(time.perf_counter() - t_start_series, 2),
                )
                return datasets

            for i in range(1, num_instances + 1):
                slice_ds = slices[(i - 1) % m_count]
                ds = cls.create_dicom_from_template(
                    template=slice_ds,
                    transfer_syntax=target_syntax,
                    patient_name=patient_name,
                    patient_id=patient_id,
                    study_date=study_date,
                    study_time=study_time,
                    image_number=i,
                    burn_in_text=burn_in,
                    rows=int(getattr(slice_ds, "Rows", rows)),
                    cols=int(getattr(slice_ds, "Columns", cols)),
                    institution_name=inst_name,
                    referring_physician_name=ref_phys,
                    performing_physician_name=perf_phys,
                    reading_physician_name=read_phys,
                    study_description=study_desc,
                    accession_number=accession,
                    modality=modality,
                    stress=is_stress,
                    include_slice_overlay=slice_overlay,
                    preserve_pixel_data=True,
                )
                ds.PatientID = patient_id
                ds.PatientName = patient_name
                if patient_dob:
                    ds.PatientBirthDate = patient_dob
                if patient_sex:
                    ds.PatientSex = patient_sex

                ds.StudyInstanceUID = study_uid
                ds.StudyDate = study_date
                ds.StudyTime = study_time
                ds.AccessionNumber = accession
                if study_desc is not None:
                    ds.StudyDescription = study_desc
                elif not is_synthetic:
                    if hasattr(slice_ds, "StudyDescription") and slice_ds.StudyDescription:
                        ds.StudyDescription = str(slice_ds.StudyDescription)
                    elif hasattr(ds, "StudyDescription"):
                        del ds.StudyDescription
                if inst_name:
                    ds.InstitutionName = inst_name
                if ref_phys:
                    ds.ReferringPhysicianName = ref_phys
                if read_phys:
                    ds.NameOfPhysiciansReadingStudy = read_phys

                ds.SeriesInstanceUID = series_uid
                ds.Modality = modality
                ds.SeriesNumber = series_number
                ds.SeriesDescription = series_desc
                if perf_phys:
                    ds.PerformingPhysicianName = perf_phys

                sop_inst_uid = generate_sop_instance_uid(series_uid, i)
                ds.SOPInstanceUID = sop_inst_uid
                if getattr(ds, "file_meta", None):
                    ds.file_meta.MediaStorageSOPInstanceUID = sop_inst_uid
                ds.InstanceNumber = i

                ds.NumberOfSeriesRelatedInstances = num_instances
                ds.NumberOfStudyRelatedSeries = 1
                ds.NumberOfStudyRelatedInstances = num_instances
                datasets.append(ds)
            logger.info(
                "generated_template_series_instances",
                modality=modality,
                instances_count=len(datasets),
                original_transfer_syntax=orig_ts_name,
                ending_transfer_syntax=target_ts_name,
                original_transfer_syntax_uid=str(template_ts),
                ending_transfer_syntax_uid=str(target_ts),
                duration_seconds=round(time.perf_counter() - t_start_series, 2),
            )
            return datasets

        datasets = []
        if is_stress and num_instances > 1:
            ds1 = cls.create_dicom_file(
                mock_req,
                instance_number=1,
                stress=True,
                include_slice_overlay=False,
            )
            datasets.append(ds1)
            for i in range(2, num_instances + 1):
                ds = copy.deepcopy(ds1)
                sop_inst_uid = generate_sop_instance_uid(series_uid, i)
                ds.SOPInstanceUID = sop_inst_uid
                if getattr(ds, "file_meta", None):
                    ds.file_meta.MediaStorageSOPInstanceUID = sop_inst_uid
                ds.InstanceNumber = i
                datasets.append(ds)
            return datasets

        for i in range(1, num_instances + 1):
            ds = cls.create_dicom_file(
                mock_req,
                instance_number=i,
                stress=is_stress,
                include_slice_overlay=slice_overlay,
            )
            datasets.append(ds)
        return datasets

    def generate_and_save(
        self,
        request: MockDicomRequest,
        target_dir: str,
        stress: bool | None = None,
    ) -> MockDicomResponse:
        """Generate a batch of DICOM files and save them to target_dir."""
        out_path = Path(target_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        is_stress = (
            stress
            if stress is not None
            else (request.stress if request.stress is not None else getattr(config, "stress", False))
        )
        slice_overlay = not is_stress if request.include_slice_overlay is None else request.include_slice_overlay

        patient_id = request.patient.patient_id
        patient_name = request.patient.patient_name
        accession = request.study.accession_number or ""
        study_uid = request.study.study_instance_uid or generate_study_uid(patient_name, patient_id, accession)
        series_uid = request.series.series_instance_uid or generate_series_uid(study_uid, request.series.series_number)

        # Update request object with UIDs if generated
        request.study.study_instance_uid = study_uid
        request.series.series_instance_uid = series_uid

        saved_files: list[str] = []

        if is_stress and request.num_instances > 1:
            ds1 = self.create_dicom_file(
                request,
                instance_number=1,
                stress=True,
                include_slice_overlay=slice_overlay,
            )
            fn1 = out_path / f"instance_{1:04d}_{ds1.SOPInstanceUID}.dcm"
            ds1.save_as(fn1, enforce_file_format=True)
            saved_files.append(str(fn1.resolve()))

            for i in range(2, request.num_instances + 1):
                ds = copy.deepcopy(ds1)
                sop_uid = generate_sop_instance_uid(series_uid, i)
                ds.SOPInstanceUID = sop_uid
                if getattr(ds, "file_meta", None):
                    ds.file_meta.MediaStorageSOPInstanceUID = sop_uid
                ds.InstanceNumber = i
                fn = out_path / f"instance_{i:04d}_{sop_uid}.dcm"
                ds.save_as(fn, enforce_file_format=True)
                saved_files.append(str(fn.resolve()))
        else:
            for i in range(1, request.num_instances + 1):
                ds = self.create_dicom_file(
                    request,
                    instance_number=i,
                    stress=is_stress,
                    include_slice_overlay=slice_overlay,
                )
                filename = out_path / f"instance_{i:04d}_{ds.SOPInstanceUID}.dcm"
                ds.save_as(filename, enforce_file_format=True)
                saved_files.append(str(filename.resolve()))

        logger.info(
            "dicom_generation_completed",
            patient_id=request.patient.patient_id,
            study_uid=study_uid,
            series_uid=series_uid,
            num_instances=len(saved_files),
            transfer_syntax=request.transfer_syntax or getattr(config, "transfer_syntax", "JPEG2000_LOSSLESS"),
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
