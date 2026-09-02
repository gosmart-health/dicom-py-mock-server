# Changelog

All notable changes to `dicom-py-mock-server` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> [!NOTE]
> **Source-Code Release Distribution**: Releases of `dicom-py-mock-server` are distributed strictly as source-code releases. No binary compilation or wheel build pipeline is required.

## [0.2.2] - 2026-09-02

### Added
- **High-Throughput Stress Mode (`GOSMART_MS_STRESS`)**:
  - Implemented server-wide stress mode controlled via `GOSMART_MS_STRESS=true/false` (or alias `STRESS`, defaults to `false`).
  - **Single Frame Compression Precomputation**: In stress mode, image matrix rendering and compression (OpenJPEG JPEG 2000, Pillow JPEG Baseline, pylibjpeg RLE) are executed only once per study or series. Subsequent instances clone the precomputed compressed frame payload, avoiding repetitive CPU-heavy encoding and yielding >3x to >10x generation speedup.
  - **Selective Demographics Overlay**: Burns patient and study demographics (`Patient Name`, `Patient ID`, `Study Date Study Time`) into the base matrix image, while omitting the per-slice overlay line (`Image: <number>`) to preserve identical pixel data across instances.
  - **DIMSE Association Transfer Syntax Negotiation**: Storage presentation context transfer syntax negotiated at association start is passed directly to the generator, computing the single compressed frame natively in the negotiated syntax for C-MOVE and C-STORE push workflows.
  - **WADO-RS First-Request Transfer Syntax Caching**: In WADO-RS, the transfer syntax from the first image request sets the cached transfer syntax and compressed frame for the study, which is reused for subsequent study, series, or instance requests.
  - **Standards Compliance & Deterministic UIDs**: Each synthesized instance retains a unique `SOPInstanceUID`, `MediaStorageSOPInstanceUID`, and sequential `InstanceNumber`, maintaining strict DICOM Part 10 conformance.
  - **Request-Level Overrides**: Added `stress: bool | None` and `include_slice_overlay: bool | None` options to `MockDicomRequest` and `RawImageGeneratorRequest` for granular per-request control.
  - **Cache Management**: Added `clear_stress_cache()` to `DicomWebService` for clearing cached study transfer syntaxes and datasets between test cycles.
  - **Automated Stress Test Suite**: Added `tests/test_stress_mode.py` with 8 dedicated test cases validating environment variable parsing, demographics text vs omitted slice overlays, single-frame byte identity, WADO stickiness, and performance speedup.

## [0.2.1] - 2026-09-02

### Added
- **Dynamic WADO-RS Transfer Syntax Negotiation**:
  - Implemented dynamic, per-request transfer syntax negotiation for all 6 supported DICOM transfer syntaxes:
    - JPEG Baseline Process 1 (`1.2.840.10008.1.2.4.50`)
    - JPEG 2000 Lossless (`1.2.840.10008.1.2.4.90`)
    - JPEG 2000 Lossy (`1.2.840.10008.1.2.4.91`)
    - RLE Lossless (`1.2.840.10008.1.2.5`)
    - Explicit VR Little Endian (`1.2.840.10008.1.2.1`)
    - Implicit VR Little Endian (`1.2.840.10008.1.2`)
  - Enhanced `parse_transfer_syntax_header` to parse standard `transfer-syntax` parameters, media types (`type="image/jpeg"`, `type="image/jp2"`, `type="image/jpx"`, `type="image/rle"`, `type="application/octet-stream"`), direct headers (`transfer-syntax`, `X-Transfer-Syntax`), and query parameters (`?transferSyntax=...`).
  - Added multi-syntax frame transcoding (`get_encoded_frames`) in `DicomWebService`, encoding frame pixel arrays into JPEG (`image/jpeg`), JPEG 2000 (`image/jp2`), RLE (`image/rle`), or raw uncompressed octet-streams (`application/octet-stream`).
  - Updated WADO-RS `/frames/{frameList}` endpoint to return multipart frame payloads with appropriate `Content-Type` matching the negotiated transfer syntax.
  - Added transfer syntax parameter support to WADO-RS metadata endpoints (`/metadata`) to optionally reflect negotiated pixel attributes (such as 8-bit dynamic range for JPEG Baseline) in metadata JSON responses.
