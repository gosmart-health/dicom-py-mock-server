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
    ) -> np.ndarray:
        """Burn metadata strings into image matrix from top-left on top of precomputed background."""
        base_arr = cls.create_precomputed_background(rows, cols, is_8bit=is_8bit).copy()

        img = Image.fromarray(base_arr)
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.load_default(size=18)
        except Exception:
            font = ImageFont.load_default()

        labels = [
            f"Patient Name: {patient_name}",
            f"Patient ID: {patient_id}",
            f"Study Date: {study_date} {study_time}",
            f"Image: {image_number}",
        ]

        if text_val is None:
            text_val = 255 if is_8bit else 4095

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

        return np.array(img, dtype=np.uint8 if is_8bit else np.uint16)

    @classmethod
    def apply_transfer_syntax(cls, ds: FileDataset, syntax_name: str | None = None) -> FileDataset:
        """Convert or set dataset Transfer Syntax UID and encode pixel data accordingly."""
        target_name = (syntax_name or getattr(config, "transfer_syntax", "JPEG2000_LOSSLESS")).upper().strip()
        target_uid = TRANSFER_SYNTAX_MAP.get(target_name, ExplicitVRLittleEndian)

        current_uid = getattr(ds.file_meta, "TransferSyntaxUID", None)
        if current_uid == target_uid:
            return ds

        if current_uid not in (ExplicitVRLittleEndian, ImplicitVRLittleEndian, None):
            try:
                ds.decompress()
            except Exception as exc:
                logger.warning("decompress_failed_before_syntax_conversion", error=str(exc))

        if target_uid in (ExplicitVRLittleEndian, ImplicitVRLittleEndian):
            ds.file_meta.TransferSyntaxUID = target_uid
            ds.LossyImageCompression = "00"
            arr = ds.pixel_array if hasattr(ds, "pixel_array") else np.frombuffer(ds.PixelData, dtype=np.uint16)
            ds.PixelData = arr.astype(np.uint16).tobytes()
        elif target_uid == JPEGBaseline8Bit:
            # JPEG Process 1 is 8-bit baseline
            arr = ds.pixel_array if hasattr(ds, "pixel_array") else np.frombuffer(ds.PixelData, dtype=np.uint16)
            if arr.dtype == np.uint8 or arr.max() <= 255:
                arr8 = arr.astype(np.uint8)
            else:
                arr8 = (arr >> 4).astype(np.uint8)

            img = Image.fromarray(arr8)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=95)
            jpeg_bytes = buf.getvalue()

            ds.file_meta.TransferSyntaxUID = JPEGBaseline8Bit
            ds.BitsAllocated = 8
            ds.BitsStored = 8
            ds.HighBit = 7
            ds.WindowCenter = 128
            ds.WindowWidth = 256
            ds.SmallestImagePixelValue = 0
            ds.LargestImagePixelValue = 255
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

        # Synchronize dataset VR and endianness encoding flags with the final TransferSyntaxUID
        is_implicit = ds.file_meta.TransferSyntaxUID == ImplicitVRLittleEndian
        ds.is_implicit_VR = is_implicit
        ds.is_little_endian = True
        ds._read_implicit = is_implicit
        ds._read_little = True
        return ds

    @classmethod
    def create_dicom_file(cls, request: MockDicomRequest, instance_number: int = 1) -> FileDataset:
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
            is_implicit_VR=False,
            is_little_endian=True,
        )

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
        target_name = syntax_to_apply.upper().strip()
        target_uid = TRANSFER_SYNTAX_MAP.get(target_name, ExplicitVRLittleEndian)
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

        if request.burn_in_text:
            pixel_matrix = cls.burn_metadata_text(
                rows=rows,
                cols=cols,
                patient_name=patient_name,
                patient_id=patient_id,
                study_date=study_date,
                study_time=study_time,
                image_number=instance_number,
                is_8bit=is_jpeg_8bit,
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
        )
        return cls.create_dicom_file(mock_req, instance_number=raw_req.image_number)

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
        burn_in_text: bool = True,
        rows: int = 512,
        cols: int = 512,
        institution_name: str | None = None,
        referring_physician_name: str | None = None,
        performing_physician_name: str | None = None,
        reading_physician_name: str | None = None,
        study_description: str | None = None,
        accession_number: str | None = None,
        modality: str | None = None,
    ) -> FileDataset:
        """Create a synthetic DICOM dataset based on a base template DICOM file/dataset.

        Swaps pixel data with precomputed background and burned metadata strings,
        resolves tag VR ambiguities for explicit transfer syntax compliance,
        and encodes with the requested transfer syntax.
        """
        import pydicom

        if isinstance(template, (str, Path)):
            ds = pydicom.dcmread(template)
        else:
            ds = copy.deepcopy(template)

        syntax_name = (transfer_syntax or getattr(config, "transfer_syntax", "JPEG2000_LOSSLESS")).upper().strip()
        target_uid = TRANSFER_SYNTAX_MAP.get(syntax_name, ExplicitVRLittleEndian)
        is_8bit = target_uid == JPEGBaseline8Bit

        p_name = patient_name or (str(ds.PatientName) if hasattr(ds, "PatientName") else "MOCK_PATIENT")
        p_id = patient_id or (str(ds.PatientID) if hasattr(ds, "PatientID") else "MOCK_ID")
        s_date = study_date or (str(ds.StudyDate) if hasattr(ds, "StudyDate") else time.strftime("%Y%m%d"))
        s_time = study_time or (str(ds.StudyTime) if hasattr(ds, "StudyTime") else time.strftime("%H%M%S"))

        ds.PatientName = p_name
        ds.PatientID = p_id
        ds.StudyDate = s_date
        ds.StudyTime = s_time
        ds.Rows = rows
        ds.Columns = cols
        ds.InstitutionName = institution_name or getattr(config, "institution_name", "GO SMART CLINIC")
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

        if burn_in_text:
            pixel_matrix = cls.burn_metadata_text(
                rows=rows,
                cols=cols,
                patient_name=p_name,
                patient_id=p_id,
                study_date=s_date,
                study_time=s_time,
                image_number=image_number,
                is_8bit=is_8bit,
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
        ds = cls.apply_transfer_syntax(ds, syntax_name)
        return ds

    @classmethod
    def create_instances_from_mwl(
        cls, mwl_record: dict[str, Any], num_instances: int | None = None
    ) -> list[FileDataset]:
        """Synthesize DICOM image FileDatasets on the fly matching an MWL record."""
        import random

        if num_instances is None:
            num_instances = mwl_record.get("num_instances")
        if num_instances is None:
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
        study_desc = json_e.get("00081030", {}).get("Value", [None])[0] or get_random_study_description(modality)
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
            burn_in_text=True,
        )

        template_ds = mwl_record.get("template_dataset")
        if not template_ds:
            templates_dir = Path(getattr(config, "templates_path", "./templates"))
            if templates_dir.exists() and templates_dir.is_dir():
                for p in templates_dir.rglob("*"):
                    if p.is_file() and p.suffix.lower() in (".dcm", ".dicom"):
                        try:
                            import pydicom

                            temp_read = pydicom.dcmread(p, force=True)
                            temp_mod = str(getattr(temp_read, "Modality", "")).strip().upper()
                            if temp_mod == modality:
                                template_ds = temp_read
                                break
                        except Exception:
                            pass

        rows = int(mwl_record.get("rows") or 512)
        cols = int(mwl_record.get("columns") or mwl_record.get("cols") or 512)

        if template_ds:
            datasets = []
            for i in range(1, num_instances + 1):
                ds = cls.create_dicom_from_template(
                    template=template_ds,
                    transfer_syntax=mwl_record.get("transfer_syntax"),
                    patient_name=patient_name,
                    patient_id=patient_id,
                    study_date=study_date,
                    study_time=study_time,
                    image_number=i,
                    burn_in_text=True,
                    rows=rows,
                    cols=cols,
                    institution_name=inst_name,
                    referring_physician_name=ref_phys,
                    performing_physician_name=perf_phys,
                    reading_physician_name=read_phys,
                    study_description=study_desc,
                    accession_number=accession,
                    modality=modality,
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
                ds.StudyDescription = study_desc
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
            return datasets

        datasets = []
        for i in range(1, num_instances + 1):
            ds = cls.create_dicom_file(mock_req, instance_number=i)
            datasets.append(ds)
        return datasets

    def generate_and_save(self, request: MockDicomRequest, target_dir: str) -> MockDicomResponse:
        """Generate a batch of DICOM files and save them to target_dir."""
        out_path = Path(target_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        patient_id = request.patient.patient_id
        patient_name = request.patient.patient_name
        accession = request.study.accession_number or ""
        study_uid = request.study.study_instance_uid or generate_study_uid(patient_name, patient_id, accession)
        series_uid = request.series.series_instance_uid or generate_series_uid(study_uid, request.series.series_number)

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
