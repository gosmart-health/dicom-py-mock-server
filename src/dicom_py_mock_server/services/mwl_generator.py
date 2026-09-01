"""Service for generating DICOM Modality Worklist (MWL) objects and managing the active MWL list."""

import asyncio
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pydicom
import structlog
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pydicom.uid import CTImageStorage

from dicom_py_mock_server.config import AppConfig
from dicom_py_mock_server.config import config as global_config
from dicom_py_mock_server.services.generator import get_random_study_description
from dicom_py_mock_server.services.person_generator import PersonGenerator
from dicom_py_mock_server.services.uid_generator import (
    generate_series_uid,
    generate_sop_instance_uid,
    generate_study_uid,
)

logger = structlog.get_logger(__name__)

MODALITY_TO_DEPARTMENT: dict[str, str] = {
    "CT": "RAD",
    "MR": "RAD",
    "DX": "RAD",
    "CR": "RAD",
    "US": "RAD",
    "MG": "RAD",
    "NM": "RAD",
    "PT": "RAD",
    "PET": "RAD",
    "XA": "CARD",
    "RF": "RAD",
    "OT": "RAD",
}


DEFAULT_DEPARTMENTS: list[dict[str, Any]] = [
    {
        "active": True,
        "department": "CARD",
        "modalities": ["US", "MR", "DX", "VL"],
        "reasons": [
            "Unstable angina",
            "Precordial pain",
            "Pleurodynia",
            "Intercostal pain",
            "Nonrheumatic aortic valve stenosis",
            "Coronary artery aneurysm",
        ],
    },
    {
        "active": True,
        "department": "ORTHO",
        "modalities": ["CT", "MR", "US", "DX", "VL"],
        "reasons": [
            "Removal of foreign body in muscle or tendon sheath",
            "Removal of implant deep or superficial",
            "Arthrotomy, glenohumeral joint",
            "Acromioplasty or acromionectomy",
            "Closed treatment of clavicular fracture",
            "Open treatment of humeral shaft fracture",
        ],
    },
    {
        "active": True,
        "department": "RAD",
        "modalities": ["CT", "MR", "US", "DX", "CR"],
        "reasons": [
            "Routine chest radiograph",
            "Abdominal screening US",
            "Pelvic CT scan with contrast",
            "Head CT non-contrast",
            "Spine lumbar MRI",
        ],
    },
    {
        "active": True,
        "department": "NEURO",
        "modalities": ["MR", "CT"],
        "reasons": [
            "Headache evaluation",
            "Stroke protocol MR",
            "Brain MRI with and without contrast",
            "Carotid artery ultrasound",
        ],
    },
]