- **WADO Study Download Utility Scripts**:
  - Added `wado_download_study.py` standalone utility script to download complete DICOM studies via WADO-RS and extract individual `.dcm` instances into a destination directory without external dependencies.
  - Added `wado_download_study.sh` helper shell script for automated testing.
- **High-Volume Stress Testing Support (Up to 1024 Slices)**:
  - Expanded `MockDicomRequest.num_instances` upper validation bound from 100 to 1024 instances (`le=1024`) for high-volume stress testing.
  - Updated MCP tool schema definition for `num_instances` to accept up to 1024 slices.
  - Updated WADO-RS study, series, and metadata endpoints (`/studies/{studyUID}`, `/series/{seriesUID}`, `/metadata`) to support query parameters (`limit`, `slices`, `count`, `numInstances`, `num_instances`).
  - Ensured WADO-RS retrieval follows the actual number of slices generated for the requested study/series rather than truncating at an arbitrary fixed 100 limit.
- **Enhanced Logging**:
  - Automatically log caller `method_name` and `func_name` across structured JSON log events.
  - Log incoming HTTP and DICOMweb request headers (`Accept`) and resolved transfer syntaxes.

### Fixed
- **Pixel Data Corruption in Metadata Extraction**:
  - Fixed shallow copy bug in `DicomWebService.get_metadata` where `ds.copy()` mutated the in-memory dataset, inadvertently stripping `PixelData` and causing subsequent frame retrievals to fail. Switched to `copy.deepcopy` to maintain dataset integrity.
- **WADO-RS Transfer Syntax Enforcement**:
  - Resolved issue where clients requesting JPEG Process 1 received 12-bit uncompressed frames due to server-wide environment variable defaults. WADO-RS now strictly honors client-requested transfer syntaxes.
- **SCU Presentation Context Negotiation**:
  - Cleaned up SCU presentation context syntax negotiation to propose the specific configured target syntax.

## [0.2.0] - 2026-09-01

### Added
- **DICOMweb Standard Protocol Services (PS 3.18)**:
  - **QIDO-RS (Query based on ID for DICOM Objects)**:
    - Implemented RESTful query endpoints: `/dicomweb/studies`, `/dicomweb/studies/{studyUID}/series`, `/dicomweb/studies/{studyUID}/series/{seriesUID}/instances`, and `/dicomweb/instances`.
    - Supports query matching filters (`PatientID`, `PatientName`, `StudyDate`, `ModalitiesInStudy`, `Modality`, `AccessionNumber`, `fuzzyMatching`), field projection (`includefield`), and pagination (`limit`, `offset`).
    - Returns standard DICOM JSON format (`application/dicom+json`).
  - **WADO-RS (Web Access to DICOM Objects by RESTful Services)**:
    - Implemented retrieve endpoints for studies, series, instances, and frame objects (`/dicomweb/studies/{studyUID}`, `/dicomweb/studies/{studyUID}/series/{seriesUID}`, `/dicomweb/studies/{studyUID}/series/{seriesUID}/instances/{sopUID}`).
    - Full metadata retrieval (`/metadata`) returning bulk JSON dataset hierarchy.
    - Rendered consumer format retrieval (`/rendered`) providing server-side dynamic rendering to JPEG and PNG with frame indexing (`frame=N`), quality control (`quality=1-100`), and window level adjustments.
    - Multipart DICOM Part 10 packaging (`multipart/related; type="application/dicom"`).
  - **STOW-RS (Store Over the Web by RESTful Services)**:
    - Implemented web-based DICOM ingestion endpoints (`POST /dicomweb/studies` and `POST /dicomweb/studies/{studyUID}`).
    - Parses `multipart/related` payloads containing DICOM Part 10 streams, stores instances to local storage directory, and returns standard XML/JSON STOW response headers.
  - **WADO-URI (Web Access to DICOM Persistent Objects via URI)**:
    - Implemented legacy single-part HTTP GET interface (`/dicomweb/wado`) supporting `requestType=WADO`, `contentType=application/dicom`, `contentType=image/jpeg`, `contentType=image/png`, frame extraction, and transfer syntax negotiation.
