"""Pydantic v2 data models for FHIR R4/R5 ServiceRequest and Bundle."""

from typing import Any

from pydantic import BaseModel, Field


class FhirCoding(BaseModel):
    """FHIR Coding datatype."""

    system: str | None = None
    version: str | None = None
    code: str | None = None
    display: str | None = None


class FhirCodeableConcept(BaseModel):
    """FHIR CodeableConcept datatype."""

    coding: list[FhirCoding] = Field(default_factory=list)
    text: str | None = None


class FhirIdentifier(BaseModel):
    """FHIR Identifier datatype."""

    use: str | None = None
    system: str | None = None
    value: str | None = None


class FhirHumanName(BaseModel):
    """FHIR HumanName datatype."""

    use: str | None = None
    text: str | None = None
    family: str | None = None
    given: list[str] = Field(default_factory=list)
    prefix: list[str] = Field(default_factory=list)
    suffix: list[str] = Field(default_factory=list)

    def to_dicom_format(self) -> str:
        """Convert FHIR HumanName into DICOM Person Name format (Last^First^Middle^Prefix^Suffix)."""
        family = (self.family or "").strip()
        given = (self.given[0] if self.given else "").strip()
        middle = (self.given[1] if len(self.given) > 1 else "").strip()
        prefix = (self.prefix[0] if self.prefix else "").strip()
        suffix = (self.suffix[0] if self.suffix else "").strip()

        components = [family, given, middle, prefix, suffix]
        # Strip trailing empty components
        while components and not components[-1]:
            components.pop()
        return "^".join(components)


class FhirReference(BaseModel):
    """FHIR Reference datatype."""

    reference: str | None = None
    type: str | None = None
    display: str | None = None


class FhirPatient(BaseModel):
    """FHIR Patient resource."""

    resourceType: str = "Patient"
    id: str | None = None
    identifier: list[FhirIdentifier] = Field(default_factory=list)
    name: list[FhirHumanName] = Field(default_factory=list)
    birthDate: str | None = None
    gender: str | None = None


class FhirPractitioner(BaseModel):
    """FHIR Practitioner resource."""

    resourceType: str = "Practitioner"
    id: str | None = None
    identifier: list[FhirIdentifier] = Field(default_factory=list)
    name: list[FhirHumanName] = Field(default_factory=list)


class FhirEncounter(BaseModel):
    """FHIR Encounter resource."""

    resourceType: str = "Encounter"
    id: str | None = None
    identifier: list[FhirIdentifier] = Field(default_factory=list)
    status: str | None = None


class FhirServiceRequest(BaseModel):
    """FHIR ServiceRequest resource representing an imaging procedure order."""

    resourceType: str = "ServiceRequest"
    id: str | None = None
    identifier: list[FhirIdentifier] = Field(default_factory=list)
    status: str | None = "active"
    intent: str | None = "order"
    category: list[FhirCodeableConcept] = Field(default_factory=list)
    priority: str | None = None
    code: FhirCodeableConcept | None = None
    subject: FhirReference | None = None
    encounter: FhirReference | None = None
    occurrenceDateTime: str | None = None
    requester: FhirReference | None = None
    performer: list[FhirReference] = Field(default_factory=list)
    reasonCode: list[FhirCodeableConcept] = Field(default_factory=list)
    bodySite: list[FhirCodeableConcept] = Field(default_factory=list)


class FhirBundleEntry(BaseModel):
    """Entry element inside a FHIR Bundle."""

    fullUrl: str | None = None
    resource: dict[str, Any] = Field(default_factory=dict)


class FhirBundle(BaseModel):
    """FHIR Bundle container."""

    resourceType: str = "Bundle"
    id: str | None = None
    type: str | None = "collection"
    entry: list[FhirBundleEntry] = Field(default_factory=list)
