#!/usr/bin/env python3
"""CLI utility to scan and load Synthea-generated FHIR R4 JSON files into DICOM mock server or HAPI FHIR."""

import argparse
import json
import os
import sys

import httpx
from fastapi.testclient import TestClient


def resolve_hapi_fhir_base_url(url: str, client: httpx.Client | None = None) -> str:
    """Normalize and resolve the FHIR base URL for a HAPI FHIR server.

    If given a root URL (e.g. http://host:port), checks whether /metadata or /fhir/metadata
    serves the CapabilityStatement and returns the working base URL.
    """
    clean_url = url.rstrip("/")
    if clean_url.endswith("/fhir"):
        return clean_url

    local_client = client or httpx.Client(timeout=5.0)
    try:
        # Check if clean_url directly serves CapabilityStatement
        resp = local_client.get(f"{clean_url}/metadata")
        if resp.status_code == 200:
            return clean_url
    except Exception:
        pass

    try:
        # Check if clean_url/fhir serves CapabilityStatement
        resp = local_client.get(f"{clean_url}/fhir/metadata")
        if resp.status_code == 200:
            return f"{clean_url}/fhir"
    except Exception:
        pass
    finally:
        if client is None:
            local_client.close()

    # Fallback default convention for HAPI FHIR
    return f"{clean_url}/fhir"


def scan_bundles(
    bundle_folder: str,
) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]], int, int] | None:
    """Scan a directory for Synthea FHIR JSON files.

    Returns:
        A tuple of (resources, patients, scanned_count, parse_errors), or None if folder cannot be listed.
    """
    try:
        file_list = sorted(os.listdir(bundle_folder))
    except OSError as exc:
        print(f"Error: Cannot list contents of directory '{bundle_folder}': {exc}", file=sys.stderr)
        return None

    resources: list[tuple[str, dict]] = []
    patients: list[tuple[str, dict]] = []
    scanned_count = 0
    parse_errors = 0

    for file_name in file_list:
        if ".js" not in file_name.lower():
            continue

        file_path = os.path.join(bundle_folder, file_name)
        if not os.path.isfile(file_path):
            continue

        scanned_count += 1
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                js = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            print(f"Error: Failed to read/parse JSON from '{file_name}': {exc}", file=sys.stderr)
            parse_errors += 1
            continue

        name_lower = file_name.lower()
        if "hospital" in name_lower or "resource" in name_lower or "practitioner" in name_lower:
            resources.append((file_name, js))
        else:
            patients.append((file_name, js))

    return resources, patients, scanned_count, parse_errors