- **Design & Specification Documentation**:
  - Updated Software Requirements Specification (`gsms_000_software_requirements_spec.md`), System Design (`gsms_010_system_design_specification.md`), Verification Plan (`gsms_030_verification_and_validation_plan.md`), Traceability Matrix (`gsms_040_traceability_matrix.md`), and `README.md` with complete DICOMweb endpoints and testing instructions.

### Fixed
- **Pydicom 4.0 Compatibility & Deprecation Cleanup (`generator.py`)**:
  - Removed deprecated kwargs `is_implicit_VR=False` and `is_little_endian=True` in `FileDataset(...)` initialization in `DicomGeneratorService.create_dicom_file`.
  - Removed deprecated property mutations `ds.is_implicit_VR` and `ds.is_little_endian` in `apply_transfer_syntax`.
  - Cleared dataset internal read-encoding flags (`_is_implicit_VR`, `_is_little_endian`, `_read_implicit`, `_read_little` set to `None`) so in-memory synthesized DICOM instances correctly adhere to their `file_meta.TransferSyntaxUID` without defaulting to Implicit VR Little Endian during `pynetdicom` C-STORE operations.
- **Test Suite Modernization (`test_generator.py`)**:
  - Updated transfer syntax assertion checks to use standard `file_meta.TransferSyntaxUID.is_implicit_VR` and `file_meta.TransferSyntaxUID.is_little_endian` properties.

## [0.1.1] - 2026-09-01

### Added
- **Direct MicroDICOM Viewer Integration Tests**:
  - Added `test_microdicom_send_jpeg2000_lossless_from_ct_small_template` verifying template-based JPEG 2000 Lossless DICOM synthesis, presentation context negotiation, and C-STORE push directly to MicroDICOM Viewer (`127.0.0.1:11113`, `AE_Title=MDICOM`).
  - Added TCP port availability helper (`_is_microdicom_available()`) to gracefully skip port 11113 integration tests via `pytest.skip()` during offline CI or development environments.

### Fixed
- **DICOM Transfer Syntax Association Negotiation (`scp.py`)**:
  - Fixed Storage SCU requested presentation contexts in C-MOVE sub-operations and C-STORE pushes to propose the specific configured `target_syntax` (`JPEG2000_LOSSLESS`, `RAW`, `RLE`, `JPEG`).
  - Resolved association negotiation failure where DICOM viewers (such as MicroDICOM) selected alternate uncompressed or JPEG Baseline transfer syntaxes when multiple syntaxes were offered in a single context, causing subsequent compressed C-STORE sub-operations to fail.
  - Maintained full multi-syntax support (`SUPPORTED_TRANSFER_SYNTAXES`) for incoming Storage SCP operations.
- **Template DICOM Synthesis & Dimension Scaling (`generator.py`)**:
  - Fixed synthesized DICOM instance dimensions to consistently default to `512`x`512` (with dynamic range patterns and burned-in metadata) rather than inheriting smaller dimensions from base template files (e.g. `templates/CT_small.dcm` 128x128).
  - Cleaned up duplicate keyword arguments in `DicomGeneratorService.create_instances_from_mwl`.
- **Default Transfer Syntax**:
  - Updated default `transfer_syntax` from `"RAW"` to `"JPEG2000_LOSSLESS"` in application config and generation fallbacks.

## [0.1.0] - 2026-08-31

