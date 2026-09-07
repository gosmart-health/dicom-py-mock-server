# Changelog

All notable changes to `dicom-py-mock-server` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> [!NOTE]
> **Source-Code Release Distribution**: Releases of `dicom-py-mock-server` are distributed strictly as source-code releases. No binary compilation or wheel build pipeline is required.

## [0.3.0] - 2026-09-07

### Changed
- **Template Directory Structure Requirement (Breaking Change)**:
  - Standalone DICOM files directly located in the `templates/` root folder are no longer accepted and will raise a `ValueError` to prevent ambiguity.
  - Multi-slice templates must now be organized into dedicated subfolders per series/modality (e.g. `templates/Toshiba_Aquilion/`, `templates/MR/`).

### Added
- **Multi-Slice CT & MR Template Loading**:
  - Added multi-slice DICOM template loading from dedicated subfolders under `templates/` (e.g. `templates/Toshiba_Aquilion/`, `templates/MR/`).
  - Implemented strict folder structure validation: standalone files directly in `templates/` root are strictly rejected with `ValueError` to prevent ambiguity.
  - Implemented dynamic modality discovery from DICOM tag `(0008, 0060)` rather than directory names.
  - Enforced folder modality purity: subfolders containing datasets with mixed modalities raise a descriptive `ValueError`.
  - Added automatic non-image object exclusion: non-pixel objects, Presentation States (`PR`), Structured Reports (`SR`), and private raw objects (`XX_*`) are safely excluded from image slice series.
  - Added series grouping and deterministic slice sorting: DICOM instances within each template series are grouped by `SeriesInstanceUID` and sorted by `InstanceNumber`, `SliceLocation`, and image position `z` coordinate.
- **Template Study Description Preservation in Non-Synthetic Mode**:
  - In non-synthetic mode (`GOSMART_MS_SYNTHETIC_MODE=false`), preserved the original `StudyDescription` loaded from template datasets (such as `"dS Torso, T2W Tra, 3D MRCP, bTFE Cor, mDixon"` in `templates/MR`) across Modality Worklist (MWL) entries (`json_entry`, `dataset`, `entry_record`), C-FIND query responses, and synthesized DICOM SOP instances (`create_instances_from_mwl`).
  - Prohibited swapping native template Study Descriptions with mockup/random descriptions from `MODALITY_STUDY_DESCRIPTIONS` when running in non-synthetic mode.
  - For templates lacking an original `StudyDescription` (e.g. `templates/Toshiba_Aquilion`), prevented injecting mockup study descriptions, keeping `StudyDescription` unset or empty as in the source template.
  - Supported explicit `custom["studyDescription"]` overrides in MWL requests while defaulting to the template dataset's native value.
  - In synthetic mode (`GOSMART_MS_SYNTHETIC_MODE=true`), maintained standard synthetic generation of modality-aligned study descriptions when omitted.
  - Enhanced multi-slice scanning across all slices in `MwlGeneratorService._load_templates` to capture any present `StudyDescription` into `TemplateSeriesDataset.study_description`.
  - Added `study_instance_uid` and `study_description` fields to `TemplateSeriesDataset.to_dict()`.
- **Synthetic Mode (`GOSMART_MS_SYNTHETIC_MODE`)**:
  - Implemented configurable synthetic mode via `GOSMART_MS_SYNTHETIC_MODE=true/false` (or alias `SYNTHETIC_MODE`, default `false`).
  - **Non-Synthetic Mode (`false`, default)**:
    - Delivers complete series with the exact slice count matching the selected template series.
    - Sequentially rotates through template series per modality in round-robin fashion for Modality Worklist (MWL) entries.
    - Preserves the Study Description originally present in the template dataset without swapping with mock up values.
    - Preserves native template slice pixel data and image geometry without burned-in annotations.
    - Only in synthetic mode (`synthetic_mode=true`) are patient demographics and slice indicators burned into the image pixels.
  - **Synthetic Mode (`true`)**:
    - Generates synthetic slice volumes conforming to `min_slices`/`max_slices` configuration (or custom count requests).
    - Rotates slices cyclically across the template series (`slice_index = (i - 1) % M`).
    - Generates modality-aligned synthetic study descriptions when omitted.
    - Compatible with high-throughput stress mode (`GOSMART_MS_STRESS=true`): computes and compresses frame 0 once and clones the compressed payload for all remaining instances.
