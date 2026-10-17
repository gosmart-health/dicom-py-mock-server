"""Utilities for loading, filtering, and extracting DICOM-relevant data from Synthea FHIR Bundles."""

import datetime
import json
import os
from typing import Any, List, Tuple

from fhir.resources.R4B.diagnosticreport import DiagnosticReport
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.R4B.imagingstudy import ImagingStudy
from fhir.resources.R4B.procedure import Procedure

from dicom_py_mock_server.models import FhirBundle
from dicom_py_mock_server.models.fhir_models import (
    FhirIdentifier,
    FhirOrganization,
    FhirPatient,
    FhirPractitioner,
    format_human_name_to_dicom,
)


class SyntheaUtils:
    """Helper class for scanning Synthea FHIR output and extracting imaging-related resources."""

    def __init__(
        self,
        synthea_output_folder: str = "../../../synthea/output/fhir",
        patient_id_system: str = "urn:oid:2.16.840.1.113883.4.3.25",
    ):
        """Initialize SyntheaUtils with the target FHIR output directory and patient ID system.

        Args:
            synthea_output_folder: Path to the directory containing Synthea FHIR Bundle JSON files.
            patient_id_system: FHIR identifier system URI used to locate the primary patient ID
                (defaults to the Massachusetts driver's license / Synthea identifier OID).
        """
        self.synthea_output_folder = synthea_output_folder
        self.patient_id_system = patient_id_system
        self._hospital_bundles: List[FhirBundle] | None = None
        self._practitioner_bundles: List[FhirBundle] | None = None

    def _load_bundles_by_prefix(self, prefix: str) -> List[FhirBundle]:
        """Load all FHIR Bundle JSON files in the Synthea output folder starting with ``prefix``.

        Args:
            prefix: Filename prefix to match (e.g., ``"hospitalInformation"`` or ``"practitionerInformation"``).

        Returns:
            List of validated ``FhirBundle`` objects matching the prefix.
        """
        bundles: List[FhirBundle] = []
        if not os.path.exists(self.synthea_output_folder):
            return bundles

        for file_name in sorted(os.listdir(self.synthea_output_folder)):
            if file_name.startswith(prefix) and file_name.endswith(".json"):
                file_path = os.path.join(self.synthea_output_folder, file_name)
                if os.path.isfile(file_path):
                    with open(file_path, "r", encoding="utf-8") as f:
                        bundle_dict = json.load(f)
                        bundles.append(FhirBundle.model_validate(bundle_dict))
        return bundles

    @staticmethod
    def _matches_reference(
        entry_full_url: str | None,
        resource_type: str,
        resource_id: str | None,
        identifiers: List[FhirIdentifier] | None,
        reference: str,
    ) -> bool:
        """Check whether a FHIR resource matches a reference string, ID, or search identifier URI.

        Supports references such as ``"urn:uuid:<id>"``, ``"<ResourceType>/<id>"``,
        ``"<ResourceType>?identifier=<system>|<value>"``, or a raw resource ID / identifier value.
        """
        if not reference:
            return True

        ref_tail = reference.rsplit("|", 1)[-1].rsplit("/", 1)[-1].removeprefix("urn:uuid:")

        if entry_full_url and reference == entry_full_url:
            return True

        if resource_id and (
            reference in (resource_id, f"{resource_type}/{resource_id}", f"urn:uuid:{resource_id}")
            or ref_tail == resource_id
            or resource_id in reference
        ):
            return True

        for ident in identifiers or []:
            if ident.value and (
                reference == ident.value
                or ref_tail == ident.value
                or (ident.system and f"{ident.system}|{ident.value}" in reference)
            ):
                return True

        return False

    def scan_synthea_output(self, modalities: List[str], max_count: int = 1000) -> List[FhirBundle]:
        """Scan the Synthea output folder for FHIR Bundle JSON files matching the given modalities.

        Args:
            modalities: List of DICOM modality codes (e.g., ``["CT", "CR", "US"]``) to filter by.
            max_count: Maximum number of patient JSON files to inspect from the output directory.

        Returns:
            List of validated ``FhirBundle`` objects that contain at least one matching ``ImagingStudy``.
        """
        filtered_bundles: List[FhirBundle] = []
        if not os.path.exists(self.synthea_output_folder):
            return filtered_bundles

        count = 0
        for file_name in sorted(os.listdir(self.synthea_output_folder)):
            if count >= max_count:
                break
            if not file_name.endswith(".json") or file_name.startswith(
                ("hospitalInformation", "practitionerInformation")
            ):
                continue
            file_path = os.path.join(self.synthea_output_folder, file_name)
            bundle = self.load_synthea_bundle(file_path, modalities)
            if bundle:
                filtered_bundles.append(bundle)
            count += 1

        return filtered_bundles

    def load_synthea_bundle(self, file_name: str, modalities: List[str]) -> FhirBundle | None:
        """Load and validate a single Synthea FHIR Bundle JSON file if it matches the target modalities.

        Args:
            file_name: Path to the FHIR Bundle JSON file.
            modalities: List of DICOM modality codes to filter the bundle against.

        Returns:
            The validated ``FhirBundle`` if it contains a matching ``ImagingStudy``, or ``None``
            if the file does not exist, is not a JSON file, or does not match the filter criteria.
        """
        if not os.path.exists(file_name) or not os.path.isfile(file_name) or not file_name.endswith(".json"):
            return None

        with open(file_name, "r", encoding="utf-8") as f:
            bundle_dict = json.load(f)
            raw_bundle = FhirBundle.model_validate(bundle_dict)
            return self.filter_imaging_bundle(raw_bundle, modalities)

    def filter_imaging_bundle(self, bundle: FhirBundle, modalities: List[str]) -> FhirBundle | None:
        """Check whether a FHIR Bundle contains an ImagingStudy with any of the specified modalities.

        Args:
            bundle: The ``FhirBundle`` instance to inspect.
            modalities: List of DICOM modality codes (e.g., ``["CT", "US"]``) to match against
                each ``ImagingStudy`` series.

        Returns:
            The original ``FhirBundle`` if at least one ``ImagingStudy`` series matches a modality
            in ``modalities``; otherwise ``None``.
        """
        if not bundle or not isinstance(bundle, FhirBundle):
            return None

        for entry in bundle.entry or []:
            study = entry.resource
            if isinstance(study, ImagingStudy):
                for s in study.series or []:
                    if s.modality and s.modality.code in modalities:
                        return bundle

        return None

    def get_patient(self, bundle: FhirBundle) -> FhirPatient | None:
        """Extract the first Patient resource from the given FHIR Bundle.

        Args:
            bundle: The ``FhirBundle`` to search.

        Returns:
            The ``FhirPatient`` resource if found, or ``None`` otherwise.
        """
        if not bundle or not isinstance(bundle, FhirBundle):
            return None

        for entry in bundle.entry or []:
            resource = entry.resource
            if isinstance(resource, FhirPatient):
                return resource

        return None

    def get_patient_id(self, patient: FhirPatient) -> str | None:
        """Extract the patient identifier value matching the configured identifier system.

        Args:
            patient: The ``FhirPatient`` resource to inspect.

        Returns:
            The identifier value string matching ``self.patient_id_system``, or ``None`` if not found.
        """
        if not patient or not isinstance(patient, FhirPatient):
            return None

        for identifier in patient.identifier or []:
            if identifier.system == self.patient_id_system:
                return identifier.value

        return None

    def get_patient_name(self, patient: FhirPatient) -> str | None:
        """Format the primary patient name into DICOM Person Name (PN) format.

        Args:
            patient: The ``FhirPatient`` resource to inspect.

        Returns:
            The patient's first listed name formatted as ``Last^First^Middle^Prefix^Suffix``,
            or ``None`` if the patient has no name entries.
        """
        if not patient or not isinstance(patient, FhirPatient):
            return None

        if patient.name and len(patient.name) > 0:
            return format_human_name_to_dicom(patient.name[0])
        return None

    def get_patient_sex(self, patient: FhirPatient) -> str | None:
        """Map the FHIR Patient administrative gender to a DICOM PatientSex code.

        Args:
            patient: The ``FhirPatient`` resource to inspect.

        Returns:
            ``"M"`` for male, ``"F"`` for female, ``"O"`` for other, or ``None`` if unknown/unmapped.
        """
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

    def get_date_time(self, date_time: datetime.datetime | datetime.date | Any | None) -> Tuple[str, str] | None:
        """Convert a Python ``date`` or ``datetime`` object into DICOM Date (DA) and Time (TM) strings.

        Args:
            date_time: A ``datetime.datetime`` or ``datetime.date`` value to format.

        Returns:
            A tuple of ``(YYYYMMDD, HHMMSS)`` for ``datetime.datetime`` inputs, ``(YYYYMMDD, "")``
            for ``datetime.date`` inputs, or ``None`` if ``date_time`` is neither.
        """
        match date_time:
            case datetime.datetime() as dt:
                # Convert dt as DICOM date yyyymmdd and hhmmss tuple
                return dt.strftime("%Y%m%d"), dt.strftime("%H%M%S")
            case datetime.date() as date:
                # Convert Date part as DICOM data yyyymmdd and time part as empty.
                return date.strftime("%Y%m%d"), ""
        return None

    def get_encounters(self, bundle: FhirBundle, encounter_ref: str = "") -> List[Encounter]:
        """Retrieve Encounter resources from a FHIR Bundle, optionally filtered by encounter reference.

        Args:
            bundle: The ``FhirBundle`` to search.
            encounter_ref: Optional encounter reference string (e.g., ``"urn:uuid:<id>"`` or
                ``"Encounter/<id>"``). When provided, only matching encounters are returned.

        Returns:
            List of matching ``Encounter`` resources.
        """
        encounters: List[Encounter] = []
        if not bundle or not isinstance(bundle, FhirBundle):
            return encounters

        for entry in bundle.entry or []:
            encounter = entry.resource
            if isinstance(encounter, Encounter):
                if encounter_ref:
                    if encounter_ref in (
                        entry.fullUrl,
                        f"Encounter/{encounter.id}",
                        encounter.id,
                    ) or (encounter.id and encounter.id in encounter_ref):
                        encounters.append(encounter)
                else:
                    encounters.append(encounter)
        return encounters

    def get_imaging_studies(self, bundle: FhirBundle, modalities: List[str] | None = None) -> List[ImagingStudy]:
        """Retrieve ImagingStudy resources from a FHIR Bundle that match the specified modalities.

        Args:
            bundle: The ``FhirBundle`` to search.
            modalities: Optional list of DICOM modality codes to filter by. Defaults to
                ``["CT", "CR", "US"]`` when omitted or empty.

        Returns:
            List of matching ``ImagingStudy`` resources.
        """
        imaging_studies: List[ImagingStudy] = []
        if not bundle or not isinstance(bundle, FhirBundle):
            return imaging_studies
        if not modalities:
            modalities = ["CT", "CR", "US"]

        for entry in bundle.entry or []:
            study = entry.resource
            if isinstance(study, ImagingStudy):
                for s in study.series or []:
                    if s.modality and s.modality.code in modalities:
                        imaging_studies.append(study)
                        break
        return imaging_studies

    def get_diagnostic_reports(self, bundle: FhirBundle, encounter_ref: str = "") -> List[DiagnosticReport]:
        """Retrieve DiagnosticReport resources from a FHIR Bundle, optionally filtered by encounter.

        Args:
            bundle: The ``FhirBundle`` to search.
            encounter_ref: Optional encounter reference string. When provided, only reports whose
                ``encounter.reference`` equals ``encounter_ref`` are returned.

        Returns:
            List of matching ``DiagnosticReport`` resources.
        """
        diagnostic_reports: List[DiagnosticReport] = []
        if not bundle or not isinstance(bundle, FhirBundle):
            return diagnostic_reports

        for entry in bundle.entry or []:
            report = entry.resource
            if isinstance(report, DiagnosticReport):
                report_encounter_ref = report.encounter.reference if report.encounter else None
                if encounter_ref:
                    if encounter_ref == report_encounter_ref:
                        diagnostic_reports.append(report)
                else:
                    diagnostic_reports.append(report)

        return diagnostic_reports

    def get_procedures(self, bundle: FhirBundle, encounter_ref: str = "") -> List[Procedure]:
        """Retrieve Procedure resources from a FHIR Bundle, optionally filtered by encounter.

        Args:
            bundle: The ``FhirBundle`` to search.
            encounter_ref: Optional encounter reference string. When provided, only procedures whose
                ``encounter.reference`` equals ``encounter_ref`` are returned.

        Returns:
            List of matching ``Procedure`` resources.
        """
        procedures: List[Procedure] = []
        if not bundle or not isinstance(bundle, FhirBundle):
            return procedures
        for entry in bundle.entry or []:
            procedure = entry.resource
            if isinstance(procedure, Procedure):
                procedure_encounter_ref = procedure.encounter.reference if procedure.encounter else None
                if encounter_ref:
                    if encounter_ref == procedure_encounter_ref:
                        procedures.append(procedure)
                else:
                    procedures.append(procedure)
        return procedures

    def get_hospital_information(self, reference: str = "", bundle: FhirBundle | None = None) -> List[FhirOrganization]:
        """Retrieve hospital (Organization) resources from Synthea ``hospitalInformation*.json`` files and/or a Bundle.

        Args:
            reference: Optional reference string, resource ID, or identifier URI (e.g., from
                ``encounter.serviceProvider.reference`` such as
                ``"Organization?identifier=https://github.com/synthetichealth/synthea|<id>"`` or
                ``"urn:uuid:<id>"``). When omitted, all ``Organization`` resources are returned.
            bundle: Optional patient or hospital ``FhirBundle`` to search in addition to the
                ``hospitalInformation*.json`` files in ``self.synthea_output_folder``.

        Returns:
            List of matching ``FhirOrganization`` (``Organization``) resources.
        """
        if self._hospital_bundles is None:
            self._hospital_bundles = self._load_bundles_by_prefix("hospitalInformation")

        source_bundles: List[FhirBundle] = []
        if bundle and isinstance(bundle, FhirBundle):
            source_bundles.append(bundle)
        source_bundles.extend(self._hospital_bundles)

        organizations: List[FhirOrganization] = []
        seen_ids: set[str] = set()

        for src_bundle in source_bundles:
            for entry in src_bundle.entry or []:
                org = entry.resource
                if isinstance(org, FhirOrganization):
                    if self._matches_reference(entry.fullUrl, "Organization", org.id, org.identifier, reference):
                        if org.id:
                            if org.id in seen_ids:
                                continue
                            seen_ids.add(org.id)
                        organizations.append(org)

        return organizations

    def get_practitioner_information(
        self, reference: str = "", bundle: FhirBundle | None = None
    ) -> List[FhirPractitioner]:
        """Retrieve Practitioner resources from Synthea ``practitionerInformation*.json`` files and/or a Bundle.

        Args:
            reference: Optional reference string, resource ID, or identifier URI (e.g., from
                ``encounter.participant[0].individual.reference`` such as
                ``"Practitioner?identifier=http://hl7.org/fhir/sid/us-npi|<npi>"`` or
                ``"urn:uuid:<id>"``). When omitted, all ``Practitioner`` resources are returned.
            bundle: Optional patient or practitioner ``FhirBundle`` to search in addition to the
                ``practitionerInformation*.json`` files in ``self.synthea_output_folder``.

        Returns:
            List of matching ``FhirPractitioner`` (``Practitioner``) resources.
        """
        if self._practitioner_bundles is None:
            self._practitioner_bundles = self._load_bundles_by_prefix("practitionerInformation")

        source_bundles: List[FhirBundle] = []
        if bundle and isinstance(bundle, FhirBundle):
            source_bundles.append(bundle)
        source_bundles.extend(self._practitioner_bundles)

        practitioners: List[FhirPractitioner] = []
        seen_ids: set[str] = set()

        for src_bundle in source_bundles:
            for entry in src_bundle.entry or []:
                practitioner = entry.resource
                if isinstance(practitioner, FhirPractitioner):
                    if self._matches_reference(
                        entry.fullUrl, "Practitioner", practitioner.id, practitioner.identifier, reference
                    ):
                        if practitioner.id:
                            if practitioner.id in seen_ids:
                                continue
                            seen_ids.add(practitioner.id)
                        practitioners.append(practitioner)

        return practitioners

    def get_practioner_information(
        self, reference: str = "", bundle: FhirBundle | None = None
    ) -> List[FhirPractitioner]:
        """Alias for :meth:`get_practitioner_information`."""
        return self.get_practitioner_information(reference=reference, bundle=bundle)
