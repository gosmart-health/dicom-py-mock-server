"""Utilities for loading, filtering, and extracting DICOM-relevant data from Synthea FHIR Bundles."""

import datetime
import json
import os
import urllib.parse
from typing import Any, List, Tuple

from fhir.resources.R4B.diagnosticreport import DiagnosticReport
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.R4B.imagingstudy import ImagingStudy
from fhir.resources.R4B.procedure import Procedure

from dicom_py_mock_server.config import config
from dicom_py_mock_server.logging_config import get_logger
from dicom_py_mock_server.models import FhirBundle
from dicom_py_mock_server.models.dicom import (
    MockDicomRequest,
    MockDicomResponse,
    PatientModel,
    SeriesModel,
    StudyModel,
)
from dicom_py_mock_server.models.fhir_models import (
    FhirIdentifier,
    FhirOrganization,
    FhirPatient,
    FhirPractitioner,
    format_human_name_to_dicom,
)
from dicom_py_mock_server.services.person_generator import PersonGenerator
from dicom_py_mock_server.services.uid_generator import (
    generate_series_uid,
    generate_sop_instance_uid,
    generate_study_uid,
)

logger = get_logger(__name__)


class SyntheaUtils:
    """Helper class for scanning Synthea FHIR output and extracting imaging-related resources."""

    def __init__(
        self,
        synthea_output_folder: str = "../../../synthea/output/fhir",
        patient_id_system: str = "urn:oid:2.16.840.1.113883.4.3.25",
        modalities: List[str] | None = None,
        mwl_service: Any | None = None,
    ):
        """Initialize SyntheaUtils with the target FHIR output directory, patient ID system, and modalities.

        Args:
            synthea_output_folder: Path to the directory containing Synthea FHIR Bundle JSON files.
            patient_id_system: FHIR identifier system URI used to locate the primary patient ID
                (defaults to the Massachusetts driver's license / Synthea identifier OID).
            modalities: Optional list of DICOM modality codes to filter by (defaults to ``["CT", "US", "CR"]``).
            mwl_service: Optional ``MwlGeneratorService`` instance to register Patient-Study-Series records into.
        """
        self.synthea_output_folder = synthea_output_folder
        self.patient_id_system = patient_id_system
        self.mwl_service = mwl_service
        if self.mwl_service is not None:
            self.mwl_service.synthea_utils = self
        self._hospital_bundles: List[FhirBundle] | None = None
        self._practitioner_bundles: List[FhirBundle] | None = None
        self._patients: List[PatientModel] = []
        self._studies: List[StudyModel] = []
        self._series: List[SeriesModel] = []
        self._patient_study_series_records: List[dict[str, Any]] = []
        self._study_accessions: dict[str, str] = {}
        self.__patient_bundles: List[FhirBundle] | None = None
        self._modalities = modalities if modalities else ["CT", "US", "CR"]

    @property
    def _patient_bundles(self) -> List[FhirBundle] | None:
        """Return cached patient bundles."""
        return self.__patient_bundles

    @_patient_bundles.setter
    def _patient_bundles(self, value: List[FhirBundle] | None) -> None:
        """Set or reset cached patient bundles and clear derived patient/study/series lists when reset."""
        self.__patient_bundles = value
        if not value:
            self._patients = []
            self._studies = []
            self._series = []
            self._patient_study_series_records = []
            self._study_accessions = {}
            if self.mwl_service is not None and hasattr(self.mwl_service, "_synthea_entries"):
                self.mwl_service._synthea_entries.clear()

    @property
    def modalities(self) -> List[str]:
        """Return the configured DICOM modalities for filtering."""
        return self._modalities

    @property
    def patients(self) -> List[PatientModel]:
        """Return the list of extracted PatientModel instances from loaded patient bundles."""
        return list(self._patients)

    @property
    def studies(self) -> List[StudyModel]:
        """Return the list of extracted StudyModel instances from loaded patient bundles."""
        return list(self._studies)

    @property
    def series(self) -> List[SeriesModel]:
        """Return the list of extracted SeriesModel instances from loaded patient bundles."""
        return list(self._series)

    @property
    def patient_study_series_records(self) -> List[dict[str, Any]]:
        """Return the list of extracted patient-study-series records for C-FIND and DICOMweb."""
        return list(self._patient_study_series_records)

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

    def _get_effective_bundles(self, bundle: FhirBundle | None) -> List[FhirBundle]:
        """Resolve the effective bundle list, falling back to ``self._patient_bundles``.

        Args:
            bundle: Optional ``FhirBundle`` instance.

        Returns:
            A list containing ``[bundle]`` if provided and valid, or ``self._patient_bundles``.

        Raises:
            ValueError: If ``bundle`` is ``None`` and ``self._patient_bundles`` is ``None``.
        """
        if bundle is not None:
            if not isinstance(bundle, FhirBundle):
                return []
            return [bundle]
        if self._patient_bundles is None:
            raise ValueError("No FHIR bundle provided and self._patient_bundles is None.")
        return self._patient_bundles

    @staticmethod
    def parse_file_uri(uri: str) -> str:
        """Validate a ``file://`` URI and resolve it to an existing local ``.json`` file path.

        Args:
            uri: Resource location URI string (must use the ``file://`` scheme).

        Returns:
            Resolved local filesystem path to the ``.json`` file.

        Raises:
            ValueError: If the URI is empty, does not use ``file://``, points to a directory,
                does not end with ``.json``, or the file does not exist.
        """
        if not uri or not isinstance(uri, str) or not uri.strip():
            raise ValueError("Invalid URI: must be a non-empty string.")

        parsed = urllib.parse.urlparse(uri.strip())
        if parsed.scheme != "file":
            raise ValueError(f"Unsupported URI scheme '{parsed.scheme or 'none'}': only 'file://' URIs are supported.")

        if parsed.netloc in ("", "localhost"):
            raw_path = urllib.parse.unquote(parsed.path)
        else:
            raw_path = urllib.parse.unquote(f"{parsed.netloc}{parsed.path}")

        if not raw_path:
            raise ValueError(f"Invalid file URI '{uri}': empty file path.")

        file_path = os.path.abspath(raw_path)
        if os.path.isdir(file_path):
            raise ValueError(f"URI '{uri}' points to a directory, expected a .json file.")
        if not file_path.endswith(".json"):
            raise ValueError(f"URI '{uri}' must point to a .json file.")
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            raise ValueError(f"File not found for URI '{uri}': {file_path}")

        return file_path

    @staticmethod
    def load_raw_bundle(file_path: str) -> FhirBundle:
        """Load and validate a FHIR Bundle JSON file from disk without modality filtering.

        Args:
            file_path: Local filesystem path to a FHIR Bundle JSON file.

        Returns:
            Validated ``FhirBundle`` instance.

        Raises:
            ValueError: If the file cannot be parsed as a valid FHIR Bundle.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                bundle_dict = json.load(f)
            return FhirBundle.model_validate(bundle_dict)
        except Exception as exc:
            raise ValueError(f"Failed to parse FHIR Bundle from '{file_path}': {exc}") from exc

    @staticmethod
    def classify_bundle(bundle: FhirBundle, file_name: str = "") -> str:
        """Classify a Synthea FHIR Bundle as ``'hospital'``, ``'practitioner'``, ``'patient'``, or ``'unknown'``.

        Args:
            bundle: The ``FhirBundle`` to inspect.
            file_name: Optional filename hint (e.g., ``hospitalInformation*.json``).

        Returns:
            One of ``"hospital"``, ``"practitioner"``, ``"patient"``, or ``"unknown"``.
        """
        base_name = os.path.basename(file_name) if file_name else ""
        if base_name.startswith("hospitalInformation"):
            return "hospital"
        if base_name.startswith("practitionerInformation"):
            return "practitioner"

        has_org = False
        has_practitioner = False
        for entry in bundle.entry or []:
            res = entry.resource
            if isinstance(res, FhirPatient):
                return "patient"
            if isinstance(res, FhirOrganization):
                has_org = True
            elif isinstance(res, FhirPractitioner):
                has_practitioner = True

        if has_org:
            return "hospital"
        if has_practitioner:
            return "practitioner"
        return "unknown"

    @staticmethod
    def _bundle_signature(bundle: FhirBundle) -> str:
        """Compute a deterministic signature for a FHIR Bundle to avoid duplicate additive caching."""
        if bundle.id:
            return f"id:{bundle.id}"
        entries = bundle.entry or []
        if entries:
            first = entries[0]
            first_id = first.fullUrl or getattr(first.resource, "id", None) or ""
            last = entries[-1]
            last_id = last.fullUrl or getattr(last.resource, "id", None) or ""
            return f"entries:{len(entries)}:{first_id}:{last_id}"
        return f"empty:{id(bundle)}"

    def add_hospital_bundle(self, bundle: FhirBundle) -> bool:
        """Additively store a hospital ``FhirBundle`` in memory with deduplication.

        Args:
            bundle: Hospital ``FhirBundle`` containing ``Organization`` resources.

        Returns:
            ``True`` if the bundle was newly added, ``False`` if it was already present.
        """
        if self._hospital_bundles is None:
            self._hospital_bundles = []
        sig = self._bundle_signature(bundle)
        for existing in self._hospital_bundles:
            if self._bundle_signature(existing) == sig:
                return False
        self._hospital_bundles.append(bundle)
        return True

    def add_practitioner_bundle(self, bundle: FhirBundle) -> bool:
        """Additively store a practitioner ``FhirBundle`` in memory with deduplication.

        Args:
            bundle: Practitioner ``FhirBundle`` containing ``Practitioner`` resources.

        Returns:
            ``True`` if the bundle was newly added, ``False`` if it was already present.
        """
        if self._practitioner_bundles is None:
            self._practitioner_bundles = []
        sig = self._bundle_signature(bundle)
        for existing in self._practitioner_bundles:
            if self._bundle_signature(existing) == sig:
                return False
        self._practitioner_bundles.append(bundle)
        return True

    def add_patient_bundle(self, bundle: FhirBundle, mwl_service: Any | None = None) -> bool:
        """Additively store a patient ``FhirBundle`` in memory with deduplication by patient ID or signature.

        Also extracts and registers the corresponding ``PatientModel``, ``StudyModel``, ``SeriesModel``,
        and patient-study-series records for C-FIND and DICOMweb queries.

        Args:
            bundle: Patient ``FhirBundle`` to cache.
            mwl_service: Optional ``MwlGeneratorService`` instance to register study/series records into.

        Returns:
            ``True`` if the bundle was newly added, ``False`` if a bundle for the same patient already existed.
        """
        if self._patient_bundles is None:
            self._patient_bundles = []

        if mwl_service is not None and self.mwl_service is None:
            self.mwl_service = mwl_service
            mwl_service.synthea_utils = self

        new_patient = self.get_patient(bundle)
        new_pid = self.get_patient_id(new_patient) if new_patient else None
        new_fhir_id = new_patient.id if new_patient else None
        sig = self._bundle_signature(bundle)

        for existing in self._patient_bundles:
            if self._bundle_signature(existing) == sig:
                return False
            existing_patient = self.get_patient(existing)
            if existing_patient:
                if new_pid and self.get_patient_id(existing_patient) == new_pid:
                    return False
                if new_fhir_id and existing_patient.id == new_fhir_id:
                    return False

        self._patient_bundles.append(bundle)
        self._extract_and_register_patient_bundle(
            bundle,
            mwl_service=mwl_service or self.mwl_service,
            create_mwl_entries=False,
        )
        return True

    def has_hospital_info(self) -> bool:
        """Return whether hospital bundles have been loaded into memory."""
        return bool(self._hospital_bundles)

    def has_practitioner_info(self) -> bool:
        """Return whether practitioner bundles have been loaded into memory."""
        return bool(self._practitioner_bundles)

    def has_hospital_and_practitioner_info(self) -> bool:
        """Return whether both hospital and practitioner bundles have been loaded into memory."""
        return self.has_hospital_info() and self.has_practitioner_info()

    def load_synthea_uri(self, uri: str) -> Tuple[str, FhirBundle | None]:
        """Validate and load a Synthea FHIR Bundle from a ``file://`` URI additively into memory.

        Hospital and practitioner bundles are added to ``_hospital_bundles`` and
        ``_practitioner_bundles`` respectively. Patient bundles are filtered by
        ``self.modalities``; if a patient bundle has no matching ``ImagingStudy``,
        a warning is logged and ``("patient", None)`` is returned.

        Args:
            uri: ``file://`` URI pointing to a Synthea FHIR Bundle JSON file.

        Returns:
            A tuple of ``(bundle_type, bundle_or_none)`` where ``bundle_type`` is
            ``"hospital"``, ``"practitioner"``, ``"patient"``, or ``"unknown"``.

        Raises:
            ValueError: If the URI is invalid, not ``file://``, not a ``.json`` file,
                does not exist, or fails FHIR Bundle validation.
        """
        file_path = self.parse_file_uri(uri)
        raw_bundle = self.load_raw_bundle(file_path)
        bundle_type = self.classify_bundle(raw_bundle, os.path.basename(file_path))

        if bundle_type == "hospital":
            self.add_hospital_bundle(raw_bundle)
            logger.info("synthea_hospital_bundle_loaded", uri=uri, file_path=file_path)
            return "hospital", raw_bundle

        if bundle_type == "practitioner":
            self.add_practitioner_bundle(raw_bundle)
            logger.info("synthea_practitioner_bundle_loaded", uri=uri, file_path=file_path)
            return "practitioner", raw_bundle

        if bundle_type == "patient":
            filtered = self.filter_imaging_bundle(raw_bundle)
            if filtered is None:
                logger.warning(
                    "synthea_bundle_no_supported_imaging_study",
                    uri=uri,
                    file_path=file_path,
                    modalities=self._modalities,
                )
                return "patient", None
            self.add_patient_bundle(filtered)
            logger.info("synthea_patient_bundle_loaded", uri=uri, file_path=file_path)
            return "patient", filtered

        logger.warning("synthea_bundle_unrecognized_type", uri=uri, file_path=file_path)
        return "unknown", None

    def scan_synthea_output(self, max_count: int = 1000) -> List[FhirBundle]:
        """Scan the Synthea output folder for FHIR Bundle JSON files matching the configured modalities.

        Args:
            max_count: Maximum number of patient JSON files to inspect from the output directory.

        Returns:
            List of validated ``FhirBundle`` objects that contain at least one matching ``ImagingStudy``.
        """
        filtered_bundles: List[FhirBundle] = []
        if not os.path.exists(self.synthea_output_folder):
            return filtered_bundles

        if self._patient_bundles is None:
            self._patient_bundles = []

        count = 0
        for file_name in sorted(os.listdir(self.synthea_output_folder)):
            if count >= max_count:
                break
            if not file_name.endswith(".json") or file_name.startswith(
                ("hospitalInformation", "practitionerInformation")
            ):
                continue
            file_path = os.path.join(self.synthea_output_folder, file_name)
            bundle = self.load_synthea_bundle(file_path)
            if bundle:
                filtered_bundles.append(bundle)
                self.add_patient_bundle(bundle)
            count += 1
        return filtered_bundles

    def load_synthea_bundle(self, file_name: str) -> FhirBundle | None:
        """Load and validate a single Synthea FHIR Bundle JSON file if it matches the configured modalities.

        Args:
            file_name: Path to the FHIR Bundle JSON file.

        Returns:
            The validated ``FhirBundle`` if it contains a matching ``ImagingStudy``, or ``None``
            if the file does not exist, is not a JSON file, or does not match the filter criteria.
        """
        if not os.path.exists(file_name) or not os.path.isfile(file_name) or not file_name.endswith(".json"):
            return None

        with open(file_name, "r", encoding="utf-8") as f:
            bundle_dict = json.load(f)
            raw_bundle = FhirBundle.model_validate(bundle_dict)
            return self.filter_imaging_bundle(raw_bundle)

    def filter_imaging_bundle(self, bundle: FhirBundle | None = None) -> FhirBundle | None:
        """Check whether a FHIR Bundle contains an ImagingStudy with any of the configured modalities.

        Args:
            bundle: Optional ``FhirBundle`` instance to inspect. When omitted or ``None``,
                ``self._patient_bundles`` is used.

        Returns:
            The original ``FhirBundle`` if at least one ``ImagingStudy`` series matches a modality
            in ``self._modalities``; otherwise ``None``.

        Raises:
            ValueError: If ``bundle`` is ``None`` and ``self._patient_bundles`` is ``None``.
        """
        if bundle is None:
            if self._patient_bundles is None:
                raise ValueError("No FHIR bundle provided and self._patient_bundles is None.")
            for b in self._patient_bundles:
                match = self.filter_imaging_bundle(b)
                if match:
                    return match
            return None

        if not isinstance(bundle, FhirBundle):
            return None

        for entry in bundle.entry or []:
            study = entry.resource
            if isinstance(study, ImagingStudy):
                for s in study.series or []:
                    if s.modality and s.modality.code in self._modalities:
                        return bundle

        return None

    def get_patient(self, bundle: FhirBundle | None = None) -> FhirPatient | None:
        """Extract the first Patient resource from the given FHIR Bundle or cached patient bundles.

        Args:
            bundle: Optional ``FhirBundle`` to search. When omitted or ``None``,
                ``self._patient_bundles`` is used.

        Returns:
            The ``FhirPatient`` resource if found, or ``None`` otherwise.

        Raises:
            ValueError: If ``bundle`` is ``None`` and ``self._patient_bundles`` is ``None``.
        """
        bundles = self._get_effective_bundles(bundle)

        for b in bundles:
            if not b or not isinstance(b, FhirBundle):
                continue
            for entry in b.entry or []:
                resource = entry.resource
                if isinstance(resource, FhirPatient):
                    return resource

        return None

    def get_patient_id(self, patient: FhirPatient) -> str | None:
        """Extract the patient identifier value matching the configured identifier system, with fallbacks.

        Checks ``self.patient_id_system`` first (defaults to driver's license OID), then falls
        back to the Medical Record Number (``http://hospital.smarthealthit.org``), and finally
        ``patient.id``.

        Args:
            patient: The ``FhirPatient`` resource to inspect.

        Returns:
            The identifier value string or ``patient.id``, or ``None`` if not found.
        """
        if not patient or not isinstance(patient, FhirPatient):
            return None

        for identifier in patient.identifier or []:
            if identifier.system == self.patient_id_system and identifier.value:
                return identifier.value

        for identifier in patient.identifier or []:
            if identifier.system == "http://hospital.smarthealthit.org" and identifier.value:
                return identifier.value

        return patient.id

    def get_patient_bundle_by_id(self, patient_id: str) -> FhirBundle | None:
        """Look up a cached patient ``FhirBundle`` by primary patient ID, MRN, identifier, or FHIR ``Patient.id``.

        Args:
            patient_id: The patient identifier value to search for.

        Returns:
            The matching ``FhirBundle`` from ``self._patient_bundles``, or ``None`` if not found.
        """
        if not patient_id or not self._patient_bundles:
            return None

        target = patient_id.strip()
        if not target:
            return None

        for bundle in self._patient_bundles:
            patient = self.get_patient(bundle)
            if not patient:
                continue
            if self.get_patient_id(patient) == target or patient.id == target:
                return bundle
            for ident in patient.identifier or []:
                if ident.value == target:
                    return bundle

        return None

    @staticmethod
    def get_patient_name(patient: FhirPatient) -> str | None:
        """Format the primary patient name into DICOM Person Name (PN) format."""
        return get_patient_name(patient)

    @staticmethod
    def get_patient_sex(patient: FhirPatient) -> str | None:
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

    @staticmethod
    def get_date_time(date_time: datetime.datetime | datetime.date | Any | None) -> Tuple[str, str] | None:
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

    def get_encounters(self, bundle: FhirBundle | None = None, encounter_ref: str = "") -> List[Encounter]:
        """Retrieve Encounter resources from a FHIR Bundle, optionally filtered by encounter reference.

        Args:
            bundle: Optional ``FhirBundle`` to search. When omitted or ``None``,
                ``self._patient_bundles`` is used.
            encounter_ref: Optional encounter reference string (e.g., ``"urn:uuid:<id>"`` or
                ``"Encounter/<id>"``). When provided, only matching encounters are returned.

        Returns:
            List of matching ``Encounter`` resources.

        Raises:
            ValueError: If ``bundle`` is ``None`` and ``self._patient_bundles`` is ``None``.
        """
        bundles = self._get_effective_bundles(bundle)

        encounters: List[Encounter] = []
        for b in bundles:
            if not b or not isinstance(b, FhirBundle):
                continue
            for entry in b.entry or []:
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

    def get_imaging_studies(self, bundle: FhirBundle | None = None) -> List[ImagingStudy]:
        """Retrieve ImagingStudy resources from a FHIR Bundle that match the configured modalities.

        Args:
            bundle: Optional ``FhirBundle`` to search. When omitted or ``None``,
                ``self._patient_bundles`` is used.

        Returns:
            List of matching ``ImagingStudy`` resources.

        Raises:
            ValueError: If ``bundle`` is ``None`` and ``self._patient_bundles`` is ``None``.
        """
        bundles = self._get_effective_bundles(bundle)

        imaging_studies: List[ImagingStudy] = []
        for b in bundles:
            if not b or not isinstance(b, FhirBundle):
                continue
            for entry in b.entry or []:
                study = entry.resource
                if isinstance(study, ImagingStudy):
                    for s in study.series or []:
                        if s.modality and s.modality.code in self._modalities:
                            imaging_studies.append(study)
                            break
        return imaging_studies

    def get_diagnostic_reports(
        self, bundle: FhirBundle | None = None, encounter_ref: str = ""
    ) -> List[DiagnosticReport]:
        """Retrieve DiagnosticReport resources from a FHIR Bundle, optionally filtered by encounter.

        Args:
            bundle: Optional ``FhirBundle`` to search. When omitted or ``None``,
                ``self._patient_bundles`` is used.
            encounter_ref: Optional encounter reference string. When provided, only reports whose
                ``encounter.reference`` equals ``encounter_ref`` are returned.

        Returns:
            List of matching ``DiagnosticReport`` resources.

        Raises:
            ValueError: If ``bundle`` is ``None`` and ``self._patient_bundles`` is ``None``.
        """
        bundles = self._get_effective_bundles(bundle)

        diagnostic_reports: List[DiagnosticReport] = []
        for b in bundles:
            if not b or not isinstance(b, FhirBundle):
                continue
            for entry in b.entry or []:
                report = entry.resource
                if isinstance(report, DiagnosticReport):
                    report_encounter_ref = report.encounter.reference if report.encounter else None
                    if encounter_ref:
                        if encounter_ref == report_encounter_ref:
                            diagnostic_reports.append(report)
                    else:
                        diagnostic_reports.append(report)

        return diagnostic_reports

    def get_procedures(self, bundle: FhirBundle | None = None, encounter_ref: str = "") -> List[Procedure]:
        """Retrieve Procedure resources from a FHIR Bundle, optionally filtered by encounter.

        Args:
            bundle: Optional ``FhirBundle`` to search. When omitted or ``None``,
                ``self._patient_bundles`` is used.
            encounter_ref: Optional encounter reference string. When provided, only procedures whose
                ``encounter.reference`` equals ``encounter_ref`` are returned.

        Returns:
            List of matching ``Procedure`` resources.

        Raises:
            ValueError: If ``bundle`` is ``None`` and ``self._patient_bundles`` is ``None``.
        """
        bundles = self._get_effective_bundles(bundle)

        procedures: List[Procedure] = []
        for b in bundles:
            if not b or not isinstance(b, FhirBundle):
                continue
            for entry in b.entry or []:
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
        if self._hospital_bundles:
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
        if self._practitioner_bundles:
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

    def _build_standalone_entry_record(self, custom_mwl: dict[str, Any]) -> dict[str, Any]:
        """Build a standalone patient-study-series entry dict when no MwlGeneratorService is attached."""
        patient_id = str(custom_mwl.get("patient_id") or f"{config.id_prefix}MOCK-PATIENT-001")
        patient_name = str(custom_mwl.get("patient_name") or "UNKNOWN^PATIENT")
        dob_str = str(custom_mwl.get("dob") or "19700101")
        sex = str(custom_mwl.get("sex") or "O")
        modality = str(custom_mwl.get("modality") or "CT")
        accession = str(custom_mwl.get("accession") or PersonGenerator.generate_random_id(8, prefix=config.id_prefix))
        study_uid = str(custom_mwl.get("study_uid") or generate_study_uid(patient_name, patient_id, accession))
        series_number = int(custom_mwl.get("series_number") or 1)
        series_uid = str(custom_mwl.get("series_uid") or generate_series_uid(study_uid, series_number))
        sop_instance_uid = generate_sop_instance_uid(series_uid, 1)
        study_date = str(custom_mwl.get("studyDate") or datetime.datetime.now().strftime("%Y%m%d"))
        study_time = str(custom_mwl.get("studyTime") or "120000")
        study_desc = str(custom_mwl.get("study_description") or f"{modality} Procedure")
        series_desc = str(custom_mwl.get("series_description") or study_desc)
        inst_name = str(custom_mwl.get("institution_name") or config.institution_name)
        ref_phys = str(custom_mwl.get("referring_physician") or "")
        perf_phys = str(custom_mwl.get("performing_physician") or ref_phys)
        num_instances = int(custom_mwl.get("num_instances") or 1)

        json_entry = {
            "00080005": {"vr": "CS", "Value": ["ISO_IR 192"]},
            "00080018": {"vr": "UI", "Value": [sop_instance_uid]},
            "00080050": {"vr": "SH", "Value": [accession]},
            "00080060": {"vr": "CS", "Value": [modality]},
            "00080080": {"vr": "LO", "Value": [inst_name]},
            "00080090": {"vr": "PN", "Value": [{"Alphabetic": ref_phys}]},
            "00081030": {"vr": "LO", "Value": [study_desc]},
            "00081040": {"vr": "LO", "Value": ["RAD"]},
            "00081050": {"vr": "PN", "Value": [{"Alphabetic": perf_phys}]},
            "00081060": {"vr": "PN", "Value": [{"Alphabetic": perf_phys}]},
            "00100010": {"vr": "PN", "Value": [{"Alphabetic": patient_name}]},
            "00100020": {"vr": "LO", "Value": [patient_id]},
            "00100030": {"vr": "DA", "Value": [dob_str]},
            "00100040": {"vr": "CS", "Value": [sex]},
            "0020000D": {"vr": "UI", "Value": [study_uid]},
            "00321032": {"vr": "PN", "Value": [{"Alphabetic": ref_phys}]},
            "00321060": {"vr": "LO", "Value": [study_desc]},
            "00380010": {"vr": "SH", "Value": [accession]},
            "00400100": {
                "vr": "SQ",
                "Value": [
                    {
                        "00080060": {"vr": "CS", "Value": [modality]},
                        "00400001": {"vr": "AE", "Value": ["ZEN_SNAP_MD"]},
                        "00400002": {"vr": "DA", "Value": [study_date]},
                        "00400003": {"vr": "TM", "Value": [study_time]},
                        "00400004": {"vr": "DA", "Value": [study_date]},
                        "00400005": {"vr": "TM", "Value": [study_time]},
                        "00400006": {"vr": "PN", "Value": [{"Alphabetic": perf_phys}]},
                        "00400007": {"vr": "LO", "Value": [study_desc]},
                        "00400009": {"vr": "SH", "Value": ["SPS01"]},
                        "00400010": {"vr": "SH", "Value": ["ZenSnapMD 4.1"]},
                    }
                ],
            },
            "00401001": {"vr": "SH", "Value": ["RP01"]},
        }

        return {
            "json_entry": json_entry,
            "dataset": None,
            "template_series": None,
            "template_dataset": None,
            "created_at": datetime.datetime.now(),
            "patient_id": patient_id,
            "patient_name": patient_name,
            "patient_birth_date": dob_str,
            "patient_sex": sex,
            "accession": accession,
            "modality": modality,
            "study_uid": study_uid,
            "study_date": study_date,
            "study_time": study_time,
            "study_description": study_desc,
            "series_uid": series_uid,
            "series_number": series_number,
            "series_description": series_desc,
            "referring_physician": ref_phys,
            "performing_physician": perf_phys,
            "reading_physician": perf_phys,
            "institution_name": inst_name,
            "num_instances": num_instances,
            "transfer_syntax": None,
        }

    def _extract_and_register_patient_bundle(
        self,
        bundle: FhirBundle,
        mwl_service: Any | None = None,
        create_mwl_entries: bool = False,
    ) -> Tuple[PatientModel, List[StudyModel], List[SeriesModel], List[dict[str, Any]]]:
        """Extract Patient, Study, and Series models and records from a patient bundle and register them."""
        effective_mwl = mwl_service or self.mwl_service
        if mwl_service is not None and self.mwl_service is None:
            self.mwl_service = mwl_service
            mwl_service.synthea_utils = self

        patient = self.get_patient(bundle)
        patient_id = (self.get_patient_id(patient) if patient else None) or f"{config.id_prefix}MOCK-PATIENT-001"
        patient_name = (self.get_patient_name(patient) if patient else None) or "UNKNOWN^PATIENT"
        dob_tuple = self.get_date_time(patient.birthDate) if (patient and patient.birthDate) else None
        patient_birth_date = dob_tuple[0] if dob_tuple and dob_tuple[0] else "19700101"
        patient_sex = (self.get_patient_sex(patient) if patient else None) or "O"

        patient_model = PatientModel(
            patient_id=patient_id,
            patient_name=patient_name,
            patient_birth_date=patient_birth_date,
            patient_sex=patient_sex,
        )

        # Register or update PatientModel in self._patients
        replaced_patient = False
        for idx, existing_p in enumerate(self._patients):
            if existing_p.patient_id == patient_id:
                self._patients[idx] = patient_model
                replaced_patient = True
                break
        if not replaced_patient:
            self._patients.append(patient_model)

        can_lookup_hospital = bool(self._hospital_bundles) or (
            bool(self.synthea_output_folder) and os.path.exists(self.synthea_output_folder)
        )
        can_lookup_practitioner = bool(self._practitioner_bundles) or (
            bool(self.synthea_output_folder) and os.path.exists(self.synthea_output_folder)
        )

        bundle_studies: List[StudyModel] = []
        bundle_series: List[SeriesModel] = []
        bundle_records: List[dict[str, Any]] = []

        for imaging in self.get_imaging_studies(bundle):
            raw_study_uid: str | None = None
            if imaging.identifier and len(imaging.identifier) > 0 and imaging.identifier[0].value:
                raw_study_uid = str(imaging.identifier[0].value).removeprefix("urn:oid:").strip() or None

            study_key = raw_study_uid or getattr(imaging, "id", None) or f"{patient_id}:study"
            if study_key not in self._study_accessions:
                self._study_accessions[study_key] = PersonGenerator.generate_random_id(8, prefix=config.id_prefix)
            study_accession = self._study_accessions[study_key]

            study_uid = raw_study_uid or generate_study_uid(patient_name, patient_id, study_accession)

            enc_ref = imaging.encounter.reference if imaging.encounter and imaging.encounter.reference else ""
            encounters = self.get_encounters(bundle=bundle, encounter_ref=enc_ref) if enc_ref else []
            encounter = encounters[0] if encounters else None

            proc_text: str | None = None
            if imaging.procedureCode and len(imaging.procedureCode) > 0:
                first_proc = imaging.procedureCode[0]
                proc_text = getattr(first_proc, "text", None)
                if not proc_text and getattr(first_proc, "coding", None) and len(first_proc.coding) > 0:
                    proc_text = first_proc.coding[0].display

            reason_text: str | None = None
            if encounter and encounter.reasonCode and len(encounter.reasonCode) > 0:
                first_reason = encounter.reasonCode[0]
                reason_text = getattr(first_reason, "text", None)
                if not reason_text and getattr(first_reason, "coding", None) and len(first_reason.coding) > 0:
                    reason_text = first_reason.coding[0].display

            study_description = proc_text or reason_text

            institution_name: str | None = None
            if can_lookup_hospital and encounter and encounter.serviceProvider and encounter.serviceProvider.reference:
                orgs = self.get_hospital_information(reference=encounter.serviceProvider.reference, bundle=bundle)
                if orgs and orgs[0].name:
                    institution_name = orgs[0].name
            if not institution_name and imaging.location and imaging.location.display:
                institution_name = imaging.location.display
            if not institution_name and encounter and encounter.serviceProvider and encounter.serviceProvider.display:
                institution_name = encounter.serviceProvider.display
            if not institution_name:
                institution_name = config.institution_name

            physician_pn: str | None = None
            if encounter and encounter.participant and len(encounter.participant) > 0:
                part = encounter.participant[0]
                if part.individual:
                    if can_lookup_practitioner and part.individual.reference:
                        pracs = self.get_practitioner_information(reference=part.individual.reference, bundle=bundle)
                        if pracs and pracs[0].name and len(pracs[0].name) > 0:
                            physician_pn = format_human_name_to_dicom(pracs[0].name[0])
                    if not physician_pn and part.individual.display:
                        physician_pn = part.individual.display

            referring_physician_name = physician_pn
            performing_physician_name = physician_pn

            study_model_added_for_imaging = False
            for s in imaging.series or []:
                modality = s.modality.code if (s.modality and s.modality.code) else None
                if not modality or modality not in self._modalities:
                    continue

                raw_dt = (
                    getattr(s, "started", None)
                    or getattr(imaging, "started", None)
                    or (encounter.period.start if (encounter and encounter.period) else None)
                )
                dt_tuple = self.get_date_time(raw_dt) if raw_dt else None
                study_date = dt_tuple[0] if (dt_tuple and dt_tuple[0]) else datetime.datetime.now().strftime("%Y%m%d")
                study_time = dt_tuple[1] if (dt_tuple and dt_tuple[1]) else "120000"

                series_uid = str(s.uid).removeprefix("urn:oid:").strip() if getattr(s, "uid", None) else None
                series_number = int(s.number) if getattr(s, "number", None) is not None else 1
                raw_instances = getattr(s, "numberOfInstances", None) or (
                    len(s.instance) if getattr(s, "instance", None) else 1
                )
                num_instances = max(1, min(1024, int(raw_instances)))

                effective_study_desc = study_description or f"{modality} Procedure"
                series_description = (
                    (s.bodySite.display if (getattr(s, "bodySite", None) and s.bodySite.display) else None)
                    or (
                        s.instance[0].title
                        if (getattr(s, "instance", None) and len(s.instance) > 0 and s.instance[0].title)
                        else None
                    )
                    or effective_study_desc
                )

                custom_mwl: dict[str, Any] = {
                    "patient_name": patient_name,
                    "patient_id": patient_id,
                    "dob": patient_birth_date,
                    "sex": patient_sex,
                    "modality": modality,
                    "accession": study_accession,
                    "study_uid": study_uid,
                    "series_uid": series_uid,
                    "series_number": series_number,
                    "series_description": series_description,
                    "study_description": effective_study_desc,
                    "reason": reason_text or effective_study_desc,
                    "institution_name": institution_name,
                    "referring_physician": referring_physician_name,
                    "performing_physician": performing_physician_name,
                    "num_instances": num_instances,
                    "studyDate": study_date,
                    "studyTime": study_time,
                }

                study_record: dict[str, Any] | None = None
                if effective_mwl is not None:
                    if create_mwl_entries:
                        mwl_record = effective_mwl.add_entry(custom=custom_mwl)
                        if mwl_record is not None:
                            effective_mwl.register_synthea_entry(mwl_record)
                            study_record = mwl_record
                        else:
                            study_record = effective_mwl.register_study_series_entry(custom=custom_mwl)
                    else:
                        study_record = effective_mwl.register_study_series_entry(custom=custom_mwl)

                if study_record is None:
                    study_record = self._build_standalone_entry_record(custom_mwl)

                accession_number = study_record["accession"]
                self._study_accessions[study_key] = accession_number
                final_study_uid = study_record["study_uid"]
                final_series_uid = study_record["series_uid"]

                study_model = StudyModel(
                    study_instance_uid=final_study_uid,
                    study_date=study_date,
                    study_time=study_time,
                    accession_number=accession_number,
                    study_description=effective_study_desc,
                    institution_name=institution_name,
                    referring_physician_name=referring_physician_name,
                    performing_physician_name=performing_physician_name,
                )
                series_model = SeriesModel(
                    series_instance_uid=final_series_uid,
                    modality=modality,
                    series_number=series_number,
                    series_description=series_description,
                    performing_physician_name=performing_physician_name,
                )

                if not study_model_added_for_imaging:
                    bundle_studies.append(study_model)
                    study_model_added_for_imaging = True
                    replaced_st = False
                    for idx, existing_st in enumerate(self._studies):
                        if existing_st.study_instance_uid == final_study_uid:
                            self._studies[idx] = study_model
                            replaced_st = True
                            break
                    if not replaced_st:
                        self._studies.append(study_model)

                bundle_series.append(series_model)
                replaced_ser = False
                for idx, existing_ser in enumerate(self._series):
                    if existing_ser.series_instance_uid == final_series_uid:
                        self._series[idx] = series_model
                        replaced_ser = True
                        break
                if not replaced_ser:
                    self._series.append(series_model)

                bundle_records.append(study_record)
                replaced_rec = False
                for idx, existing_rec in enumerate(self._patient_study_series_records):
                    if str(existing_rec.get("study_uid", "")) == str(final_study_uid) and str(
                        existing_rec.get("series_uid", "")
                    ) == str(final_series_uid):
                        self._patient_study_series_records[idx] = study_record
                        replaced_rec = True
                        break
                if not replaced_rec:
                    self._patient_study_series_records.append(study_record)

        return patient_model, bundle_studies, bundle_series, bundle_records

    def get_patients(
        self,
        bundle: FhirBundle | None = None,
        patient_id: str | None = None,
        patient_name: str | None = None,
    ) -> List[PatientModel]:
        """Retrieve ``PatientModel`` objects extracted from the given FHIR Bundle or cached patient bundles.

        Args:
            bundle: Optional ``FhirBundle`` to extract from. When omitted or ``None``,
                ``self._patient_bundles`` is used.
            patient_id: Optional ``PatientID`` filter.
            patient_name: Optional ``PatientName`` filter (supports wildcards).

        Returns:
            List of ``PatientModel`` objects.
        """
        if bundle is None and self._patient_bundles is None:
            if self.synthea_output_folder and os.path.exists(self.synthea_output_folder):
                self.load_all_bundles()
            else:
                return []

        bundles = self._get_effective_bundles(bundle)
        if bundle is not None:
            results: List[PatientModel] = []
            for b in bundles:
                p_model, _, _, _ = self._extract_and_register_patient_bundle(
                    b, mwl_service=self.mwl_service, create_mwl_entries=False
                )
                results.append(p_model)
        else:
            if len(self._patients) < len(bundles):
                for b in bundles:
                    self._extract_and_register_patient_bundle(b, mwl_service=self.mwl_service, create_mwl_entries=False)
            results = list(self._patients)

        if patient_id:
            results = [p for p in results if p.patient_id == patient_id]
        if patient_name:
            import fnmatch

            q_upper = patient_name.strip().upper()
            if "*" in q_upper or "?" in q_upper:
                results = [p for p in results if fnmatch.fnmatch((p.patient_name or "").upper(), q_upper)]
            else:
                results = [p for p in results if q_upper in (p.patient_name or "").upper()]
        return results

    def get_studies(
        self,
        bundle: FhirBundle | None = None,
        patient_id: str | None = None,
        study_uid: str | None = None,
        accession: str | None = None,
    ) -> List[StudyModel]:
        """Retrieve ``StudyModel`` objects extracted from the given FHIR Bundle or cached patient bundles.

        Args:
            bundle: Optional ``FhirBundle`` to extract from. When omitted or ``None``,
                ``self._patient_bundles`` is used.
            patient_id: Optional patient ID filter.
            study_uid: Optional ``StudyInstanceUID`` filter.
            accession: Optional ``AccessionNumber`` filter.

        Returns:
            List of matching ``StudyModel`` objects.
        """
        if bundle is None and self._patient_bundles is None:
            if self.synthea_output_folder and os.path.exists(self.synthea_output_folder):
                self.load_all_bundles()
            else:
                return []

        bundles = self._get_effective_bundles(bundle)
        if bundle is not None:
            studies: List[StudyModel] = []
            for b in bundles:
                p_model, b_studies, _, _ = self._extract_and_register_patient_bundle(
                    b, mwl_service=self.mwl_service, create_mwl_entries=False
                )
                if patient_id and p_model.patient_id != patient_id:
                    continue
                studies.extend(b_studies)
        else:
            if not self._studies and bundles:
                for b in bundles:
                    self._extract_and_register_patient_bundle(b, mwl_service=self.mwl_service, create_mwl_entries=False)
            if patient_id:
                allowed_study_uids = {
                    str(r.get("study_uid", ""))
                    for r in self._patient_study_series_records
                    if str(r.get("patient_id", "")) == str(patient_id)
                }
                studies = [st for st in self._studies if st.study_instance_uid in allowed_study_uids]
            else:
                studies = list(self._studies)

        if study_uid:
            studies = [st for st in studies if st.study_instance_uid == study_uid]
        if accession:
            studies = [st for st in studies if st.accession_number == accession]
        return studies

    def get_series(
        self,
        bundle: FhirBundle | None = None,
        study_uid: str | None = None,
        series_uid: str | None = None,
        modality: str | None = None,
        patient_id: str | None = None,
    ) -> List[SeriesModel]:
        """Retrieve ``SeriesModel`` objects extracted from the given FHIR Bundle or cached patient bundles.

        Args:
            bundle: Optional ``FhirBundle`` to extract from. When omitted or ``None``,
                ``self._patient_bundles`` is used.
            study_uid: Optional ``StudyInstanceUID`` filter.
            series_uid: Optional ``SeriesInstanceUID`` filter.
            modality: Optional ``Modality`` filter.
            patient_id: Optional ``PatientID`` filter.

        Returns:
            List of matching ``SeriesModel`` objects.
        """
        if bundle is None and self._patient_bundles is None:
            if self.synthea_output_folder and os.path.exists(self.synthea_output_folder):
                self.load_all_bundles()
            else:
                return []

        bundles = self._get_effective_bundles(bundle)
        if bundle is not None:
            for b in bundles:
                self._extract_and_register_patient_bundle(b, mwl_service=self.mwl_service, create_mwl_entries=False)
        elif not self._series and bundles:
            for b in bundles:
                self._extract_and_register_patient_bundle(b, mwl_service=self.mwl_service, create_mwl_entries=False)

        if study_uid or patient_id or bundle is not None:
            bundle_pids = set()
            if bundle is not None:
                for b in bundles:
                    p = self.get_patient(b)
                    pid = self.get_patient_id(p) if p else None
                    if pid:
                        bundle_pids.add(pid)
            allowed_series_uids = set()
            for r in self._patient_study_series_records:
                if bundle is not None and bundle_pids and str(r.get("patient_id", "")) not in bundle_pids:
                    continue
                if patient_id and str(r.get("patient_id", "")) != str(patient_id):
                    continue
                if study_uid and str(r.get("study_uid", "")) != str(study_uid):
                    continue
                allowed_series_uids.add(str(r.get("series_uid", "")))
            series_list = [ser for ser in self._series if ser.series_instance_uid in allowed_series_uids]
        else:
            series_list = list(self._series)

        if series_uid:
            series_list = [ser for ser in series_list if ser.series_instance_uid == series_uid]
        if modality:
            mod_upper = modality.strip().upper()
            series_list = [ser for ser in series_list if (ser.modality or "").upper() == mod_upper]
        return series_list

    def get_patient_study_series_records(
        self,
        bundle: FhirBundle | None = None,
        patient_id: str | None = None,
        study_uid: str | None = None,
    ) -> List[dict[str, Any]]:
        """Retrieve correlated patient-study-series records for C-FIND and DICOMweb queries."""
        if bundle is not None:
            _, _, _, b_records = self._extract_and_register_patient_bundle(
                bundle, mwl_service=self.mwl_service, create_mwl_entries=False
            )
            records = b_records
        else:
            if self._patient_bundles is not None and not self._patient_study_series_records:
                for b in self._patient_bundles:
                    self._extract_and_register_patient_bundle(b, mwl_service=self.mwl_service, create_mwl_entries=False)
            records = list(self._patient_study_series_records)

        if patient_id:
            records = [r for r in records if str(r.get("patient_id", "")) == str(patient_id)]
        if study_uid:
            records = [r for r in records if str(r.get("study_uid", "")) == str(study_uid)]
        return records

    def load_all_bundles(self) -> None:
        """Load hospital, practitioner, and patient bundles from ``synthea_output_folder``."""
        if self.synthea_output_folder and os.path.exists(self.synthea_output_folder):
            if self._hospital_bundles is None:
                self.get_hospital_information()
            if self._practitioner_bundles is None:
                self.get_practitioner_information()
            if self._patient_bundles is None:
                self.scan_synthea_output()

    def process_all_patients_to_dicom(
        self,
        mwl_service: Any,
        generator_service: Any,
        target_dir: str | None = None,
    ) -> List[MockDicomResponse]:
        """Load Synthea bundles from ``synthea_output_folder`` and process patient bundles to MWL and DICOM."""
        if not self.has_hospital_and_practitioner_info() or self._patient_bundles is None:
            self.load_all_bundles()
        responses: List[MockDicomResponse] = []
        for b in list(self._patient_bundles or []):
            responses.extend(
                self.process_patient_bundle_to_dicom(
                    b,
                    mwl_service=mwl_service,
                    generator_service=generator_service,
                    target_dir=target_dir,
                )
            )
        return responses

    def process_patient_bundle_to_dicom(
        self,
        bundle: FhirBundle,
        mwl_service: Any,
        generator_service: Any,
        target_dir: str | None = None,
    ) -> List[MockDicomResponse]:
        """Convert matching ``ImagingStudy`` series in a Synthea patient bundle into MWL entries and DICOM files.

        Also generates and registers the corresponding patient, study, and series records so that
        DICOM C-FIND (Patient, Study, Series, Image levels) and DICOMweb queries can discover them.

        Args:
            bundle: Validated patient ``FhirBundle`` containing ``ImagingStudy`` resources.
            mwl_service: ``MwlGeneratorService`` instance used to register MWL entries and study/series records.
            generator_service: ``DicomGeneratorService`` instance used to write DICOM files to disk.
            target_dir: Optional output directory for generated DICOM files (defaults to ``config.storage_dir``).

        Returns:
            List of ``MockDicomResponse`` objects, one per matching ``ImagingStudy`` series.

        Raises:
            ValueError: If hospital or practitioner bundles have not yet been loaded into memory.
        """
        if not self.has_hospital_and_practitioner_info():
            raise ValueError(
                "Hospital and practitioner information bundles must be loaded "
                "at least once before processing patient bundles."
            )

        if self._patient_bundles is None:
            self._patient_bundles = []
        self.add_patient_bundle(bundle, mwl_service=mwl_service)

        patient_model, _, _, bundle_records = self._extract_and_register_patient_bundle(
            bundle,
            mwl_service=mwl_service,
            create_mwl_entries=True,
        )

        responses: List[MockDicomResponse] = []
        out_dir = target_dir or config.storage_dir

        for rec in bundle_records:
            mock_req = MockDicomRequest(
                patient=patient_model,
                study=StudyModel(
                    study_instance_uid=rec["study_uid"],
                    study_date=rec.get("study_date") or datetime.datetime.now().strftime("%Y%m%d"),
                    study_time=rec.get("study_time") or "120000",
                    accession_number=rec["accession"],
                    study_description=rec.get("study_description"),
                    institution_name=rec.get("institution_name"),
                    referring_physician_name=rec.get("referring_physician"),
                    performing_physician_name=rec.get("performing_physician"),
                ),
                series=SeriesModel(
                    series_instance_uid=rec["series_uid"],
                    modality=rec["modality"],
                    series_number=int(rec.get("series_number") or 1),
                    series_description=rec.get("series_description"),
                    performing_physician_name=rec.get("performing_physician"),
                ),
                num_instances=int(rec.get("num_instances") or 1),
            )

            dicom_resp = generator_service.generate_and_save(mock_req, target_dir=out_dir)
            responses.append(dicom_resp)

        return responses

    def load_and_generate_from_raw_bundles(
        self,
        bundles: List[dict[str, Any] | FhirBundle],
        mwl_service: Any,
        generator_service: Any,
        target_dir: str | None = None,
    ) -> List[FhirBundle]:
        """Validate raw FHIR R4 JSON bundles, cache them additively, and generate MWL entries and DICOM files.

        Performs a two-pass ingestion:
        1. Validates all bundle dictionaries/instances into ``FhirBundle`` and ingests any hospital or
           practitioner bundles into memory first.
        2. Verifies hospital and practitioner bundles are resident in memory before processing patient bundles,
           logs warnings for patient bundles without matching ``ImagingStudy`` resources, and generates MWL entries
           plus on-disk DICOM files for matching studies.

        Args:
            bundles: Non-empty list of FHIR Bundle dictionaries or ``FhirBundle`` instances.
            mwl_service: ``MwlGeneratorService`` instance.
            generator_service: ``DicomGeneratorService`` instance.
            target_dir: Optional output directory for generated DICOM files (defaults to ``config.storage_dir``).

        Returns:
            Flat list of validated patient ``FhirBundle`` instances for which imaging studies were processed.

        Raises:
            ValueError: If the bundle list is empty, bundles are invalid, or prerequisite
                hospital/practitioner bundles are missing.
        """
        if not bundles:
            raise ValueError("A non-empty list of FHIR Bundles is required.")

        pending: List[FhirBundle] = []

        # Pass 1: Parse/validate all bundles and ingest hospital/practitioner bundles first
        for idx, item in enumerate(bundles):
            if isinstance(item, FhirBundle):
                raw_bundle = item
            elif isinstance(item, dict):
                try:
                    raw_bundle = FhirBundle.model_validate(item)
                except Exception as exc:
                    raise ValueError(f"Invalid FHIR Bundle at index {idx}: {exc}") from exc
            else:
                raise ValueError(f"Expected dict or FhirBundle at index {idx}, got {type(item).__name__}")

            b_type = self.classify_bundle(raw_bundle)

            if b_type == "hospital":
                self.add_hospital_bundle(raw_bundle)
                logger.info("synthea_hospital_bundle_loaded", bundle_id=raw_bundle.id)
            elif b_type == "practitioner":
                self.add_practitioner_bundle(raw_bundle)
                logger.info("synthea_practitioner_bundle_loaded", bundle_id=raw_bundle.id)
            elif b_type == "patient":
                pending.append(raw_bundle)
            else:
                logger.warning("synthea_bundle_unrecognized_type", bundle_id=raw_bundle.id)

        # Prerequisite check for patient bundles: hospital resources first, then practitioner resources
        if pending:
            if not self.has_hospital_info():
                raise ValueError("Hospital resources must be sent first.")
            if not self.has_practitioner_info():
                raise ValueError("Practitioner resources must be sent first.")

        # Pass 2: Filter patient bundles, cache matching ones, and generate MWL + DICOM files
        processed_bundles: List[FhirBundle] = []
        for raw_bundle in pending:
            filtered = self.filter_imaging_bundle(raw_bundle)
            if filtered is None:
                logger.warning(
                    "synthea_bundle_no_supported_imaging_study",
                    bundle_id=raw_bundle.id,
                    modalities=self._modalities,
                )
                continue

            self.add_patient_bundle(filtered)
            logger.info("synthea_patient_bundle_loaded", bundle_id=filtered.id)
            self.process_patient_bundle_to_dicom(
                filtered,
                mwl_service=mwl_service,
                generator_service=generator_service,
                target_dir=target_dir,
            )
            processed_bundles.append(filtered)

        return processed_bundles

    def load_and_generate_from_uris(
        self,
        uris: List[str],
        mwl_service: Any,
        generator_service: Any,
        target_dir: str | None = None,
    ) -> List[MockDicomResponse]:
        """Validate ``file://`` URIs, additively cache bundles, and generate MWL entries and DICOM files.

        Performs a two-pass ingestion:
        1. Validates all URIs, loads raw FHIR Bundles, and ingests any hospital or practitioner bundles first.
        2. Verifies hospital and practitioner bundles are resident in memory before processing patient bundles,
           logs warnings for patient bundles without matching ``ImagingStudy`` resources, and generates MWL entries
           plus on-disk DICOM files for matching studies.

        Args:
            uris: Non-empty list of ``file://`` URI strings.
            mwl_service: ``MwlGeneratorService`` instance.
            generator_service: ``DicomGeneratorService`` instance.
            target_dir: Optional output directory for generated DICOM files (defaults to ``config.storage_dir``).

        Returns:
            Flat list of ``MockDicomResponse`` objects generated across all matching patient bundles.

        Raises:
            ValueError: If any URI is invalid or prerequisite hospital/practitioner bundles are missing.
        """
        if not uris:
            raise ValueError("URI list must not be empty.")

        pending: List[Tuple[str, str, str, FhirBundle]] = []

        # Pass 1: Validate all URIs and ingest hospital/practitioner bundles first
        for uri in uris:
            file_path = self.parse_file_uri(uri)
            raw_bundle = self.load_raw_bundle(file_path)
            b_type = self.classify_bundle(raw_bundle, os.path.basename(file_path))

            if b_type == "hospital":
                self.add_hospital_bundle(raw_bundle)
                logger.info("synthea_hospital_bundle_loaded", uri=uri, file_path=file_path)
            elif b_type == "practitioner":
                self.add_practitioner_bundle(raw_bundle)
                logger.info("synthea_practitioner_bundle_loaded", uri=uri, file_path=file_path)
            else:
                pending.append((uri, file_path, b_type, raw_bundle))

        has_patient_bundles = any(b_type == "patient" for _, _, b_type, _ in pending)
        if has_patient_bundles and not self.has_hospital_and_practitioner_info():
            raise ValueError(
                "Hospital and practitioner information bundles must be loaded "
                "at least once before loading patient bundles."
            )

        # Pass 2: Filter patient bundles, cache matching ones, and generate MWL + DICOM files
        responses: List[MockDicomResponse] = []
        for uri, file_path, b_type, raw_bundle in pending:
            if b_type == "patient":
                filtered = self.filter_imaging_bundle(raw_bundle)
                if filtered is None:
                    logger.warning(
                        "synthea_bundle_no_supported_imaging_study",
                        uri=uri,
                        file_path=file_path,
                        modalities=self._modalities,
                    )
                    continue
                self.add_patient_bundle(filtered)
                logger.info("synthea_patient_bundle_loaded", uri=uri, file_path=file_path)
                bundle_responses = self.process_patient_bundle_to_dicom(
                    filtered,
                    mwl_service=mwl_service,
                    generator_service=generator_service,
                    target_dir=target_dir,
                )
                responses.extend(bundle_responses)
            else:
                logger.warning("synthea_bundle_unrecognized_type", uri=uri, file_path=file_path)

        return responses


def get_patient_name(patient: FhirPatient) -> str | None:
    """Format the primary patient name into DICOM Person Name (PN) format.

    Args:
        patient: The ``FhirPatient`` resource to inspect.

    Returns:
        The patient's first listed name formatted as ``Last^First^Middle^Prefix^Suffix``,\
        or ``None`` if the patient has no name entries.
    """
    if not patient or not isinstance(patient, FhirPatient):
        return None

    if patient.name and len(patient.name) > 0:
        return format_human_name_to_dicom(patient.name[0])
    return None