- **Transfer Syntax Conversion Logging & Performance Optimizations**:
  - Added structured logging for transfer syntax conversions in `DicomGeneratorService.apply_transfer_syntax` and `create_instances_from_mwl`, explicitly reporting `original_transfer_syntax`, `ending_transfer_syntax`, `original_transfer_syntax_uid`, and `ending_transfer_syntax_uid`.
  - Added series-level lifecycle logging (`generating_template_series_instances`, `generated_template_series_instances`) reporting modality, total slices, transfer syntax transition, conversion necessity, and generation duration in seconds.
  - Added `transfer_syntax` and `transfer_syntax_uid` metadata attributes to `dicom_c_store_instance_pushed` events during C-MOVE SCP storage sub-operations.
  - Optimized template slice transcoding: eliminated redundant NumPy `pixel_array` decompression and byte buffer re-packing when slices do not require burned-in annotations, and streamlined uncompressed Little Endian byte transfers.
- **WADO-RS In-Memory Caching & Fast Metadata Extraction**:
  - Implemented an LRU in-memory study cache (`_study_cache`) in `DicomWebService` keyed on `(study_instance_uid, target_transfer_syntax, is_stress)` with a capacity of 50 studies.
  - Eliminated redundant series generation and pixel transcoding on repetitive WADO-RS instance, frame, and rendered view requests for the same study, dropping subsequent retrieval latencies from ~3.3 seconds to under 1 microsecond.
  - Optimized WADO-RS metadata extraction (`get_metadata`) to shallow-copy datasets with pixel tag filtering `(0x7FE0, 0x0010)` and `(0x7FE0, 0x0001)`, avoiding expensive deep copies and eliminating pixel compression cycles for metadata-only requests.
  - Added cache management methods `clear_cache(study_uid=None)` with backwards-compatible alias `clear_stress_cache()`.
  - Added automated test case `test_wado_study_cache_and_transcoder_reuse` verifying zero repeated transcoding invocations across instance queries.
- **Zero-Dependency HL7 v2 MLLP Ingestion Subsystem**:
  - Implemented a built-in, non-blocking `asyncio` TCP server listening for HL7 v2 messages using Minimal Lower Layer Protocol (MLLP) on configurable port `GOSMART_MS_HL7_PORT` (default `2575`).
  - Added standard MLLP framing support (`<SB> = 0x0B`, `<EB><CR> = 0x1C 0x0D`) and automatic generation of `ACK^O01` acknowledgement responses (`AA` for application accept, `AE` for error/rejection).
  - Built zero-dependency parser for `ORM^O01` radiology orders extracting patient demographics (`PID-3`, `PID-5`, `PID-7`, `PID-8`), order details (`ORC-1`, `ORC-2`, `ORC-3`, `ORC-7`), procedure and modality attributes (`OBR-4`, `OBR-18`, `OBR-20`, `OBR-24`, `OBR-27`, `OBR-31`, `OBR-32`, `OBR-34`), and custom Study Instance UID (`ZDS-1`).
  - Enforced raw demographic preservation: ingested EHR/RIS demographics are injected directly into active Modality Worklist (MWL) entries without modification (no anonymization, no `GSH-` prefixes, no `_GSH` suffixes).
  - Implemented modality template validation: orders requesting modalities without available template images on disk (e.g. `PET`) are rejected with an MLLP `ACK` containing `MSA|AE|<MsgID>|Rejected: No template images available for modality '<MOD>'`.
  - Implemented active MWL order cancellation: messages with `ORC-1` in `CA`, `OC`, or `DC` locate and immediately purge matching active MWL entries.
  - Added REST management endpoints: `GET /api/v1/hl7/status`, `POST /api/v1/hl7/start`, `POST /api/v1/hl7/stop`, and `POST /api/v1/hl7/simulate`.
