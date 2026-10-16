import datetime
import json
import os
from typing import List, Tuple

from fhir.resources.R4B.diagnosticreport import DiagnosticReport
from fhir.resources.R4B.encounter import Encounter

# from fhir.resources.R4B.explanationofbenefit import ExplanationOfBenefit
from fhir.resources.R4B.imagingstudy import ImagingStudy

from dicom_py_mock_server.models import FhirBundle
from dicom_py_mock_server.models.fhir_models import FhirPatient, format_human_name_to_dicom


class SyntheaUtils:
    def __init__(
        self,
        synthea_output_folder: str = "../../../synthea/output/fhir",
        patient_id_system: str = "urn:oid:2.16.840.1.113883.4.3.25",
    ):
        self.synthea_output_folder = synthea_output_folder
        self.get_patient_id_system = patient_id_system

    def scan_synthea_output(self, modalities: List[str], max_count: int = 1000) -> List[FhirBundle]:
        """Scan Synthea output for FHIR Bundle JSON files and return matching bundles."""
        filtered_bundles = []
        if not os.path.exists(self.synthea_output_folder):
            return filtered_bundles

        count = 0
        for file_name in os.listdir(self.synthea_output_folder):
            if count >= max_count:
                break
            if file_name.endswith(".json"):
                file_path = os.path.join(self.synthea_output_folder, file_name)
                bundle = self.load_synthea_bundle(file_path, modalities)
                if bundle:
                    filtered_bundles.append(bundle)
                count += 1

        return filtered_bundles

    def load_synthea_bundle(self, file_name: str, modalities: List[str]) -> FhirBundle | None:
        if not os.path.exists(file_name) or not os.path.isfile(file_name) or not file_name.endswith(".json"):
            return None

        with open(file_name, "r") as f:
            bundle_dict = json.load(f)
            raw_bundle = FhirBundle.model_validate(bundle_dict)
            return self.filter_imaging_bundle(raw_bundle, modalities)

    def filter_imaging_bundle(self, bundle: FhirBundle, modalities: List[str]) -> FhirBundle | None:
        """Filter the given FHIR Bundle to only include ImagingStudy, DiagnosticReport, and Encounter resources."""
        if not bundle or not isinstance(bundle, FhirBundle):
            return None

        has_imaging_study = False

        for entry in bundle.entry:
            resource = entry.resource
            if not isinstance(resource, (ImagingStudy, DiagnosticReport, Encounter)):
                continue
            match resource:
                case ImagingStudy() as study:
                    for s in study.series:
                        if s.modality and s.modality.code in modalities:
                            has_imaging_study = True
                            break
                case DiagnosticReport():
                    # filtered_entries.append(entry)
                    pass
                case Encounter():
                    # filtered_entries.append(entry)
                    pass

        if has_imaging_study:
            return bundle
        else:
            return None

    def get_patient(self, bundle: FhirBundle) -> FhirPatient | None:
        """Get the Patient resource from the given FHIR Bundle."""
        if not bundle or not isinstance(bundle, FhirBundle):
            return None

        for entry in bundle.entry:
            resource = entry.resource
            if isinstance(resource, FhirPatient):
                return resource

        return None

    def get_patient_id(self, patient: FhirPatient) -> str | None:
        """Get the patient ID from the given FHIR Patient resource."""
        if not patient or not isinstance(patient, FhirPatient):
            return None

        for identifier in patient.identifier:
            if identifier.system == self.get_patient_id_system:
                return identifier.value

        return None

    def get_patient_name(self, patient: FhirPatient) -> str | None:
        """Get the patient name from the given FHIR Patient resource."""
        if not patient or not isinstance(patient, FhirPatient):
            return None

        if patient.name and len(patient.name) > 0:
            return format_human_name_to_dicom(patient.name[0])
        return None

    def get_patient_sex(self, patient: FhirPatient) -> str | None:
        """Get the patient sex from the given FHIR Patient resource."""
        if not patient or not isinstance(patient, FhirPatient):
            return None

        match patient.gender:
            case "male":
                return "M"
            case "female":
                return "F"
            case "other":
                return "O"
            case _:
                return None

    def get_date_time(self, date_time: any) -> Tuple[str, str] | None:
        match date_time:
            case datetime.datetime() as dt:
                # Convert dt as DICOM date yyyymmdd and hhmmss tuple
                return dt.strftime("%Y%m%d"), dt.strftime("%H%M%S")
            case datetime.date() as date:
                # Convert Date part as DICOM data yyyymmdd and time part as empty.
                return date.strftime("%Y%m%d"), ""
        return None

    def get_encounters(self, bundle: FhirBundle) -> List[Encounter]:
        """Get all Encounter resources from the given FHIR Bundle."""
        encounters = []
        if not bundle or not isinstance(bundle, FhirBundle):
            return encounters

        for entry in bundle.entry:
            resource = entry.resource
            if isinstance(resource, Encounter):
                encounters.append(resource)

        return encounters

    def get_imaging_studies(self, bundle: FhirBundle, modalities: List[str] = None) -> List[ImagingStudy]:
        """Get all ImagingStudy resources from the given FHIR Bundle."""
        imaging_studies: List[ImagingStudy] = []
        if not bundle or not isinstance(bundle, FhirBundle):
            return imaging_studies
        if not modalities:
            modalities = ["CT", "CR", "US"]

        for entry in bundle.entry:
            study: ImagingStudy = entry.resource
            if isinstance(study, ImagingStudy):
                for s in study.series:
                    if s.modality and s.modality.code in modalities:
                        imaging_studies.append(study)
        return imaging_studies

    def get_diagnostic_reports(self, bundle: FhirBundle) -> List[DiagnosticReport]:
        """Get all DiagnosticReport resources from the given FHIR Bundle."""
        diagnostic_reports = []
        if not bundle or not isinstance(bundle, FhirBundle):
            return diagnostic_reports

        for entry in bundle.entry:
            resource = entry.resource
            if isinstance(resource, DiagnosticReport):
                diagnostic_reports.append(resource)

        return diagnostic_reports
