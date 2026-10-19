"""FHIR models re-exported from open-source fhir.resources (R4B) with helper utilities."""

from typing import Any

from fhir.resources.R4B.bundle import Bundle, BundleEntry
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.R4B.humanname import HumanName
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.imagingstudy import ImagingStudy
from fhir.resources.R4B.organization import Organization
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.practitioner import Practitioner
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.servicerequest import ServiceRequest


def format_human_name_to_dicom(name: HumanName | Any | None) -> str:
    """Convert FHIR HumanName into DICOM Person Name format (Last^First^Middle^Prefix^Suffix)."""
    if name is None:
        return ""

    family = (getattr(name, "family", "") or "").strip()
    given_list = getattr(name, "given", None) or []
    given = (given_list[0] if len(given_list) > 0 else "").strip()
    middle = (given_list[1] if len(given_list) > 1 else "").strip()
    prefix_list = getattr(name, "prefix", None) or []
    prefix = (prefix_list[0] if len(prefix_list) > 0 else "").strip()
    suffix_list = getattr(name, "suffix", None) or []
    suffix = (suffix_list[0] if len(suffix_list) > 0 else "").strip()

    components = [family, given, middle, prefix, suffix]
    # Strip trailing empty components
    while components and not components[-1]:
        components.pop()

    if not components:
        # Fall back to raw text if family/given were absent
        return (getattr(name, "text", "") or "").strip()

    return "^".join(components)


# Canonical and backward-compatible aliases
FhirBundle = Bundle
FhirBundleEntry = BundleEntry
FhirPatient = Patient
FhirPractitioner = Practitioner
FhirOrganization = Organization
FhirEncounter = Encounter
FhirServiceRequest = ServiceRequest
FhirHumanName = HumanName
FhirIdentifier = Identifier
FhirImagingStudy = ImagingStudy
FhirCodeableConcept = CodeableConcept
FhirCoding = Coding
FhirReference = Reference

__all__ = [
    "Bundle",
    "BundleEntry",
    "CodeableConcept",
    "Coding",
    "Encounter",
    "FhirBundle",
    "FhirBundleEntry",
    "FhirCodeableConcept",
    "FhirCoding",
    "FhirEncounter",
    "FhirHumanName",
    "FhirIdentifier",
    "FhirImagingStudy",
    "FhirOrganization",
    "FhirPatient",
    "FhirPractitioner",
    "FhirReference",
    "FhirServiceRequest",
    "HumanName",
    "Identifier",
    "ImagingStudy",
    "Organization",
    "Patient",
    "Practitioner",
    "Reference",
    "ServiceRequest",
    "format_human_name_to_dicom",
]
