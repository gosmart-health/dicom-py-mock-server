"""Service for parsing FHIR ServiceRequest Bundles and generating DICOM MWL entries."""

from datetime import datetime
from typing import Any

import structlog

from dicom_py_mock_server.models.fhir_models import (
    FhirBundle,
    FhirPatient,
    FhirPractitioner,
    FhirServiceRequest,
)
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService

logger = structlog.get_logger(__name__)


class FhirParserService:
    """Service to parse FHIR imaging bundles into Modality Worklist (MWL) entries."""

    def __init__(self, mwl_service: MwlGeneratorService) -> None:
        self.mwl_service = mwl_service

    def process_bundle(self, bundle_data: dict[str, Any] | FhirBundle) -> dict[str, Any]:
        """Parse a FHIR bundle, update MWL active list, and return processing summary."""
        # Structured debug dump of raw payload
        logger.debug("fhir_bundle_raw_dump", raw_bundle=bundle_data)

        if isinstance(bundle_data, dict):
            bundle = FhirBundle.model_validate(bundle_data)
        else:
            bundle = bundle_data

        patients: dict[str, FhirPatient] = {}
        practitioners: dict[str, FhirPractitioner] = {}
        service_requests: list[FhirServiceRequest] = []

        # If payload itself is a single ServiceRequest resource
        if getattr(bundle, "resourceType", "") == "ServiceRequest":
            sr = FhirServiceRequest.model_validate(bundle_data)
            service_requests.append(sr)

        for entry in bundle.entry:
            res_dict = entry.resource
            if not res_dict or not isinstance(res_dict, dict):
                continue
            res_type = res_dict.get("resourceType")
            res_id = res_dict.get("id") or ""

            if res_type == "Patient":
                pat = FhirPatient.model_validate(res_dict)
                patients[res_id] = pat
                if entry.fullUrl:
                    patients[entry.fullUrl] = pat
            elif res_type == "Practitioner":
                prac = FhirPractitioner.model_validate(res_dict)
                practitioners[res_id] = prac
                if entry.fullUrl:
                    practitioners[entry.fullUrl] = prac
            elif res_type == "ServiceRequest":
                sr = FhirServiceRequest.model_validate(res_dict)
                service_requests.append(sr)

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
                patient_name = patient.name[0].to_dicom_format()
            dob_str = ""
            if patient and patient.birthDate:
                dob_str = patient.birthDate.replace("-", "")[:8]
            sex = ""
            if patient and patient.gender:
                g = patient.gender.lower().strip()
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
                study_desc = sr.code.text or (sr.code.coding[0].display if sr.code.coding else "")
            if not study_desc and sr.bodySite:
                study_desc = sr.bodySite[0].text or ""

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
                    referring_physician = prac.name[0].to_dicom_format()
                elif sr.requester.display:
                    referring_physician = sr.requester.display

            performing_physician = ""
            if sr.performer:
                perf_ref = sr.performer[0]
                ref_key = (perf_ref.reference or "").split("/")[-1]
                prac = practitioners.get(ref_key) or practitioners.get(perf_ref.reference or "")
                if prac and prac.name:
                    performing_physician = prac.name[0].to_dicom_format()
                elif perf_ref.display:
                    performing_physician = perf_ref.display

            # 7. Scheduled Timing
            scheduled_at = None
            if sr.occurrenceDateTime:
                clean_ts = "".join(filter(str.isdigit, sr.occurrenceDateTime))
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
            if sr.reasonCode:
                coding_display = sr.reasonCode[0].coding[0].display if sr.reasonCode[0].coding else ""
                reason = sr.reasonCode[0].text or coding_display

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
    def _determine_modality(sr: FhirServiceRequest, description: str) -> str:
        """Infer DICOM Modality from ServiceRequest codes or text."""
        tokens: list[str] = []
        if sr.code and sr.code.coding:
            for coding in sr.code.coding:
                if coding.code:
                    tokens.extend(coding.code.upper().replace("-", " ").replace("_", " ").split())
                if coding.display:
                    tokens.extend(coding.display.upper().replace("-", " ").replace("_", " ").split())
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
