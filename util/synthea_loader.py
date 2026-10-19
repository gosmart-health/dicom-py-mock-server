#!/usr/bin/env python3
"""CLI utility to scan and load Synthea-generated FHIR R4 JSON files into the DICOM mock server."""

import argparse
import json
import os
import sys

import httpx
from fastapi.testclient import TestClient

from dicom_py_mock_server.main import app


def load(bundle_folder: str, url: str | None = None, chunk_size: int = 25) -> bool:
    """Scan a folder for Synthea FHIR JSON bundles and ingest them into the mock server.

    Prerequisite resource bundles (hospitals, practitioners) are posted first, followed
    by patient bundles in chunks of `chunk_size` (default: 25). If the live server is
    unreachable, falls back to in-process TestClient.

    Args:
        bundle_folder: Directory path containing Synthea FHIR JSON files.
        url: Base URL of the mock server. Defaults to $GOSMART_MS_BASE_URL or http://127.0.0.1:8000.
        chunk_size: Number of patient bundles to post per request (default: 25).

    Returns:
        True if all bundles loaded successfully; False if errors occurred.
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

    # Prefer calling the live running dicom-py-mock-server on http://127.0.0.1:8000
    # so its DICOM SCP listener (e.g. port 11112 / 11114) receives the Synthea patients/studies.
    if not url:
        url = os.environ.get("GOSMART_MS_BASE_URL", "http://127.0.0.1:8000")
    url = url.rstrip("/")

    try:
        health_resp = httpx.get(f"{url}/health", timeout=2.0)
        if health_resp.status_code == 200:
            client = httpx.Client(base_url=url, timeout=120.0)
            print(f"Connected to live server at {url}")
        else:
            client = TestClient(app)
            print(
                f"Live server at {url} returned HTTP {health_resp.status_code}; "
                "falling back to in-process TestClient(app)"
            )
    except Exception as exc:
        client = TestClient(app)
        print(f"Live server at {url} not reachable ({exc}); falling back to in-process TestClient(app)")

    resources: list[dict] = []
    patients: list[dict] = []
    scanned_count = 0
    parse_errors = 0

    try:
        file_list = sorted(os.listdir(bundle_folder))
    except OSError as exc:
        print(f"Error: Cannot list contents of directory '{bundle_folder}': {exc}", file=sys.stderr)
        return False

    for file_name in file_list:
        # Task: Check if the file contains .js else continue
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
            resources.append(js)
        else:
            patients.append(js)

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
    # TASK: Take an argument of --url <API base url> and --folder <folder path>
    # then call load() above
    parser = argparse.ArgumentParser(
        description="CLI utility to scan and load Synthea-generated FHIR JSON files into the DICOM mock server."
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
        help="DICOM mock server base URL (default: $GOSMART_MS_BASE_URL or http://127.0.0.1:8000).",
    )
    parser.add_argument(
        "--chunk-size",
        "-c",
        type=int,
        default=25,
        help="Number of patient bundles to post per request (default: 25).",
    )

    args = parser.parse_args(argv)
    success = load(bundle_folder=args.folder, url=args.url, chunk_size=args.chunk_size)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
