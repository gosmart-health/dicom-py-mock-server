"""FHIR Imaging Parser for extracting DICOM MWL and C-FIND parameters from FHIR Bundles."""

from __future__ import annotations

import copy
import datetime
from typing import Any

import structlog
from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.imagingstudy import ImagingStudy
from fhir.resources.R4B.patient import Patient

from dicom_py_mock_server.config import config as global_config
from dicom_py_mock_server.models.fhir_models import format_human_name_to_dicom
from dicom_py_mock_server.services.person_generator import PersonGenerator
from dicom_py_mock_server.services.uid_generator import generate_series_uid, generate_study_uid

logger = structlog.get_logger(__name__)


def _normalize_bundle_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Normalize raw dictionary payloads for standard FHIR R4B validation."""
    for entry in d.get("entry", []):
        res = entry.get("resource")
        if isinstance(res, dict) and res.get("resourceType") == "ImagingStudy":
            if not res.get("subject"):
                res["subject"] = {"reference": "Patient/UNKNOWN"}
            if not res.get("status"):
                res["status"] = "available"
            for s in res.get("series", []):
                if isinstance(s, dict) and "uid" in s and isinstance(s["uid"], str):
                    cleaned = clean_dicom_uid(s["uid"])
                    if cleaned:
                        s["uid"] = cleaned
    return d


def clean_dicom_uid(raw_uid: str | None) -> str | None:
    """Strip URI schemes such as urn:oid: and urn:uuid: from a DICOM UID string."""
    if not raw_uid:
        return None
    val = str(raw_uid).strip()
    for prefix in ("urn:oid:", "urn:uuid:", "urn:"):
        if val.lower().startswith(prefix):
            val = val[len(prefix) :].strip()
    return val or None


class FhirImagingParser:
    """Parses FHIR Patient and ImagingStudy resources into normalized DICOM MWL records."""

    def __init__(self, mwl_service: Any | None = None, app_config: Any | None = None) -> None:
        self.mwl_service = mwl_service
        self.config = app_config or (getattr(mwl_service, "config", None) if mwl_service else None) or global_config
        self._study_accessions: dict[str, str] = {}

    def extract_patient_demographics(self, patient: Patient | None) -> dict[str, str] | None:
        """Extract standardized DICOM patient demographics from FHIR Patient resource.

        Requires an identifier matching GOSMART_MS_FHIR_PATIENT_ID_SYSTEM. If missing or
        patient is None, logs a warning and returns None.
        """
        target_system = str(
            getattr(self.config, "fhir_patient_id_system", "urn:oid:2.16.840.1.113883.4.3.25") or ""
        ).strip()
        patient_res_id = (getattr(patient, "id", None) or "UNKNOWN") if patient else "UNKNOWN"

        if not patient:
            warn_msg = (
                f"FHIR Patient Resource {patient_res_id} does not contain the identifier matching "
                f"GOSMART_MS_FHIR_PATIENT_ID_SYSTEM={target_system}"
            )
            logger.warning(warn_msg, patient_resource_id=patient_res_id, target_system=target_system)
            return None

        matched_value: str | None = None
        for ident in getattr(patient, "identifier", None) or []:
            ident_system = getattr(ident, "system", None)
            ident_value = getattr(ident, "value", None)
            if isinstance(ident, dict):
                ident_system = ident.get("system")
                ident_value = ident.get("value")

            if ident_system and str(ident_system).strip() == target_system and ident_value and str(ident_value).strip():
                matched_value = str(ident_value).strip()
                break

        if not matched_value:
            warn_msg = (
                f"FHIR Patient Resource {patient_res_id} does not contain the identifier matching "
                f"GOSMART_MS_FHIR_PATIENT_ID_SYSTEM={target_system}"
            )
            logger.warning(warn_msg, patient_resource_id=patient_res_id, target_system=target_system)
            return None

        # For FHIR-based patient ID, do not prefix with GSH- or any other prefix
        patient_id = matched_value

        patient_name = "UNKNOWN^PATIENT"
        if patient.name:
            for name in patient.name:
                pn = format_human_name_to_dicom(name)
                if pn:
                    # Raw Demographics Preservation: do not append synthetic _GSH suffix
                    patient_name = pn
                    break

        patient_birth_date = "19700101"
        if patient.birthDate:
            patient_birth_date = str(patient.birthDate).replace("-", "")[:8]

        patient_sex = "O"
        if patient.gender:
            g = str(patient.gender).lower().strip()
            patient_sex = "M" if g in ("male", "m") else ("F" if g in ("female", "f") else "O")

        return {
            "patient_id": patient_id,
            "patient_name": patient_name,
            "dob": patient_birth_date,
            "sex": patient_sex,
        }

    def parse_bundle_to_custom_entries(
        self,
        bundle_data: dict[str, Any] | Bundle,
    ) -> list[dict[str, Any]]:
        """Parse a FHIR bundle into a list of custom dictionary records ready for MWL generation."""
        bundle: Bundle | None = None
        if isinstance(bundle_data, dict):
            try:
                normalized = _normalize_bundle_dict(copy.deepcopy(bundle_data))
                bundle = Bundle.model_validate(normalized)
            except Exception as exc:
                logger.warning("fhir_bundle_validation_failed", error=str(exc))
                return []
        elif isinstance(bundle_data, Bundle):
            bundle = bundle_data
        else:
            return []

        if not bundle or not bundle.entry:
            return []

        patient_res: Patient | None = None
        imaging_studies: list[ImagingStudy] = []

        for entry in bundle.entry:
            res = entry.resource
            if not res:
                continue
            if isinstance(res, Patient):
                patient_res = res
            elif isinstance(res, ImagingStudy):
                imaging_studies.append(res)

        if not patient_res:
            target_system = str(
                getattr(self.config, "fhir_patient_id_system", "urn:oid:2.16.840.1.113883.4.3.25") or ""
            ).strip()
            warn_msg = (
                "FHIR Patient Resource UNKNOWN does not contain the identifier matching "
                f"GOSMART_MS_FHIR_PATIENT_ID_SYSTEM={target_system}"
            )
            logger.warning(warn_msg, patient_resource_id="UNKNOWN", target_system=target_system)
            return []

        demo = self.extract_patient_demographics(patient_res)
        if not demo:
            return []

        custom_entries: list[dict[str, Any]] = []

        # Select physicians
        ref_physician = (
            self.mwl_service.referring_physicians[0]
            if self.mwl_service and getattr(self.mwl_service, "referring_physicians", None)
            else f"Dr. Referring{self.config.pn_suffix}"
        )
        perf_physician = (
            self.mwl_service.performing_physicians[0]
            if self.mwl_service and getattr(self.mwl_service, "performing_physicians", None)
            else f"Dr. Performing{self.config.pn_suffix}"
        )

        for imaging in imaging_studies:
            raw_study_uid: str | None = None
            if imaging.identifier:
                for ident in imaging.identifier:
                    ident_val = getattr(ident, "value", None)
                    if isinstance(ident, dict):
                        ident_val = ident.get("value")
                    if ident_val:
                        cleaned = clean_dicom_uid(ident_val)
                        if cleaned:
                            raw_study_uid = cleaned
                            break

            explicit_accession: str | None = None
            if imaging.identifier:
                for ident in imaging.identifier:
                    ident_val = getattr(ident, "value", None)
                    if isinstance(ident, dict):
                        ident_val = ident.get("value")
                    if not ident_val:
                        continue
                    clean_val = str(ident_val).strip()
                    ident_type = getattr(ident, "type", None) or (
                        ident.get("type") if isinstance(ident, dict) else None
                    )
                    if ident_type:
                        codings = (
                            getattr(ident_type, "coding", None)
                            or (ident_type.get("coding") if isinstance(ident_type, dict) else None)
                            or []
                        )
                        for c in codings:
                            code = getattr(c, "code", None) if not isinstance(c, dict) else c.get("code")
                            if code == "ACSN":
                                explicit_accession = clean_val
                                break
                    if explicit_accession:
                        break

            study_key = raw_study_uid or getattr(imaging, "id", None) or f"{demo['patient_id']}:study"
            if study_key not in self._study_accessions:
                if explicit_accession:
                    self._study_accessions[study_key] = explicit_accession
                else:
                    # For FHIR-based accession numbers, do not prefix with GSH- or any other prefix
                    self._study_accessions[study_key] = PersonGenerator.generate_random_id(8, prefix="")
            study_accession = self._study_accessions[study_key]

            study_uid = raw_study_uid or generate_study_uid(demo["patient_name"], demo["patient_id"], study_accession)

            # Procedure description
            study_desc: str | None = None
            if imaging.procedureCode:
                first_proc = imaging.procedureCode[0]
                study_desc = getattr(first_proc, "text", None)
                if not study_desc and getattr(first_proc, "coding", None) and len(first_proc.coding) > 0:
                    study_desc = first_proc.coding[0].display
            if not study_desc and imaging.description:
                study_desc = imaging.description

            # Study date/time from started
            study_date = datetime.datetime.now().strftime("%Y%m%d")
            study_time = "120000"
            if imaging.started:
                try:
                    dt = imaging.started
                    if hasattr(dt, "strftime"):
                        study_date = dt.strftime("%Y%m%d")
                        study_time = dt.strftime("%H%M%S")
                    else:
                        s_dt = str(dt)
                        if "T" in s_dt:
                            d_part, t_part = s_dt.split("T", 1)
                            study_date = d_part.replace("-", "")
                            study_time = t_part.replace(":", "").replace("Z", "")[:6]
                except Exception:
                    pass

            # Institution name
            institution_name = self.config.institution_name
            if imaging.location and imaging.location.display:
                institution_name = imaging.location.display

            # Parse series
            series_list = imaging.series or []
            if not series_list:
                # If no series list, default to CT
                modality = "CT"
                custom_entries.append(
                    {
                        "patient_name": demo["patient_name"],
                        "patient_id": demo["patient_id"],
                        "dob": demo["dob"],
                        "sex": demo["sex"],
                        "modality": modality,
                        "accession": study_accession,
                        "study_uid": study_uid,
                        "series_uid": generate_series_uid(study_uid, 1),
                        "series_number": 1,
                        "series_description": study_desc or f"{modality} Series",
                        "study_description": study_desc or f"{modality} Procedure",
                        "reason": study_desc or f"{modality} Procedure",
                        "institution_name": institution_name,
                        "referring_physician": ref_physician,
                        "performing_physician": perf_physician,
                        "num_instances": 1,
                        "studyDate": study_date,
                        "studyTime": study_time,
                    }
                )
                continue

            for s in series_list:
                modality = s.modality.code if (s.modality and s.modality.code) else "CT"
                modality = str(modality).strip().upper()

                series_uid = clean_dicom_uid(s.uid) if getattr(s, "uid", None) else None
                series_number = int(s.number) if getattr(s, "number", None) is not None else 1
                raw_instances = getattr(s, "numberOfInstances", None) or (
                    len(s.instance) if getattr(s, "instance", None) else 1
                )
                num_instances = max(1, min(1024, int(raw_instances)))

                effective_study_desc = study_desc or f"{modality} Procedure"
                series_description = (
                    s.description
                    or (s.bodySite.display if (getattr(s, "bodySite", None) and s.bodySite.display) else None)
                    or effective_study_desc
                )

                custom_entries.append(
                    {
                        "patient_name": demo["patient_name"],
                        "patient_id": demo["patient_id"],
                        "dob": demo["dob"],
                        "sex": demo["sex"],
                        "modality": modality,
                        "accession": study_accession,
                        "study_uid": study_uid,
                        "series_uid": series_uid or generate_series_uid(study_uid, series_number),
                        "series_number": series_number,
                        "series_description": series_description,
                        "study_description": effective_study_desc,
                        "reason": effective_study_desc,
                        "institution_name": institution_name,
                        "referring_physician": ref_physician,
                        "performing_physician": perf_physician,
                        "num_instances": num_instances,
                        "studyDate": study_date,
                        "studyTime": study_time,
                    }
                )

        return custom_entries