class MwlGeneratorService:
    """Service to generate DICOM Modality Worklist (MWL) entries and maintain active MWL list."""

    def __init__(
        self,
        app_config: AppConfig | None = None,
        patient_generator: PersonGenerator | None = None,
    ) -> None:
        self.config = app_config or global_config
        self.patient_generator = patient_generator or PersonGenerator(
            patient_suffix=self.config.patient_suffix,
            id_prefix=self.config.id_prefix,
            pn_suffix=self.config.pn_suffix,
        )
        self.template_modalities: dict[str, dict[str, Any]] = {}
        self.dicom_templates: dict[str, list[Dataset]] = {}
        self.departments: list[dict[str, Any]] = []

        # Initial pools of 3 physician names for each role
        self.referring_physicians: list[str] = self.patient_generator.generate_physician_pool(count=3, title="MD")
        self.performing_physicians: list[str] = self.patient_generator.generate_physician_pool(count=3, title="MD")
        self.reading_physicians: list[str] = self.patient_generator.generate_physician_pool(count=3, title="MD")

        # Active MWL in-memory storage: list of dicts with dataset, json_entry, created_at
        self._entries: list[dict[str, Any]] = []

        # Auto generation background task
        self._auto_gen_task: asyncio.Task | None = None
        self._is_auto_generating = False

        self._load_templates()

    def _load_templates(self) -> None:
        """Load template modalities and DICOM/JSON templates into memory from templates_path.

        If at least one template file (.dcm, .dicom, or .json) is found in templates_path,
        the default fallback modalities are NOT loaded, ensuring MWL generation only uses
        modalities present in loaded templates.
        """
        self.departments = [d for d in DEFAULT_DEPARTMENTS if d.get("active", True)]
        self.template_modalities = {}
        self.dicom_templates = {}

        loaded_file_templates: dict[str, dict[str, Any]] = {}

        path_obj = Path(self.config.templates_path)
        if path_obj.is_absolute():
            candidate_paths = [path_obj]
        else:
            candidate_paths = [
                path_obj,
                Path.cwd() / path_obj,
            ]
            for parent in Path(__file__).resolve().parents:
                candidate_paths.append(parent / path_obj)

        templates_dir = None
        for p in candidate_paths:
            if p.exists() and p.is_dir() and any(p.rglob("*")):
                templates_dir = p
                break

        if templates_dir:
            for file_path in templates_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                ext = file_path.suffix.lower()
                if ext in (".dcm", ".dicom"):
                    try:
                        ds = pydicom.dcmread(file_path, force=True)
                        modality = ""
                        if "Modality" in ds and ds.Modality:
                            modality = str(ds.Modality).strip().upper()
                        if not modality:
                            stem = file_path.stem.upper()
                            modality = stem.split("_")[0] if "_" in stem else stem

                        if modality not in self.dicom_templates:
                            self.dicom_templates[modality] = []
                        self.dicom_templates[modality].append(ds)

                        loaded_file_templates[modality] = {
                            "modality": modality,
                            "source": str(file_path),
                            "format": "dicom",
                            "dataset": ds,
                        }
                        logger.info("loaded_dicom_template_file", modality=modality, path=str(file_path))
                    except Exception as exc:
                        logger.warning("failed_to_load_dicom_template_file", path=str(file_path), error=str(exc))
                elif ext == ".json":
                    try:
                        data = json.loads(file_path.read_text(encoding="utf-8"))
                        modality = str(data.get("modality") or file_path.stem).strip().upper()
                        loaded_file_templates[modality] = {
                            "modality": modality,
                            "source": str(file_path),
                            "format": "json",
                            "data": data,
                        }
                        logger.info("loaded_mwl_template_file", modality=modality, path=str(file_path))
                    except Exception as exc:
                        logger.warning("failed_to_load_template_file", path=str(file_path), error=str(exc))

        if loaded_file_templates:
            # Only use modalities from loaded template files
            self.template_modalities = loaded_file_templates
        else:
            self.template_modalities = {}
            logger.error("no_template_files_found_in_templates_path", templates_path=str(self.config.templates_path))

        logger.info(
            "mwl_template_modalities_loaded",
            loaded_modalities=list(self.template_modalities.keys()),
            has_dicom_templates=bool(self.dicom_templates),
        )

    def get_template_modalities(self) -> list[str]:
        """Get the list of currently loaded in-memory template modalities."""
        return sorted(self.template_modalities.keys())

    def get_dicom_templates_by_modality(self, modality: str) -> list[Dataset]:
        """Get in-memory loaded DICOM template datasets for a specific modality.

        If no template dataset exists specifically for `modality`, fall back to any available
        loaded DICOM template dataset so template-based synthesis is always used.
        """
        mod_upper = modality.upper()
        if mod_upper in self.dicom_templates:
            return self.dicom_templates[mod_upper]

        all_templates = [ds for sublist in self.dicom_templates.values() for ds in sublist]
        return all_templates

    def get_current_rate_per_hr(self, current_time: datetime | None = None) -> float:
        """Calculate current MWL entry creation rate based on local machine time.

        Business hours: 9 am - 5 pm (09:00 <= hour < 17:00) local time -> 100% rate.
        After hours: Before 9 am or at/after 5 pm local time -> 5% rate.
        """
        if current_time is None:
            current_time = datetime.now()

        local_hour = current_time.hour
        if 9 <= local_hour < 17:
            return float(self.config.mwl_rate_per_hr)
        else:
            return float(self.config.mwl_rate_per_hr) * 0.05

    def generate_json(
        self,
        custom: dict[str, Any] | None = None,
        scheduled_at: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Generate a single MWL DICOM Web JSON entry matching mwlEntryGenerator.ts format.

        Returns None if no template file is loaded.
        """
        if not self.template_modalities and not self.dicom_templates:
            logger.error(
                "mwl_template_not_found_cannot_generate_entry",
                templates_path=str(self.config.templates_path),
            )
            return None

        now = scheduled_at or datetime.now()

        # Determine modality
        if custom and "modality" in custom:
            modality = str(custom["modality"]).strip().upper()
        else:
            available_modalities = self.get_template_modalities()
            if available_modalities:
                modality = random.choice(available_modalities)
            else:
                modality = "CT"

        # Modality-aligned description and department
        description = get_random_study_description(modality)
        department_name = MODALITY_TO_DEPARTMENT.get(modality.upper(), "RAD")

        # Patient demographics
        patient = self.patient_generator.generate(is_patient=True)

        # Physician demographics - randomly pick from startup-generated pools
        referring_name = (
            random.choice(self.referring_physicians)
            if self.referring_physicians
            else self.patient_generator.generate_physician("MD").name
        )
        performing_name = (
            random.choice(self.performing_physicians)
            if self.performing_physicians
            else self.patient_generator.generate_physician("MD").name
        )
        reading_name = (
            random.choice(self.reading_physicians)
            if self.reading_physicians
            else self.patient_generator.generate_physician("MD").name
        )
        institution = self.config.institution_name

        # IDs and UIDs
        accession = PersonGenerator.generate_random_id(8, prefix=self.config.id_prefix)
        sps_id = PersonGenerator.generate_random_id(5)
        req_proc_id = PersonGenerator.generate_random_id(4)

        start_date = now.strftime("%Y%m%d")
        start_time = now.strftime("%H%M%S")

        patient_name = patient.name
        patient_id = patient.mrn
        dob_str = patient.dob.strftime("%Y%m%d")
        sex = patient.gender
        scheduled_station_ae = "ZEN_SNAP_MD"
        scheduled_station_name = "ZenSnapMD 4.1"

        # Apply overrides if custom dictionary provided
        custom_study_uid = None
        if custom:
            patient_name = custom.get("patientName") or patient_name
            patient_id = custom.get("patientId") or custom.get("mrn") or patient_id
            if custom.get("dob"):
                if isinstance(custom["dob"], (datetime, datetime.date)):
                    dob_str = custom["dob"].strftime("%Y%m%d")
                else:
                    dob_str = str(custom["dob"]).replace("-", "")
            sex = custom.get("sex") or custom.get("gender") or sex
            modality = custom.get("modality") or modality
            accession = custom.get("accession") or accession
            custom_study_uid = custom.get("studyUid") or custom.get("study_uid")
            description = custom.get("studyDescription") or custom.get("reason") or description
            department_name = custom.get("department") or department_name
            referring_name = custom.get("referringPhysician") or custom.get("referring_physician") or referring_name
            performing_name = (
                custom.get("performingPhysician")
                or custom.get("performing_physician")
                or custom.get("attendingPhysician")
                or performing_name
            )
            reading_name = custom.get("readingPhysician") or custom.get("reading_physician") or reading_name
            institution = (
                custom.get("institutionName")
                or custom.get("institution_name")
                or custom.get("institution")
                or institution
            )
            if custom.get("studyDate") and isinstance(custom["studyDate"], datetime):
                start_date = custom["studyDate"].strftime("%Y%m%d")
                start_time = custom["studyDate"].strftime("%H%M%S")

        study_uid = custom_study_uid or generate_study_uid(patient_name, patient_id, accession)
        series_uid = generate_series_uid(study_uid, 1)
        sop_instance_uid = generate_sop_instance_uid(series_uid, 1)

        json_entry = {
            "00080005": {"vr": "CS", "Value": ["ISO_IR 192"]},
            "00080018": {"vr": "UI", "Value": [sop_instance_uid]},
            "00080050": {"vr": "SH", "Value": [accession]},
            "00080060": {"vr": "CS", "Value": [modality]},
            "00080080": {"vr": "LO", "Value": [institution]},
            "00080090": {"vr": "PN", "Value": [{"Alphabetic": referring_name}]},
            "00081030": {"vr": "LO", "Value": [description]},
            "00081040": {"vr": "LO", "Value": [department_name]},
            "00081050": {"vr": "PN", "Value": [{"Alphabetic": performing_name}]},
            "00081060": {"vr": "PN", "Value": [{"Alphabetic": reading_name}]},
            "00100010": {"vr": "PN", "Value": [{"Alphabetic": patient_name}]},
            "00100020": {"vr": "LO", "Value": [patient_id]},
            "00100030": {"vr": "DA", "Value": [dob_str]},
            "00100040": {"vr": "CS", "Value": [sex]},
            "00101000": {"vr": "LO", "Value": [""]},
            "00101030": {"vr": "DS", "Value": ["0"]},
            "00102000": {"vr": "LO", "Value": [""]},
            "00102110": {"vr": "LO", "Value": [""]},
            "001021B0": {"vr": "LT", "Value": ""},
            "0020000D": {"vr": "UI", "Value": [study_uid]},
            "00321032": {"vr": "PN", "Value": [{"Alphabetic": referring_name}]},
            "00321060": {"vr": "LO", "Value": [description]},
            "00321064": {
                "vr": "SQ",
                "Value": [
                    {
                        "00080100": {"vr": "SH", "Value": ["18804247"]},
                        "00080102": {"vr": "SH", "Value": ""},
                        "00080104": {"vr": "LO", "Value": [description]},
                    }
                ],
            },
            "00380010": {"vr": "SH", "Value": [accession]},
            "00400009": {"vr": "SH", "Value": [sps_id]},
            "00400100": {
                "vr": "SQ",
                "Value": [
                    {
                        "00080060": {"vr": "CS", "Value": [modality]},
                        "00400001": {"vr": "AE", "Value": [scheduled_station_ae]},
                        "00400002": {"vr": "DA", "Value": [start_date]},
                        "00400003": {"vr": "TM", "Value": [start_time]},
                        "00400006": {"vr": "PN", "Value": [{"Alphabetic": performing_name}]},
                        "00400007": {"vr": "LO", "Value": [description]},
                        "00400008": {
                            "vr": "SQ",
                            "Value": [
                                {
                                    "00080100": {"vr": "SH", "Value": ["18804247"]},
                                    "00080102": {"vr": "SH", "Value": None},
                                    "00080104": {"vr": "LO", "Value": [description]},
                                }
                            ],
                        },
                        "00400009": {"vr": "SH", "Value": [sps_id]},
                        "00400010": {"vr": "SH", "Value": [scheduled_station_name]},
                    }
                ],
            },
            "00401001": {"vr": "SH", "Value": [req_proc_id]},
        }

        return json_entry

    def generate_dataset(self, custom: dict[str, Any] | None = None, scheduled_at: datetime | None = None) -> Dataset:
        """Generate a pydicom Dataset representing the Modality Worklist entry."""
        json_entry = self.generate_json(custom=custom, scheduled_at=scheduled_at)
        return self.json_to_dataset(json_entry)

    @staticmethod
    def json_to_dataset(json_entry: dict[str, Any]) -> Dataset:
        """Convert DICOM Web JSON dictionary to a pydicom Dataset."""
        ds = Dataset()

        # Specific Character Set
        ds.SpecificCharacterSet = json_entry["00080005"]["Value"][0]
        # Accession Number
        ds.AccessionNumber = json_entry["00080050"]["Value"][0]
        # Modality
        ds.Modality = json_entry["00080060"]["Value"][0]
        # Institution Name
        ds.InstitutionName = json_entry["00080080"]["Value"][0]
        # Referring Physician's Name
        ref_pn = json_entry["00080090"]["Value"][0]
        ds.ReferringPhysicianName = ref_pn.get("Alphabetic", "") if isinstance(ref_pn, dict) else ref_pn
        # Performing Physician's Name
        if "00081050" in json_entry and json_entry["00081050"].get("Value"):
            perf_pn = json_entry["00081050"]["Value"][0]
            ds.PerformingPhysicianName = perf_pn.get("Alphabetic", "") if isinstance(perf_pn, dict) else perf_pn
        # Name of Physician(s) Reading Study
        if "00081060" in json_entry and json_entry["00081060"].get("Value"):
            read_pn = json_entry["00081060"]["Value"][0]
            ds.NameOfPhysiciansReadingStudy = read_pn.get("Alphabetic", "") if isinstance(read_pn, dict) else read_pn
        # Study Description
        ds.StudyDescription = json_entry["00081030"]["Value"][0]
        # Institutional Department Name
        ds.InstitutionalDepartmentName = json_entry["00081040"]["Value"][0]

        # Patient Module
        pat_pn = json_entry["00100010"]["Value"][0]
        ds.PatientName = pat_pn.get("Alphabetic", "") if isinstance(pat_pn, dict) else pat_pn
        ds.PatientID = json_entry["00100020"]["Value"][0]
        ds.PatientBirthDate = json_entry["00100030"]["Value"][0]
        ds.PatientSex = json_entry["00100040"]["Value"][0]

        # Study Instance UID
        ds.StudyInstanceUID = json_entry["0020000D"]["Value"][0]
        # Requested Procedure Description
        ds.RequestedProcedureDescription = json_entry["00321060"]["Value"][0]
        # Requested Procedure ID
        ds.RequestedProcedureID = json_entry["00401001"]["Value"][0]

        # Scheduled Procedure Step Sequence (0040,0100)
        sps_json_list = json_entry["00400100"]["Value"]
        sps_sequence = Sequence()
        for sps_item in sps_json_list:
            sps_ds = Dataset()
            sps_ds.Modality = sps_item["00080060"]["Value"][0]
            sps_ds.ScheduledStationAETitle = sps_item["00400001"]["Value"][0]
            sps_ds.ScheduledProcedureStepStartDate = sps_item["00400002"]["Value"][0]
            sps_ds.ScheduledProcedureStepStartTime = sps_item["00400003"]["Value"][0]
            sps_raw_perf = sps_item["00400006"]["Value"]
            if isinstance(sps_raw_perf, list) and len(sps_raw_perf) > 0:
                sps_perf_val = sps_raw_perf[0]
            else:
                sps_perf_val = sps_raw_perf
            sps_ds.ScheduledPerformingPhysicianName = (
                sps_perf_val.get("Alphabetic", "") if isinstance(sps_perf_val, dict) else sps_perf_val
            )
            sps_ds.ScheduledProcedureStepDescription = sps_item["00400007"]["Value"][0]
            sps_ds.ScheduledProcedureStepID = sps_item["00400009"]["Value"][0]
            sps_ds.ScheduledStationName = sps_item["00400010"]["Value"][0]
            sps_sequence.append(sps_ds)

        ds.ScheduledProcedureStepSequence = sps_sequence
        return ds

    def purge_expired_entries(self, current_time: datetime | None = None) -> int:
        """Purge MWL entries older than GOSMART_MS_MWL_WINDOW_HR hours."""
        if current_time is None:
            current_time = datetime.now()

        cutoff = current_time - timedelta(hours=self.config.mwl_window_hr)
        initial_count = len(self._entries)
        self._entries = [e for e in self._entries if e.get("created_at", current_time) >= cutoff]
        purged = initial_count - len(self._entries)
        if purged > 0:
            logger.info("purged_expired_mwl_entries", count=purged, remaining=len(self._entries))
        return purged

    def add_entry(
        self, custom: dict[str, Any] | None = None, scheduled_at: datetime | None = None
    ) -> dict[str, Any] | None:
        """Generate and add a new MWL entry to the active MWL list."""
        now = datetime.now()
        json_entry = self.generate_json(custom=custom, scheduled_at=scheduled_at)
        if not json_entry:
            logger.error("cannot_add_mwl_entry_due_to_missing_template", custom=custom)
            return None

        dataset = self.json_to_dataset(json_entry)

        # Determine randomized instance count between min_slices and max_slices
        custom_instances = custom.get("num_instances") or custom.get("numInstances") if custom else None
        if custom_instances is not None:
            num_instances = int(custom_instances)
        else:
            num_instances = random.randint(self.config.min_slices, self.config.max_slices)

        custom_sn = (custom.get("seriesNumber") or custom.get("series_number") or 1) if custom else 1
        custom_suid = (custom.get("seriesUid") or custom.get("series_uid")) if custom else None
        custom_sdesc = (custom.get("seriesDescription") or custom.get("series_description")) if custom else None

        ref_val = json_entry["00080090"]["Value"][0]
        ref_name = ref_val.get("Alphabetic", "") if isinstance(ref_val, dict) else ref_val
        perf_val = json_entry.get("00081050", {}).get("Value", [""])[0]
        perf_name = perf_val.get("Alphabetic", "") if isinstance(perf_val, dict) else perf_val
        read_val = json_entry.get("00081060", {}).get("Value", [""])[0]
        read_name = read_val.get("Alphabetic", "") if isinstance(read_val, dict) else read_val
        inst_name = json_entry.get("00080080", {}).get("Value", [""])[0]
        templates_for_mod = self.get_dicom_templates_by_modality(json_entry["00080060"]["Value"][0])
        dicom_template = random.choice(templates_for_mod) if templates_for_mod else None

        entry_record = {
            "json_entry": json_entry,
            "dataset": dataset,
            "template_dataset": dicom_template,
            "created_at": scheduled_at or now,
            "patient_id": json_entry["00100020"]["Value"][0],
            "patient_name": json_entry["00100010"]["Value"][0].get("Alphabetic", ""),
            "accession": json_entry["00080050"]["Value"][0],
            "modality": json_entry["00080060"]["Value"][0],
            "study_uid": json_entry["0020000D"]["Value"][0],
            "series_uid": custom_suid or generate_series_uid(json_entry["0020000D"]["Value"][0], custom_sn),
            "series_number": int(custom_sn),
            "series_description": custom_sdesc or f"{json_entry['00080060']['Value'][0]} Series",
            "referring_physician": ref_name,
            "performing_physician": perf_name,
            "reading_physician": read_name,
            "institution_name": inst_name,
            "num_instances": num_instances,
            "transfer_syntax": (custom or {}).get("transfer_syntax") or (custom or {}).get("transferSyntax"),
        }

        self._entries.append(entry_record)
        self.purge_expired_entries(now)
        logger.info(
            "added_mwl_entry",
            patient_id=entry_record["patient_id"],
            accession=entry_record["accession"],
            modality=entry_record["modality"],
            study_uid=entry_record["study_uid"],
            series_uid=entry_record["series_uid"],
            num_instances=entry_record["num_instances"],
        )
        return entry_record

    def seed_initial_entries(self, count: int = 10) -> list[dict[str, Any]]:
        """Populate initial MWL entries spread across the active window."""
        now = datetime.now()
        window_hr = self.config.mwl_window_hr
        seeded: list[dict[str, Any]] = []

        for i in range(count):
            # Spread times backwards across the window
            offset_hours = (window_hr / count) * i
            sched_time = now - timedelta(hours=offset_hours)
            record = self.add_entry(scheduled_at=sched_time)
            seeded.append(record)

        logger.info("seeded_mwl_entries", count=len(seeded), window_hr=window_hr)
        return seeded

    def list_entries(self) -> list[dict[str, Any]]:
        """Get all current active MWL entries within the window."""
        self.purge_expired_entries()
        return [
            {
                "patient_id": e["patient_id"],
                "patient_name": e["patient_name"],
                "accession": e["accession"],
                "modality": e["modality"],
                "study_uid": e["study_uid"],
                "series_uid": e.get("series_uid", ""),
                "series_number": e.get("series_number", 1),
                "series_description": e.get("series_description", ""),
                "referring_physician": e.get("referring_physician"),
                "performing_physician": e.get("performing_physician"),
                "reading_physician": e.get("reading_physician"),
                "institution_name": e.get("institution_name"),
                "num_instances": e.get("num_instances", self.config.min_slices),
                "created_at": e["created_at"].isoformat(),
                "json_entry": e["json_entry"],
            }
            for e in self._entries
        ]

    def get_datasets(self) -> list[Dataset]:
        """Get list of pydicom Dataset objects for active MWL entries."""
        self.purge_expired_entries()
        return [e["dataset"] for e in self._entries]

    @staticmethod
    def _matches_filter(val: Any, query: str | None) -> bool:
        """Helper to match DICOM attribute value against query with wildcard and case insensitivity."""
        if not query or not str(query).strip() or str(query).strip() == "*":
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

    def find_entries(
        self,
        study_uid: str | None = None,
        series_uid: str | None = None,
        patient_id: str | None = None,
        accession: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find active MWL entries matching query keys."""
        self.purge_expired_entries()
        matched = []
        for e in self._entries:
            if study_uid and not self._matches_filter(e.get("study_uid"), study_uid):
                continue
            if series_uid and not self._matches_filter(e.get("series_uid"), series_uid):
                continue
            if patient_id and not self._matches_filter(e.get("patient_id"), patient_id):
                continue
            if accession and not self._matches_filter(e.get("accession"), accession):
                continue
            matched.append(e)
        return matched

    @staticmethod
    def to_study_cfind_dataset(entry: dict[str, Any]) -> Dataset:
        """Convert MWL entry record into a DICOM Study Root C-FIND (STUDY Level) response Dataset."""
        ds = Dataset()
        json_e = entry.get("json_entry", {})

        ds.QueryRetrieveLevel = "STUDY"
        ds.PatientName = entry.get("patient_name", "")
        ds.PatientID = entry.get("patient_id", "")
        if "00100030" in json_e and json_e["00100030"].get("Value"):
            ds.PatientBirthDate = json_e["00100030"]["Value"][0]
        if "00100040" in json_e and json_e["00100040"].get("Value"):
            ds.PatientSex = json_e["00100040"]["Value"][0]

        ds.StudyInstanceUID = entry.get("study_uid", "")
        ds.AccessionNumber = entry.get("accession", "")

        # Institution and Physician names
        inst_name = entry.get("institution_name") or json_e.get("00080080", {}).get("Value", [""])[0]
        if inst_name:
            ds.InstitutionName = inst_name

        ref_phys = entry.get("referring_physician")
        if not ref_phys and "00080090" in json_e and json_e["00080090"].get("Value"):
            ref_raw = json_e["00080090"]["Value"][0]
            ref_phys = ref_raw.get("Alphabetic", "") if isinstance(ref_raw, dict) else ref_raw
        if ref_phys:
            ds.ReferringPhysicianName = ref_phys

        perf_phys = entry.get("performing_physician")
        if not perf_phys and "00081050" in json_e and json_e["00081050"].get("Value"):
            perf_raw = json_e["00081050"]["Value"][0]
            perf_phys = perf_raw.get("Alphabetic", "") if isinstance(perf_raw, dict) else perf_raw
        if perf_phys:
            ds.PerformingPhysicianName = perf_phys

        read_phys = entry.get("reading_physician")
        if not read_phys and "00081060" in json_e and json_e["00081060"].get("Value"):
            read_raw = json_e["00081060"]["Value"][0]
            read_phys = read_raw.get("Alphabetic", "") if isinstance(read_raw, dict) else read_raw
        if read_phys:
            ds.NameOfPhysiciansReadingStudy = read_phys

        # Study Date & Time from SPS sequence if available
        sps_seq = json_e.get("00400100", {}).get("Value", [{}])[0]
        ds.StudyDate = sps_seq.get("00400002", {}).get("Value", [""])[0]
        ds.StudyTime = sps_seq.get("00400003", {}).get("Value", [""])[0]

        if "00081030" in json_e and json_e["00081030"].get("Value"):
            ds.StudyDescription = json_e["00081030"]["Value"][0]

        modality = entry.get("modality", "CT")
        ds.ModalitiesInStudy = modality
        ds.Modality = modality
        ds.NumberOfStudyRelatedSeries = 1
        ds.NumberOfStudyRelatedInstances = int(entry.get("num_instances") or 8)

        # Include Series-level attributes as well so clients requesting Series fields at Study level get full info
        ds.SeriesInstanceUID = entry.get("series_uid", "")
        ds.SeriesNumber = int(entry.get("series_number") or 1)
        ds.SeriesDescription = entry.get("series_description") or f"{modality} Series"
        ds.NumberOfSeriesRelatedInstances = int(entry.get("num_instances") or 8)

        return ds

    @staticmethod
    def to_series_cfind_dataset(entry: dict[str, Any]) -> Dataset:
        """Convert MWL entry record into a DICOM Study Root C-FIND (SERIES Level) response Dataset."""
        ds = Dataset()
        json_e = entry.get("json_entry", {})

        ds.QueryRetrieveLevel = "SERIES"
        ds.PatientName = entry.get("patient_name", "")
        ds.PatientID = entry.get("patient_id", "")
        ds.StudyInstanceUID = entry.get("study_uid", "")
        ds.SeriesInstanceUID = entry.get("series_uid", "")
        modality = entry.get("modality", "CT")
        ds.Modality = modality
        ds.SeriesNumber = int(entry.get("series_number") or 1)
        ds.SeriesDescription = entry.get("series_description") or f"{modality} Series"
        ds.NumberOfSeriesRelatedInstances = int(entry.get("num_instances") or 8)

        # Institution and Performing Physician
        inst_name = entry.get("institution_name") or json_e.get("00080080", {}).get("Value", [""])[0]
        if inst_name:
            ds.InstitutionName = inst_name

        perf_phys = entry.get("performing_physician")
        if not perf_phys and "00081050" in json_e and json_e["00081050"].get("Value"):
            perf_raw = json_e["00081050"]["Value"][0]
            perf_phys = perf_raw.get("Alphabetic", "") if isinstance(perf_raw, dict) else perf_raw
        if perf_phys:
            ds.PerformingPhysicianName = perf_phys

        ds.AccessionNumber = entry.get("accession", "")
        sps_seq = json_e.get("00400100", {}).get("Value", [{}])[0]
        ds.StudyDate = sps_seq.get("00400002", {}).get("Value", [""])[0]
        ds.StudyTime = sps_seq.get("00400003", {}).get("Value", [""])[0]

        return ds

    @staticmethod
    def to_image_cfind_datasets(entry: dict[str, Any]) -> list[Dataset]:
        """Convert MWL entry record into DICOM Study Root C-FIND (IMAGE Level) response Datasets."""
        num_instances = int(entry.get("num_instances") or 8)
        modality = entry.get("modality", "CT")
        study_uid = entry.get("study_uid", "")
        series_uid = entry.get("series_uid") or generate_series_uid(study_uid, entry.get("series_number") or 1)
        datasets = []
        for i in range(1, num_instances + 1):
            ds = Dataset()
            ds.QueryRetrieveLevel = "IMAGE"
            ds.PatientName = entry.get("patient_name", "")
            ds.PatientID = entry.get("patient_id", "")
            ds.StudyInstanceUID = study_uid
            ds.SeriesInstanceUID = series_uid
            ds.SOPInstanceUID = generate_sop_instance_uid(series_uid, i)
            ds.SOPClassUID = CTImageStorage
            ds.InstanceNumber = i
            ds.Modality = modality
            ds.SeriesNumber = int(entry.get("series_number") or 1)
            ds.NumberOfSeriesRelatedInstances = num_instances
            datasets.append(ds)
        return datasets

    def get_status(self) -> dict[str, Any]:
        """Get current MWL generator service status and configuration."""

        self.purge_expired_entries()
        now = datetime.now()
        current_rate = self.get_current_rate_per_hr(now)
        is_biz_hrs = 9 <= now.hour < 17

        return {
            "active_entries_count": len(self._entries),
            "window_hr": self.config.mwl_window_hr,
            "base_rate_per_hr": float(self.config.mwl_rate_per_hr),
            "current_rate_per_hr": current_rate,
            "is_business_hours": is_biz_hrs,
            "template_modalities": self.get_template_modalities(),
            "is_auto_generating": self._is_auto_generating,
        }

    async def _auto_generation_loop(self) -> None:
        """Async background task that generates MWL entries according to current rate."""
        logger.info("mwl_auto_generation_loop_started")
        try:
            while self._is_auto_generating:
                now = datetime.now()
                rate_per_hr = self.get_current_rate_per_hr(now)
                # Interval in seconds: 3600 / rate_per_hr
                interval = 3600.0 / max(rate_per_hr, 0.01)

                # Sleep interval seconds or wait for stop
                await asyncio.sleep(min(interval, 60.0))
                if not self._is_auto_generating:
                    break

                self.add_entry()
        except asyncio.CancelledError:
            logger.info("mwl_auto_generation_loop_cancelled")
        except Exception as exc:
            logger.error("mwl_auto_generation_loop_error", error=str(exc))
        finally:
            self._is_auto_generating = False

    def start_auto_generation(self) -> dict[str, Any]:
        """Start the background MWL entry creation loop."""
        if self._is_auto_generating and self._auto_gen_task:
            return self.get_status()

        self._is_auto_generating = True
        try:
            loop = asyncio.get_running_loop()
            self._auto_gen_task = loop.create_task(self._auto_generation_loop())
        except RuntimeError:
            logger.warning("no_running_event_loop_for_mwl_auto_generation")

        return self.get_status()

    def stop_auto_generation(self) -> dict[str, Any]:
        """Stop the background MWL entry creation loop."""
        self._is_auto_generating = False
        if self._auto_gen_task and not self._auto_gen_task.done():
            self._auto_gen_task.cancel()
            self._auto_gen_task = None
        return self.get_status()
