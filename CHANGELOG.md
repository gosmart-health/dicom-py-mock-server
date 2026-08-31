# Changelog

All notable changes to `dicom-py-mock-server` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> [!NOTE]
> **Source-Code Release Distribution**: Releases of `dicom-py-mock-server` are distributed strictly as source-code releases. No binary compilation or wheel build pipeline is required.

## [0.0.2] - 2026-08-30
- **Fixed Issue 5** Fixed the bug where C-FIND does not return all needed attributes.

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

