"""Command Line Utility to push HL7 v2 messages (ORM^O01) over MLLP to the mock server."""

import argparse
import os
import socket
import sys
from pathlib import Path

# MLLP Framing Bytes
MLLP_START_BLOCK = b"\x0b"  # <SB> (Vertical Tab 0x0B)
MLLP_END_BLOCK = b"\x1c\r"  # <EB><CR> (File Separator 0x1C + Carriage Return 0x0D)

DEFAULT_HOST = os.getenv("GOSMART_MS_HL7_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("GOSMART_MS_HL7_PORT", "2575"))
DEFAULT_TIMEOUT = 5.0


def normalize_hl7_message(raw_text: str) -> str:
    """Normalize line endings to standard HL7 segment terminator (CR / \\r)."""
    # Replace \r\n and \n with \r
    normalized = raw_text.replace("\r\n", "\r").replace("\n", "\r")
    # Filter out empty lines and rejoin with \r
    segments = [seg.strip() for seg in normalized.split("\r") if seg.strip()]
    if not segments:
        raise ValueError("Empty HL7 message or file contains no segments")
    return "\r".join(segments) + "\r"


def parse_ack_status(ack_text: str) -> tuple[str, str, str]:
    """Extract ACK code (AA, AE, AR), message control ID, and text message from MSA segment."""
    normalized = ack_text.replace("\r\n", "\r").replace("\n", "\r")
    segments = [seg.strip() for seg in normalized.split("\r") if seg.strip()]

    ack_code = "UNKNOWN"
    msg_id = ""
    comment = ""

    for seg in segments:
        if seg.startswith("MSA"):
            fields = seg.split("|")
            if len(fields) > 1:
                ack_code = fields[1].strip()
            if len(fields) > 2:
                msg_id = fields[2].strip()
            if len(fields) > 3:
                comment = fields[3].strip()
            break

    return ack_code, msg_id, comment


def send_hl7_mllp(raw_msg: str, host: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Send an HL7 message string over TCP wrapped in standard MLLP framing and return response."""
    normalized = normalize_hl7_message(raw_msg)
    framed_request = MLLP_START_BLOCK + normalized.encode("utf-8") + MLLP_END_BLOCK

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.sendall(framed_request)

        buffer = bytearray()
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            if MLLP_END_BLOCK in buffer:
                break

    sb_idx = buffer.find(MLLP_START_BLOCK)
    eb_idx = buffer.find(MLLP_END_BLOCK)

    if sb_idx == -1 or eb_idx == -1:
        # If response was not framed or connection closed abruptly
        raw_decoded = buffer.decode("utf-8", errors="replace")
        raise ConnectionError(f"Malformed or missing MLLP framing from server: {raw_decoded!r}")

    payload = buffer[sb_idx + 1 : eb_idx]
    return payload.decode("utf-8", errors="replace")


def find_default_orm_file() -> Path | None:
    """Attempt to locate a default orm.txt file from working directory or repo root."""
    cwd = Path.cwd()
    candidates = [
        cwd / "util" / "orm.txt",
        cwd / "orm.txt",
        Path(__file__).resolve().parent.parent.parent.parent / "util" / "orm.txt",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand.resolve()
    return None


def push_hl7_file(
    file_path: Path,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_TIMEOUT,
    verbose: bool = False,
) -> tuple[int, str]:
    """Read HL7 file, send over MLLP to target host:port, and return (exit_code, ack_text)."""
    if not file_path.is_file():
        raise FileNotFoundError(f"HL7 message file not found: {file_path}")

    content = file_path.read_text(encoding="utf-8")
    if not content.strip().startswith("MSH"):
        raise ValueError(f"File {file_path} does not appear to contain a valid HL7 message starting with 'MSH'")

    if verbose:
        print(f"Connecting to {host}:{port} (timeout={timeout}s)...")
        print(f"Sending payload from {file_path}:\n{content.strip()}\n")

    ack_text = send_hl7_mllp(content, host=host, port=port, timeout=timeout)
    ack_code, msg_id, comment = parse_ack_status(ack_text)

    if verbose:
        print(f"Received ACK:\n{ack_text.strip()}\n")

    if ack_code == "AA":
        print(f"[OK] HL7 message delivered successfully to {host}:{port}")
        print(f"     ACK Status : {ack_code} (Application Accept)")
        if msg_id:
            print(f"     Message ID : {msg_id}")
        if comment:
            print(f"     Details    : {comment}")
        return 0, ack_text
    else:
        print(f"[REJECTED] Server rejected message with ACK status: {ack_code}")
        if msg_id:
            print(f"           Message ID : {msg_id}")
        if comment:
            print(f"           Reason     : {comment}")
        return 1, ack_text


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for push_hl7 utility."""
    parser = argparse.ArgumentParser(
        prog="push_hl7",
        description="Push an HL7 v2 ORM message from a text file to the DICOM mock server's MLLP listener.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to HL7 message file (defaults to util/orm.txt)",
    )
    parser.add_argument(
        "-H",
        "--host",
        default=DEFAULT_HOST,
        help=f"HL7 MLLP server host (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"HL7 MLLP server TCP port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Socket timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output showing raw payload and ACK responses",
    )

    args = parser.parse_args(argv)

    # Determine target file
    if args.file:
        target_path = Path(args.file)
    else:
        default_file = find_default_orm_file()
        if not default_file:
            print(
                "Error: No HL7 message file provided and default 'util/orm.txt' could not be found.\n"
                "Please specify a path to an HL7 text file: push_hl7 path/to/orm.txt",
                file=sys.stderr,
            )
            return 1
        target_path = default_file

    try:
        exit_code, _ = push_hl7_file(
            file_path=target_path,
            host=args.host,
            port=args.port,
            timeout=args.timeout,
            verbose=args.verbose,
        )
        return exit_code
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (ConnectionRefusedError, TimeoutError, socket.gaierror) as exc:
        print(
            f"Connection Error: Could not connect to HL7 server at {args.host}:{args.port} ({exc}).\n"
            "Ensure the DICOM mock server is running and HL7 MLLP is enabled.",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