### Added
- **Deterministic ITU-T X.667 / ISO/IEC 9834-8 DICOM UID Generation (Issue #8)**:
  - Implemented standards-compliant `2.25.<u128>` DICOM UID construction adhering to DICOM PS 3.5 Annex B.2 using SHA-1 (UUIDv5, default) and MD5 (UUIDv3) over a persistent namespace UUID (`GOSMART_MS_NAMESPACE_UUID`, default `6ba7b810-9dad-11d1-80b4-00c04fd430c8`).
  - Hierarchical deterministic derivation: StudyInstanceUID from `PatientName`, `PatientID`, and `AccessionNumber`; SeriesInstanceUID from `StudyUID` and `SeriesNumber`; SOPInstanceUID from `SeriesUID` and `InstanceNumber`.
  - Privacy and PHI protection preventing raw identifier strings from leaking into DICOM UIDs while guaranteeing reproducible generation across test iterations.
  - Configuration support via `GOSMART_MS_NAMESPACE_UUID` and `GOSMART_MS_UID_VERSION`.
- **C-STORE Association CSV Audit Logging (Issue #3)**:
  - Automated generation of CSV audit logs upon completion of C-STORE transfers (SCU move/push, C-MOVE retrievals, and incoming Storage SCP transactions).
  - Generates UTC-timestamped audit files `<yyyymmddhhmmss>_<AE_Title>.csv` in configurable path `GORMART_MS_CSV_PATH` (default `./csv`).
  - Logs header columns: `Date,Time,Destination AE,Status,Patient Name,Patient ID,Accession Number,Study UID,Series UID,Instance UID,Transfer Rate kb/s` with statuses `Accepted`, `Rejected`, `No Connection`, `Dropped`.
- **Physician & Institution Demographics & Propagation (Issue #5)**:
  - Initializes synthetic pools of Referring Physician, Performing Physician, and Reading Physician names on startup with configurable `GOSMART_MS_PN_SUFFIX` (default `_GSH`) and default `GORMART_MS_INSTITUTION_NAME` (`GO SMART CLINIC`).
  - Propagates Referring Physician (`0008,0090`), Performing Physician (`0008,1050`), Reading Physician (`0008,1060`), and Institution Name (`0008,0080`) attributes across MWL entries, SOP instances, and C-MOVE network transfers.

## [0.0.2] - 2026-08-30
- **Fixed Issue 5**: Fixed the bug where C-FIND does not return all needed attributes.

## [0.0.1] - 2026-08-28

### Added
- **Synthetic DICOM P10 Generator**: Generates realistic, fully customizable DICOM Part 10 files with configurable Patient, Study, Series, and SOP Instance attributes.
- **Pixel Data Synthesis Engine**: Generates 12-bit dynamic range test patterns [0, 4095] with 4 monotonic gradient segments and burned-in OCR metadata headers.
- **DICOM Network Services (SCP)**: Embedded `pynetdicom` Application Entity listener supporting C-ECHO (Verification), C-FIND (Query), C-MOVE/C-GET (Retrieve), and C-STORE (Storage).
- **Modality Worklist (MWL) Service**: Automated background MWL schedule generation modeling realistic business hours (9 AM–5 PM) vs off-peak rates.
- **REST API Suite**: FastAPI endpoints for on-demand DICOM synthesis (`/api/v1/generate`, `/api/v1/generate/raw`), MWL querying and management (`/api/v1/mwl`), and DICOM SCP lifecycle controls (`/api/v1/scp`).
- **Model Context Protocol (MCP) SSE Transport**: Full MCP Server-Sent Events interface exposing tools for AI assistants (AntiGravity, Claude Desktop, Cursor) to automate DICOM testing workflows.
- **Transfer Syntax Support**: Support for `RAW` (Explicit VR Little Endian), `JPEG` (Process 1 Baseline), `JPEG2000` (Lossless), and `RLE` encodings.
- **Startup Licensing & Non-Clinical Notice**: Structured notice logging on application startup: `Created by Gosmart.Health (info@gosmart.health) 2026, Apache 2.0 License, Not for clinical use.`
- **Configuration & Logging**: Environment variable configuration via `pydantic-settings` and structured JSON-lines logging with timed file rotation.
- **Continuous Integration (CI)**: GitHub Actions workflow on Pull Requests to `main` featuring `uv lock` verification, `ruff` linting and formatting gates, `pip-audit` package vulnerability scanning, and pytest test matrix across x86 Linux (`ubuntu-latest`) and x86 Windows (`windows-latest`) for Python 3.10–3.14.
- **Software Bill of Materials (SBOM)**: CycloneDX 1.6 compliant `sbom.json` generation and automated validation via `cyclonedx-bom`.
- **Comprehensive Test Suite**: Unit and integration test coverage verifying Pydantic models, DICOM generator, SCP network handlers, and MCP SSE sessions.

### Security
- **Synthetic PHI Safeguard**: All generated patient names, IDs, and accessions are strictly synthetic, preventing unintentional ingestion of real clinical PHI.
- **Default Loopback Binding**: REST and MCP HTTP services bind to local loopback (`127.0.0.1`) by default to prevent unintended exposure to external networks.
- **SOUP & Dependency Auditing**: Continuous dependency vulnerability monitoring with `pip-audit` and deterministic builds locked with `uv.lock`.
