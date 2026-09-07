#!/usr/bin/env python3
"""Command Line Utility to push an HL7 v2 ORM message from a text file over MLLP."""

import runpy
import sys
from pathlib import Path

TARGET_UTIL = Path(__file__).resolve().parent.parent / "src" / "dicom_py_mock_server" / "utils" / "push_hl7.py"

if __name__ == "__main__":
    if TARGET_UTIL.is_file():
        mod = runpy.run_path(str(TARGET_UTIL))
        sys.exit(mod["main"]())
    else:
        print(f"Error: Could not find implementation file at {TARGET_UTIL}", file=sys.stderr)
        sys.exit(1)