def load_to_hapi_fhir(
    bundle_folder: str,
    url: str | None = None,
    client: httpx.Client | None = None,
) -> bool:
    """Scan a folder for Synthea FHIR JSON bundles and ingest each into HAPI FHIR server.

    Prerequisite resource bundles (hospitals, practitioners) are posted first as individual
    transaction/batch bundles, followed by individual patient transaction bundles.

    Args:
        bundle_folder: Directory path containing Synthea FHIR JSON files.
        url: Base URL of the HAPI FHIR server. Defaults to $HAPI_FHIR_URL or http://10.200.0.103:8087/fhir.
        client: Optional httpx.Client instance for testing or custom configuration.

    Returns:
        True if all bundles loaded successfully; False if any errors occurred.
    """
    if not bundle_folder:
        print("Error: Bundle folder path must be specified.", file=sys.stderr)
        return False

    if not os.path.exists(bundle_folder):
        print(f"Error: Bundle folder does not exist: {bundle_folder}", file=sys.stderr)
        return False

    if not os.path.isdir(bundle_folder):
        print(f"Error: Path is not a directory: {bundle_folder}", file=sys.stderr)
        return False

    if not url:
        url = os.environ.get("HAPI_FHIR_URL", "http://10.200.0.103:8087/fhir")

    fhir_base = resolve_hapi_fhir_base_url(url, client=client)
    close_client = False
    if client is None:
        client = httpx.Client(base_url=fhir_base, timeout=300.0)
        close_client = True

    try:
        # Check connectivity to HAPI FHIR CapabilityStatement
        cap_resp = client.get(f"{fhir_base}/metadata")
        if cap_resp.status_code == 200:
            print(f"Connected to HAPI FHIR server at {fhir_base}")
        else:
            print(
                f"Warning: HAPI FHIR metadata endpoint at {fhir_base}/metadata returned HTTP {cap_resp.status_code}.",
                file=sys.stderr,
            )
    except Exception as exc:
        print(f"Error: Cannot connect to HAPI FHIR server at {fhir_base}: {exc}", file=sys.stderr)
        if close_client:
            client.close()
        return False

    scan_result = scan_bundles(bundle_folder)
    if scan_result is None:
        if close_client:
            client.close()
        return False

    resources, patients, scanned_count, parse_errors = scan_result
    print(
        f"Scanned {scanned_count} JSON file(s) from '{bundle_folder}': "
        f"{len(resources)} resource bundle(s), {len(patients)} patient bundle(s), "
        f"{parse_errors} parse error(s)."
    )

    if not resources and not patients:
        print("Warning: No valid Synthea FHIR JSON bundles found to load.", file=sys.stderr)
        if close_client:
            client.close()
        return parse_errors == 0

    headers = {
        "Content-Type": "application/fhir+json",
        "Accept": "application/fhir+json",
    }
    overall_success = parse_errors == 0
    loaded_resources = 0
    loaded_patients = 0

    try:
        # 1. Post prerequisite resources (hospitals, practitioners)
        if resources:
            print(f"Posting {len(resources)} prerequisite resource bundle(s) (hospitals/practitioners)...")
            for idx, (file_name, js) in enumerate(resources, start=1):
                try:
                    resp = client.post(fhir_base, json=js, headers=headers)
                    if resp.status_code in (200, 201):
                        loaded_resources += 1
                        print(
                            f"  [{idx}/{len(resources)}] Successfully loaded prerequisite '{file_name}' "
                            f"(HTTP {resp.status_code})."
                        )
                    else:
                        print(
                            f"  [{idx}/{len(resources)}] Error loading '{file_name}': "
                            f"HTTP {resp.status_code} - {resp.text[:300]}",
                            file=sys.stderr,
                        )
                        overall_success = False
                except Exception as exc:
                    print(
                        f"  [{idx}/{len(resources)}] Exception posting '{file_name}': {exc}",
                        file=sys.stderr,
                    )
                    overall_success = False
        else:
            print("Notice: No prerequisite resource bundles (hospitals/practitioners) found in folder.")

        # 2. Post patient bundles
        if patients:
            print(f"Posting {len(patients)} patient bundle(s)...")
            for idx, (file_name, js) in enumerate(patients, start=1):
                try:
                    resp = client.post(fhir_base, json=js, headers=headers)
                    if resp.status_code in (200, 201):
                        loaded_patients += 1
                        print(
                            f"  [{idx}/{len(patients)}] Successfully loaded patient bundle '{file_name}' "
                            f"(HTTP {resp.status_code})."
                        )
                    else:
                        print(
                            f"  [{idx}/{len(patients)}] Error loading patient bundle '{file_name}': "
                            f"HTTP {resp.status_code} - {resp.text[:300]}",
                            file=sys.stderr,
                        )
                        overall_success = False
                except Exception as exc:
                    print(
                        f"  [{idx}/{len(patients)}] Exception posting patient bundle '{file_name}': {exc}",
                        file=sys.stderr,
                    )
                    overall_success = False
        else:
            print("Notice: No patient bundles found to load.")

        print(
            f"HAPI FHIR Load Summary: {loaded_resources}/{len(resources)} prerequisite bundle(s) loaded, "
            f"{loaded_patients}/{len(patients)} patient bundle(s) loaded."
        )
    finally:
        if close_client:
            client.close()

    return overall_success