- **Zero-Dependency FHIR ServiceRequest & Bundle Ingestion Subsystem**:
  - Implemented RESTful endpoints (`POST /api/v1/fhir_service_request`, `POST /api/v1/fhir/Bundle`, and `POST /api/v1/fhir/ServiceRequest`) to ingest FHIR R4/R5 imaging order bundles.
  - Built zero-dependency FHIR parser using native Pydantic models resolving internal bundle references (`urn:uuid:...` and relative `Patient/123`), mapping `Patient`, `Practitioner`, and `ServiceRequest` attributes directly into active MWL entries.
  - Preserved raw patient demographics and accession identifiers without artificial modification.
  - Supported modality validation returning HTTP 422 with descriptive error messages when requested modalities lack template images.
  - Implemented order revocation: bundles containing ServiceRequests with `status` set to `revoked` or `entered-in-error` immediately purge matching active MWL entries.
- **Developer Testing Utilities (`util/`)**:
  - Added `push_hl7` Command Line Utility (`util/push_hl7.py`, `src/dicom_py_mock_server/utils/push_hl7.py`): Standalone, zero-dependency Python CLI tool to push HL7 messages over MLLP to the mock server (`127.0.0.1:2575`), featuring newline-to-CR normalization, MLLP framing, ACK parsing, and friendly formatted outputs.
  - Added console scripts `push-hl7` and `push_hl7` in `pyproject.toml` (`uv run push-hl7`).
  - Added sample HL7 `ORM^O01` message file `util/orm.txt`.
  - Added `push_fhir.sh` Shell Script (`util/push_fhir.sh`): Executable `curl` script to POST FHIR bundles to `/api/v1/fhir_service_request` with HTTP response validation and formatted JSON rendering via `jq`/`python3`.
  - Added sample FHIR imaging order bundle `util/fhir_order_bundle.json`.
- **Automated Multi-Slice Template, HL7 & FHIR Test Suites**:
  - Added `tests/test_template_datasets.py` with 9 test cases verifying root file rejection, mixed modality rejection, non-image object filtering, series grouping & slice sorting, non-synthetic exact delivery with sequential assignment, synthetic cyclic rotation with stress cloning, transfer syntax conversion logging with direct passthrough verification, non-synthetic Study Description preservation without mockup swapping, and repository template behavior (MR preservation vs CT mockup omission).
  - Added `tests/test_hl7_orm.py` with 8 test cases verifying ORM^O01 parsing, ACK construction, demographic preservation, template validation rejection, order cancellation, downstream DICOM synthesis, and live MLLP socket client communication.
  - Added `tests/test_fhir_service_request.py` with 7 test cases verifying CT/MR MWL creation, modality rejection, order cancellation/revocation, downstream DICOM synthesis, and REST endpoint behavior.
  - Added `tests/test_push_hl7.py` with 9 test cases verifying line normalization, ACK status parsing, default file lookup, live MLLP pushing, error handling, and CLI execution.
- **DICOM Conformance Statement (PS 3.2)**:
  - Added comprehensive, formal DICOM Conformance Statement (`docs/dicom_conformance_statement.md`) adhering to NEMA PS 3.2.
  - Documented supported DIMSE SOP classes (Verification, Patient/Study Root Query/Retrieve C-FIND & C-MOVE, Storage C-STORE SCP/SCU, Modality Worklist C-FIND).
  - Documented supported transfer syntaxes (RAW, JPEG Process 1, JPEG 2000 Lossless/Lossy, RLE Lossless), DICOMweb services (QIDO-RS, WADO-RS, WADO-URI), order ingestion protocols (HL7 v2 MLLP, FHIR ServiceRequest), and deterministic ITU-T X.667 `2.25.` UID generation.


