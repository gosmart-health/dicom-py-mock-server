#!/usr/bin/env python3
"""Utility script to download a DICOM study from DICOMweb WADO-RS and extract individual instances."""

import argparse
import io
import re
import sys
import urllib.request
from pathlib import Path


def download_study(
    study_uid: str,
    output_dir: str = "./received",
    transfer_syntax: str = "1.2.840.10008.1.2.4.50",
    server_url: str = "http://127.0.0.1:8000",
) -> list[Path]:
    """Download study from DICOMweb WADO-RS endpoint and extract individual .dcm files."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    base_url = server_url.rstrip("/")
    url = f"{base_url}/dicomweb/studies/{study_uid}"
    headers = {"Accept": f'multipart/related; type="application/dicom"; transfer-syntax="{transfer_syntax}"'}

    print(f"Connecting to: {url}")
    print(f"Requesting Transfer Syntax: {transfer_syntax}")
    print(f"Output Directory: {out_path.resolve()}")

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read()
    except Exception as exc:
        print(f"Error fetching study: {exc}", file=sys.stderr)
        sys.exit(1)

    boundary_match = re.search(r'boundary="?([^";,\s]+)"?', content_type)
    if not boundary_match:
        print(f"Error: No multipart boundary found in response Content-Type: {content_type}", file=sys.stderr)
        sys.exit(1)

    boundary = boundary_match.group(1).encode("utf-8")
    parts = body.split(b"--" + boundary)

    try:
        import pydicom
    except ImportError:
        pydicom = None

    saved_files: list[Path] = []
    for p in parts:
        p_strip = p.strip()
        if not p_strip or p_strip == b"--":
            continue
        if b"\r\n\r\n" in p_strip:
            _, raw = p_strip.split(b"\r\n\r\n", 1)
            if raw.endswith(b"\r\n"):
                raw = raw[:-2]

            file_name = None
            if pydicom is not None:
                try:
                    ds = pydicom.dcmread(io.BytesIO(raw), force=True)
                    sop_uid = str(getattr(ds, "SOPInstanceUID", f"instance_{len(saved_files) + 1:03d}"))
                    inst_num = getattr(ds, "InstanceNumber", len(saved_files) + 1)
                    file_name = out_path / f"instance_{int(inst_num):03d}_{sop_uid}.dcm"
                except Exception:
                    file_name = None

            if file_name is None:
                file_name = out_path / f"instance_{len(saved_files) + 1:03d}.dcm"

            file_name.write_bytes(raw)
            saved_files.append(file_name)

    print(f"Successfully extracted {len(saved_files)} DICOM instances into {out_path.resolve()}")
    return saved_files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download a DICOM study from DICOMweb WADO-RS into individual .dcm files."
    )
    parser.add_argument(
        "study_uid",
        nargs="?",
        default="2.25.162277523622777323928980372093016568091",
        help="StudyInstanceUID to retrieve (default: sample study UID)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="./received",
        help="Target folder to save individual .dcm files (default: ./received)",
    )
    parser.add_argument(
        "-t",
        "--transfer-syntax",
        default="1.2.840.10008.1.2.4.50",
        help="Requested Transfer Syntax UID or name (default: 1.2.840.10008.1.2.4.50 for JPEG Baseline)",
    )
    parser.add_argument(
        "-s",
        "--server",
        default="http://127.0.0.1:8000",
        help="Base DICOMweb server URL (default: http://127.0.0.1:8000)",
    )

    args = parser.parse_args()
    download_study(
        study_uid=args.study_uid,
        output_dir=args.output,
        transfer_syntax=args.transfer_syntax,
        server_url=args.server,
    )


if __name__ == "__main__":
    main()
