# dicom-py-mock-server

Generate mock DICOM objects and serve them over DIMSE, DICOMweb, and MCP, with HL7 and FHIR order integration.

> [!WARNING]
> This server has no authentication or authorization. Do not deploy it in production or expose it to untrusted networks.
>
> Template DICOM files are **not de-identified**. Other than replaced fields and pixel data, attributes including private data may pass through unchanged. Ensure templates contain no sensitive PHI.

## Quick start

```bash
./start.sh
```

For FHIR-driven worklists, use `./start-fhir.sh`. See the [user guide](docs/mkdocs/docs/user-guide.md) for configuration, Docker, endpoints, and examples.

## Documentation

- [User guide](docs/mkdocs/docs/user-guide.md)
- [DICOM conformance statement](docs/mkdocs/docs/dicom-conformance.md)
- [Design controls](docs/design/README.md)

The documentation site is configured for [gosmart.health/docs/dicom-py-mock-server](https://gosmart.health/docs/dicom-py-mock-server/). Preview or build it with Zensical from the project root:

```bash
uv run zensical serve -f docs/mkdocs/mkdocs.yml
uv run zensical build -f docs/mkdocs/mkdocs.yml
```

The generated site is written to `docs/mkdocs/site/`. See [CHANGELOG.md](CHANGELOG.md) for releases and [GitHub issues](https://github.com/gosmart-health/dicom-py-mock-server/issues) for support.