### Fixed
- **DICOM Instance & MWL Date and Time Synchronization**:
  - Fixed an issue where synthesized DICOM instances retained historical template dates and times (e.g., from 2010/2011 template files) for Acquisition Date `(0008,0022)`, Content Date `(0008,0023)`, Series Date `(0008,0021)`, Series Time `(0008,0031)`, Scheduled Procedure Step Date/Time `(0040,0002)/(0040,0003)`, and Performed Procedure Step Date/Time `(0040,0244)/(0040,0245)`.
  - Implemented `DicomGeneratorService.sync_dicom_dates_and_times()` ensuring all date and time attributes across Study, Series, Acquisition, Content, and Procedure Steps (both top-level and sequence items) synchronize to the MWL scheduled study date and time across template synthesis, stress mode, and synthetic generation.
  - Added Scheduled Procedure Step End Date `(0040,0004)` and Scheduled Procedure Step End Time `(0040,0005)` to MWL JSON generation (`MwlGeneratorService.generate_json()`) and dataset conversion (`json_to_dataset()`).
  - Set top-level `StudyDate` and `StudyTime` on MWL datasets matching SPS start date and time.
  - Added unit test cases `test_mwl_generator_sps_and_study_dates`, `test_create_dicom_from_template_date_time_sync`, and `test_create_instances_from_mwl_date_time_sync`.
- **WADO-RS JPEG 2000 & RLE 16-bit Signed Frame Encoding**:
  - Fixed an issue in `DicomWebService.get_encoded_frames()` where CT and other 16-bit signed (`int16`, `PixelRepresentation=1`) datasets had their bit depth incorrectly calculated as 8-bit because `f_arr.dtype == np.uint16` evaluated to `False`. This caused OpenJPEG to encode only the top half of 512x512 images (resulting in a blank rectangular bottom half and truncated dynamic range) and caused RLE encoding to output an invalid single-segment count.
  - Corrected `BitsAllocated`, `BitsStored`, `HighBit`, and `PixelRepresentation` preservation and fallback calculation to fully support signed 16-bit CT/MR data for both `JPEG2000Lossless`/`JPEG2000` and `RLELossless`.
  - Added direct encapsulated frame passthrough: when the active dataset is already encapsulated in the requested transfer syntax, `get_encoded_frames()` extracts encapsulated frames directly via `generate_pixel_data_frame()` without performing redundant decompression and re-encoding.
  - Improved JPEG Baseline 8-bit transcoding for signed 16-bit datasets using dynamic range min-max scaling to `[0, 255]`.
  - Added automated test `test_wado_retrieve_ct_frames_j2k_and_rle_integrity` verifying full 512x512 resolution, `int16` range, and non-blank bottom half for both JPEG 2000 and RLE frames over WADO-RS.

## [0.2.3] - 2026-09-04

### Added
- **Flexible Delimiter Support in DICOMweb `Accept` Headers**:
  - Enhanced `DicomWebService.parse_transfer_syntax_header` to support both standard semicolon-delimited parameters (per DICOM PS3.18 / HTTP RFC 9110, e.g., `multipart/related; type="application/dicom"; transfer-syntax=...`) and comma-delimited parameters (e.g., `multipart/related, type="application/dicom", transfer-syntax=...`).
  - Added support for multi-valued transfer syntax candidate lists separated by either semicolons (`;`) or commas (`,`) within `transfer-syntax="..."` parameter values (e.g., `transfer-syntax="1.2.840.10008.1.2.4.90;1.2.840.10008.1.2.4.50"` or `transfer-syntax="1.2.840.10008.1.2.4.90, 1.2.840.10008.1.2.4.50"`).
  - Added support for semicolon- and comma-separated transfer syntax lists in direct request headers (`transfer-syntax`, `X-Transfer-Syntax`), query parameters (`?transferSyntax=UID1;UID2` / `?transferSyntax=UID1,UID2`), and direct `Accept` header values (e.g., `JPEG2000; RAW` or `JPEG2000, RAW`).
  - Added internal helper `_extract_candidates_from_list` for consistent tokenization and stripping of delimiter-separated syntax candidates.
  - Added automated test suite `test_wado_accept_header_semicolon_and_comma_separation` in `tests/test_dicomweb.py` covering standard semicolon, comma, and mixed delimiter headers, candidate lists, wildcard fallbacks, and end-to-end WADO-RS retrieval transcoding.

### Changed
- **De-Identification Documentation**:
  - Updated `README.md` to reference the [GoSmart.Health DICOM RS Transformer](https://github.com/gosmart-health/dicom-rs-transformer) for full standard-compliant DICOM de-identification workflows alongside the mock server.

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