def load(
    bundle_folder: str,
    url: str | None = None,
    chunk_size: int = 25,
    hapi_fhir: bool = False,
    client: httpx.Client | None = None,
) -> bool:
    """Scan a folder for Synthea FHIR JSON bundles and ingest them.

    When `hapi_fhir=True`, ingests each bundle individually into the target HAPI FHIR server.
    When `hapi_fhir=False` (default), ingests bundles into the DICOM mock server using batch chunks
    and falls back to in-process TestClient if the live server is unreachable.

    Args:
        bundle_folder: Directory path containing Synthea FHIR JSON files.
        url: Base URL of the target server.
        chunk_size: Number of patient bundles to post per request in mock server mode (default: 25).
        hapi_fhir: Whether to load to a standard HAPI FHIR server.
        client: Optional httpx.Client instance.

    Returns:
        True if all bundles loaded successfully; False if errors occurred.
    """
    if hapi_fhir:
        return load_to_hapi_fhir(bundle_folder=bundle_folder, url=url, client=client)

    if not bundle_folder:
        print("Error: Bundle folder path must be specified.", file=sys.stderr)
        return False

    if not os.path.exists(bundle_folder):
        print(f"Error: Bundle folder does not exist: {bundle_folder}", file=sys.stderr)
        return False

    if not os.path.isdir(bundle_folder):
        print(f"Error: Path is not a directory: {bundle_folder}", file=sys.stderr)
        return False

    # Prefer calling the live running dicom-py-mock-server on http://127.0.0.1:8000
    # so its DICOM SCP listener (e.g. port 11112 / 11114) receives the Synthea patients/studies.
    if not url:
        url = os.environ.get("GOSMART_MS_BASE_URL", "http://127.0.0.1:8000")
    url = url.rstrip("/")

    if client is None:
        try:
            health_resp = httpx.get(f"{url}/health", timeout=2.0)
            if health_resp.status_code == 200:
                client = httpx.Client(base_url=url, timeout=120.0)
                print(f"Connected to live server at {url}")
            else:
                from dicom_py_mock_server.main import app

                client = TestClient(app)
                print(
                    f"Live server at {url} returned HTTP {health_resp.status_code}; "
                    "falling back to in-process TestClient(app)"
                )
        except Exception as exc:
            from dicom_py_mock_server.main import app

            client = TestClient(app)
            print(f"Live server at {url} not reachable ({exc}); falling back to in-process TestClient(app)")

    scan_result = scan_bundles(bundle_folder)
    if scan_result is None:
        return False

    resources_with_names, patients_with_names, scanned_count, parse_errors = scan_result
    resources = [b[1] for b in resources_with_names]
    patients = [b[1] for b in patients_with_names]

    print(
        f"Scanned {scanned_count} JSON file(s) from '{bundle_folder}': "
        f"{len(resources)} resource bundle(s), {len(patients)} patient bundle(s), "
        f"{parse_errors} parse error(s)."
    )

    if not resources and not patients:
        print("Warning: No valid Synthea FHIR JSON bundles found to load.", file=sys.stderr)
        return parse_errors == 0

    overall_success = parse_errors == 0

    if resources:
        print(f"Posting {len(resources)} prerequisite resource bundle(s) (hospitals/practitioners)...")
        try:
            resp = client.post("/api/v1/synthea/load", json=resources)
            if resp.status_code == 200:
                print(f"Successfully loaded {len(resources)} resource bundle(s).")
            else:
                print(f"Error loading resource bundles: HTTP {resp.status_code} - {resp.text}", file=sys.stderr)
                overall_success = False
        except Exception as exc:
            print(f"Error posting resource bundles: {exc}", file=sys.stderr)
            overall_success = False
    else:
        print("Notice: No prerequisite resource bundles (hospitals/practitioners) found in folder.")

    if patients:
        effective_chunk_size = chunk_size if chunk_size > 0 else 25
        total_patients = len(patients)
        total_chunks = (total_patients + effective_chunk_size - 1) // effective_chunk_size
        total_imaging_generated = 0

        print(
            f"Posting {total_patients} patient bundle(s) in {total_chunks} chunk(s) "
            f"(chunk size: {effective_chunk_size})..."
        )

        for chunk_idx, i in enumerate(range(0, total_patients, effective_chunk_size), start=1):
            chunk = patients[i : i + effective_chunk_size]
            print(f"Posting patient chunk {chunk_idx}/{total_chunks} ({len(chunk)} bundle(s))...")
            try:
                resp = client.post("/api/v1/synthea/load", json=chunk)
                if resp.status_code == 200:
                    result_data = resp.json()
                    total_imaging_generated += len(result_data)
                    print(
                        f"Successfully loaded chunk {chunk_idx}/{total_chunks}: "
                        f"{len(chunk)} patient bundle(s) ({len(result_data)} imaging bundle(s) generated)."
                    )
                else:
                    print(
                        f"Error loading patient chunk {chunk_idx}/{total_chunks}: "
                        f"HTTP {resp.status_code} - {resp.text}",
                        file=sys.stderr,
                    )
                    overall_success = False
            except Exception as exc:
                print(
                    f"Error posting patient chunk {chunk_idx}/{total_chunks}: {exc}",
                    file=sys.stderr,
                )
                overall_success = False

        if overall_success:
            print(
                f"Successfully loaded all {total_patients} patient bundle(s) "
                f"({total_imaging_generated} total imaging bundle(s) generated)."
            )
    else:
        print("Notice: No patient bundles found to load.")

    return overall_success


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and load Synthea FHIR bundles."""
    parser = argparse.ArgumentParser(
        description="CLI utility to scan and load Synthea FHIR JSON files into DICOM mock server or HAPI FHIR."
    )
    parser.add_argument(
        "--folder",
        "-f",
        required=True,
        help="Path to folder containing Synthea FHIR JSON files.",
    )
    parser.add_argument(
        "--url",
        "-u",
        default=None,
        help=(
            "Target server base URL. "
            "For mock server: defaults to $GOSMART_MS_BASE_URL or http://127.0.0.1:8000. "
            "For HAPI FHIR: defaults to $HAPI_FHIR_URL or http://10.200.0.103:8087/fhir."
        ),
    )
    parser.add_argument(
        "--chunk-size",
        "-c",
        type=int,
        default=25,
        help="Number of patient bundles to post per request in mock server mode (default: 25).",
    )
    parser.add_argument(
        "--hapi-fhir",
        "--hapi_fhir",
        action="store_true",
        dest="hapi_fhir",
        help="Load bundles into a standard HAPI FHIR server instead of the DICOM mock server.",
    )

    args = parser.parse_args(argv)
    success = load(
        bundle_folder=args.folder,
        url=args.url,
        chunk_size=args.chunk_size,
        hapi_fhir=args.hapi_fhir,
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
