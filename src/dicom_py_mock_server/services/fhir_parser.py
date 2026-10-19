"""Service for parsing FHIR ServiceRequest Bundles and generating DICOM MWL entries."""

import copy
from datetime import datetime
from typing import Any

import structlog
from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.practitioner import Practitioner
from fhir.resources.R4B.servicerequest import ServiceRequest

from dicom_py_mock_server.models.fhir_models import format_human_name_to_dicom
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService

logger = structlog.get_logger(__name__)


def _normalize_fhir_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Normalize raw dictionary payloads for standard FHIR R4B validation.

    Ensures naive datetime strings without timezone offsets are given UTC 'Z' timezone,
    and defaults required fields like 'intent' or 'status' if missing in lightweight test payloads.
    """
    res_type = d.get("resourceType")
    if res_type == "ServiceRequest":
        d.setdefault("intent", "order")
        d.setdefault("status", "active")
        occ = d.get("occurrenceDateTime")
        if (
            isinstance(occ, str)
            and "T" in occ
            and not occ.endswith("Z")
            and "+" not in occ[10:]
            and "-" not in occ[10:]
        ):
            d["occurrenceDateTime"] = occ + "Z"

    for v in d.values():
        if isinstance(v, dict):
            _normalize_fhir_dict(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _normalize_fhir_dict(item)
    return d


class FhirParserService:
    """Service to parse FHIR imaging bundles into Modality Worklist (MWL) entries."""

    def __init__(self, mwl_service: MwlGeneratorService) -> None:
        self.mwl_service = mwl_service

    def process_bundle(self, bundle_data: dict[str, Any] | Bundle | ServiceRequest) -> dict[str, Any]:
        """Parse a FHIR bundle, update MWL active list, and return processing summary."""
        # Structured debug dump of raw payload
        logger.debug("fhir_bundle_raw_dump", raw_bundle=bundle_data)

        patients: dict[str, Patient] = {}
        practitioners: dict[str, Practitioner] = {}
        service_requests: list[ServiceRequest] = []
        bundle: Bundle | None = None

        if isinstance(bundle_data, dict):
            normalized_data = _normalize_fhir_dict(copy.deepcopy(bundle_data))
            res_type = normalized_data.get("resourceType")
            if res_type == "ServiceRequest":
                sr = ServiceRequest.model_validate(normalized_data)
                service_requests.append(sr)
            else:
                bundle = Bundle.model_validate(normalized_data)
        elif isinstance(bundle_data, ServiceRequest):
            service_requests.append(bundle_data)
        elif isinstance(bundle_data, Bundle):
            bundle = bundle_data
        elif getattr(bundle_data, "get_resource_type", lambda: "")() == "ServiceRequest":
            service_requests.append(bundle_data)  # type: ignore[arg-type]

        if bundle is not None and getattr(bundle, "entry", None):
            for entry in bundle.entry or []:
                res = entry.resource
                if not res:
                    continue

                res_id = getattr(res, "id", "") or ""
                if isinstance(res, Patient):
                    if res_id:
                        patients[res_id] = res
                    if entry.fullUrl:
                        patients[entry.fullUrl] = res
                elif isinstance(res, Practitioner):
                    if res_id:
                        practitioners[res_id] = res
                    if entry.fullUrl:
                        practitioners[entry.fullUrl] = res
                elif isinstance(res, ServiceRequest):
                    service_requests.append(res)

        if not service_requests:
            logger.warning("fhir_bundle_has_no_service_requests")
            return {
                "status": "ignored",
                "message": "No ServiceRequest resources found in bundle",
                "entries_created": [],
                "entries_removed": 0,
            }

        created_entries: list[dict[str, Any]] = []
        removed_count = 0
        rejections: list[dict[str, Any]] = []

        for sr in service_requests:
            # 1. Resolve Patient
            patient = None
            if sr.subject and sr.subject.reference:
                ref_key = sr.subject.reference.split("/")[-1]
                patient = patients.get(ref_key) or patients.get(sr.subject.reference)
            if not patient and patients:
                # Fallback to the first patient in the bundle
                patient = next(iter(patients.values()))

            # Extract Patient Demographics
            patient_id = ""
            if patient:
                if patient.identifier:
                    patient_id = patient.identifier[0].value or ""
                if not patient_id and patient.id:
                    patient_id = patient.id

            patient_name = ""
            if patient and patient.name:
                patient_name = format_human_name_to_dicom(patient.name[0])

            dob_str = ""
            if patient and patient.birthDate:
                dob_str = str(patient.birthDate).replace("-", "")[:8]

            sex = ""
            if patient and patient.gender:
                g = str(patient.gender).lower().strip()
                sex = "M" if g in ("male", "m") else ("F" if g in ("female", "f") else "O")

            # 2. Extract Accession Number
            accession = ""
            if sr.identifier:
                for ident in sr.identifier:
                    if ident.value:
                        accession = ident.value
                        break
            if not accession and sr.id:
                accession = sr.id

            # 3. Check Status for Cancellation
            sr_status = (sr.status or "active").lower()
            if sr_status in ("revoked", "entered-in-error", "cancelled", "inactive"):
                cnt = self.mwl_service.remove_entry(accession=accession, patient_id=patient_id)
                removed_count += cnt
                logger.info(
                    "fhir_service_request_cancelled",
                    status=sr_status,
                    accession=accession,
                    patient_id=patient_id,
                    removed_count=cnt,
                )
                continue

            # 4. Procedure Description & Modality
            study_desc = ""
            if sr.code:
                code_obj = getattr(sr.code, "concept", None) or sr.code
                study_desc = getattr(code_obj, "text", "") or ""
                if not study_desc and getattr(code_obj, "coding", None):
                    codings = code_obj.coding or []
                    if codings and codings[0].display:
                        study_desc = codings[0].display
            if not study_desc and sr.bodySite:
                site = sr.bodySite[0]
                study_desc = getattr(site, "text", "") or ""
                if not study_desc and getattr(site, "coding", None):
                    site_coding = site.coding or []
                    if site_coding and site_coding[0].display:
                        study_desc = site_coding[0].display

            modality = self._determine_modality(sr, study_desc)
            if not study_desc:
                study_desc = f"{modality} Procedure"

            # 5. Modality Validation
            if not self.mwl_service.has_modality_template(modality):
                err_text = f"Rejected: No template images available for modality '{modality}'"
                logger.warning(
                    "fhir_modality_rejected_no_template",
                    modality=modality,
                    accession=accession,
                    patient_id=patient_id,
                    available_modalities=self.mwl_service.get_template_modalities(),
                )
                rejections.append({"accession": accession, "modality": modality, "error": err_text})
                continue

            # 6. Referring and Performing Physicians
            referring_physician = ""
            if sr.requester:
                ref_key = (sr.requester.reference or "").split("/")[-1]
                prac = practitioners.get(ref_key) or practitioners.get(sr.requester.reference or "")
                if prac and prac.name:
                    referring_physician = format_human_name_to_dicom(prac.name[0])
                elif sr.requester.display:
                    referring_physician = sr.requester.display

            performing_physician = ""
            if sr.performer:
                perf_ref = sr.performer[0]
                ref_key = (perf_ref.reference or "").split("/")[-1]
                prac = practitioners.get(ref_key) or practitioners.get(perf_ref.reference or "")
                if prac and prac.name:
                    performing_physician = format_human_name_to_dicom(prac.name[0])
                elif perf_ref.display:
                    performing_physician = perf_ref.display

            # 7. Scheduled Timing
            scheduled_at = None
            if sr.occurrenceDateTime:
                if isinstance(sr.occurrenceDateTime, datetime):
                    scheduled_at = (
                        sr.occurrenceDateTime.replace(tzinfo=None)
                        if sr.occurrenceDateTime.tzinfo
                        else sr.occurrenceDateTime
                    )
                elif hasattr(sr.occurrenceDateTime, "year"):
                    scheduled_at = datetime.combine(sr.occurrenceDateTime, datetime.min.time())
                else:
                    clean_ts = "".join(filter(str.isdigit, str(sr.occurrenceDateTime)))
                    if len(clean_ts) >= 14:
                        try:
                            scheduled_at = datetime.strptime(clean_ts[:14], "%Y%m%d%H%M%S")
                        except ValueError:
                            pass
                    elif len(clean_ts) >= 8:
                        try:
                            scheduled_at = datetime.strptime(clean_ts[:8], "%Y%m%d")
                        except ValueError:
                            pass

            reason = ""
            reason_list = getattr(sr, "reasonCode", None) or getattr(sr, "reason", None) or []
            if reason_list:
                first_reason = reason_list[0]
                reason_obj = getattr(first_reason, "concept", None) or first_reason
                reason = getattr(reason_obj, "text", "") or ""
                if not reason and getattr(reason_obj, "coding", None):
                    codings = reason_obj.coding or []
                    if codings and codings[0].display:
                        reason = codings[0].display

            # Log summary at INFO level
            logger.info(
                "fhir_service_request_received",
                status=sr_status,
                patient_id=patient_id,
                patient_name=patient_name,
                accession=accession,
                modality=modality,
                description=study_desc,
            )

            # Ingest into MWL with exact demographics
            custom_dict = {
                "patientName": patient_name,
                "patientId": patient_id,
                "mrn": patient_id,
                "dob": dob_str,
                "sex": sex,
                "gender": sex,
                "modality": modality,
                "accession": accession,
                "studyDescription": study_desc,
                "reason": reason or study_desc,
                "referringPhysician": referring_physician,
                "performingPhysician": performing_physician,
            }
            if scheduled_at:
                custom_dict["studyDate"] = scheduled_at

            entry = self.mwl_service.add_entry(custom=custom_dict, scheduled_at=scheduled_at)
            if entry:
                created_entries.append(
                    {
                        "patient_id": entry["patient_id"],
                        "patient_name": entry["patient_name"],
                        "accession": entry["accession"],
                        "modality": entry["modality"],
                        "study_uid": entry["study_uid"],
                    }
                )

        if created_entries or (removed_count and not rejections):
            status_result = "success"
        elif rejections:
            status_result = "rejected"
        else:
            status_result = "no_action"
        return {
            "status": status_result,
            "entries_created": created_entries,
            "entries_removed": removed_count,
            "rejections": rejections,
        }

    @staticmethod
    def _determine_modality(sr: Any, description: str) -> str:
        """Infer DICOM Modality from ServiceRequest codes or text."""
        tokens: list[str] = []
        code_obj = getattr(sr, "code", None)
        if hasattr(code_obj, "concept") and code_obj.concept:
            code_obj = code_obj.concept

        if code_obj and getattr(code_obj, "coding", None):
            for coding in code_obj.coding or []:
                if coding.code:
                    tokens.extend(str(coding.code).upper().replace("-", " ").replace("_", " ").split())
                if coding.display:
                    tokens.extend(str(coding.display).upper().replace("-", " ").replace("_", " ").split())
        if description:
            tokens.extend(description.upper().replace("-", " ").replace("_", " ").split())

        clean_tokens = [t.strip(".,;:()") for t in tokens]
        for m in ("PET", "PT", "MR", "CT", "US", "DX", "CR", "XA", "NM", "MG", "RF", "OT"):
            if m in clean_tokens:
                return m
            if m == "MR" and any(t in ("MRI", "MAGNETIC") or t.startswith("MR") for t in clean_tokens):
                return m
            if m == "CT" and any(t.startswith("CT") for t in clean_tokens):
                return m

        return "CT"
