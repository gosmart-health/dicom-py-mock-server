# DICOM Python Mock Server

The DICOM Python Mock Server generates and serves mock DICOM objects for non-clinical testing and integration.

**Safety:** The server has no authentication or authorization and must not be exposed to untrusted networks or used in production. It does not de-identify template DICOM files; ensure templates contain no sensitive PHI.

- [User guide](user-guide.md): setup, configuration, services, and examples.
- EHR integration: [FHIR to MWL](ehr/FHIR_to_MWL.md) and [HL7 to MWL](ehr/HL7_to_MWL.md).
- [DICOM conformance statement](dicom-conformance.md): supported DICOM services and behavior.