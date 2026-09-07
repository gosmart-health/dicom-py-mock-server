"""Zero-dependency parser and generator for HL7 v2 messages (ORM^O01 and ACK)."""

from datetime import datetime
from typing import Any


class Hl7Message:
    """Represents a parsed HL7 v2 message."""

    def __init__(
        self,
        raw_text: str,
        field_sep: str = "|",
        comp_sep: str = "^",
        rep_sep: str = "~",
        subcomp_sep: str = "&",
    ) -> None:
        self.raw_text = raw_text
        self.field_sep = field_sep
        self.comp_sep = comp_sep
        self.rep_sep = rep_sep
        self.subcomp_sep = subcomp_sep
        self.segments: list[tuple[str, list[str]]] = []
        self._segment_map: dict[str, list[list[str]]] = {}

    def get_segment(self, name: str) -> list[str] | None:
        """Get the first segment with the given name."""
        segs = self._segment_map.get(name.upper())
        return segs[0] if segs else None

    def get_segments(self, name: str) -> list[list[str]]:
        """Get all segments with the given name."""
        return self._segment_map.get(name.upper(), [])

    def get_field(self, segment_name: str, field_index: int, default: str = "") -> str:
        """Get raw field string from the first matching segment by 1-based index."""
        seg = self.get_segment(segment_name)
        if not seg:
            return default
        if field_index < len(seg):
            return seg[field_index]
        return default

    def get_component(self, segment_name: str, field_index: int, comp_index: int, default: str = "") -> str:
        """Get component from a field by 1-based component index."""
        field_val = self.get_field(segment_name, field_index)
        if not field_val:
            return default
        comps = field_val.split(self.comp_sep)
        if 1 <= comp_index <= len(comps):
            return comps[comp_index - 1]
        return default


def parse_hl7_message(raw_msg: str | bytes) -> Hl7Message:
    """Parse an HL7 message into a structured Hl7Message object."""
    if isinstance(raw_msg, bytes):
        raw_text = raw_msg.decode("utf-8", errors="replace")
    else:
        raw_text = str(raw_msg)

    # Normalize line breaks: handle \r, \r\n, \n
    normalized = raw_text.replace("\r\n", "\r").replace("\n", "\r")
    lines = [line.strip() for line in normalized.split("\r") if line.strip()]

    if not lines:
        raise ValueError("Empty HL7 message")

    msh_line = lines[0]
    if not msh_line.startswith("MSH"):
        raise ValueError(f"HL7 message must begin with MSH segment, got: {msh_line[:10]}")

    field_sep = msh_line[3]
    encoding_chars = msh_line[4:8]
    comp_sep = encoding_chars[0] if len(encoding_chars) > 0 else "^"
    rep_sep = encoding_chars[1] if len(encoding_chars) > 1 else "~"
    subcomp_sep = encoding_chars[3] if len(encoding_chars) > 3 else "&"

    msg = Hl7Message(
        raw_text=raw_text,
        field_sep=field_sep,
        comp_sep=comp_sep,
        rep_sep=rep_sep,
        subcomp_sep=subcomp_sep,
    )

    for line in lines:
        if line.startswith("MSH"):
            # MSH field 1 is the separator itself, so MSH-2 is encoding characters
            parts = line.split(field_sep)
            # Reconstruct MSH fields list so index 1 = field_sep, index 2 = encoding_chars, index 3 = sending app
            msh_fields = ["MSH", field_sep] + parts[1:]
            msg.segments.append(("MSH", msh_fields))
            msg._segment_map.setdefault("MSH", []).append(msh_fields)
        else:
            parts = line.split(field_sep)
            seg_name = parts[0].upper()
            msg.segments.append((seg_name, parts))
            msg._segment_map.setdefault(seg_name, []).append(parts)

    return msg


def extract_hl7_orm_fields(msg: Hl7Message) -> dict[str, Any]:
    """Extract patient, procedure, order, and modality attributes from an ORM^O01 message."""
    # 1. MSH
    sending_app = msg.get_field("MSH", 3)
    sending_facility = msg.get_field("MSH", 4)
    message_type = msg.get_field("MSH", 9)
    message_control_id = msg.get_field("MSH", 10) or "UNKNOWN_MSG_ID"

    # 2. Patient Demographics (PID)
    # PID-3.1 (ID / MRN) or PID-2
    patient_id = msg.get_component("PID", 3, 1) or msg.get_field("PID", 2) or msg.get_field("PID", 3)
    # PID-5 (Name: Family^Given^Middle^Prefix^Suffix)
    pid_5 = msg.get_field("PID", 5)
    patient_name = pid_5.replace("^", "^").strip("^") if pid_5 else ""
    # PID-7 (Birth Date: YYYYMMDD...)
    dob_raw = msg.get_field("PID", 7)
    dob = dob_raw[:8] if len(dob_raw) >= 8 else dob_raw
    # PID-8 (Sex: M, F, O, U)
    sex = msg.get_field("PID", 8).upper()

    # 3. Order Control (ORC)
    order_control = msg.get_field("ORC", 1).upper() or "NW"
    placer_order_num = msg.get_component("ORC", 2, 1) or msg.get_field("ORC", 2)
    filler_order_num = msg.get_component("ORC", 3, 1) or msg.get_field("ORC", 3)

    # 4. Procedure & Modality (OBR)
    obr_accession = (
        msg.get_component("OBR", 20, 1)  # Filler Field 1
        or msg.get_component("OBR", 18, 1)  # Placer Field 1
        or msg.get_component("OBR", 3, 1)  # Filler Order Number
        or msg.get_component("OBR", 2, 1)  # Placer Order Number
        or filler_order_num
        or placer_order_num
    )
    accession = obr_accession or msg.get_field("ORC", 25)

    # Modality: OBR-24 (Diagnostic Serv Sect ID) or neighboring fields / text
    modality = msg.get_field("OBR", 24).strip().upper()
    if not modality:
        # Check neighboring fields 22..25 in case RIS off-by-one
        for f_idx in (23, 22, 25):
            val = msg.get_field("OBR", f_idx).strip().upper()
            if val in ("CT", "MR", "US", "DX", "CR", "XA", "NM", "PT", "PET", "MG", "RF"):
                modality = val
                break

    obr_4_text = msg.get_component("OBR", 4, 2) or msg.get_component("OBR", 4, 1)
    obr_31_reason = msg.get_field("OBR", 31)

    if not modality:
        # Check if modality keyword is in OBR-4 or OBR-31
        raw_words = f"{obr_4_text} {obr_31_reason}".upper().replace("^", " ").replace("/", " ").split()
        clean_words = [w.strip(".,;:()") for w in raw_words]
        for cand in ("PET", "PT", "CT", "MR", "US", "DX", "CR", "XA", "NM", "MG", "RF", "OT"):
            if cand in clean_words:
                modality = cand
                break
            if cand == "MR" and any(w in ("MRI", "MAGNETIC") or w.startswith("MR") for w in clean_words):
                modality = "MR"
                break
            if cand == "CT" and any(w.startswith("CT") for w in clean_words):
                modality = "CT"
                break

    if not modality:
        modality = "CT"

    study_description = obr_4_text or obr_31_reason or f"{modality} Procedure"

    # Physicians
    # Referring physician: PV1-8 or OBR-16 or ORC-12
    ref_phys_raw = msg.get_field("PV1", 8) or msg.get_field("OBR", 16) or msg.get_field("ORC", 12)
    referring_physician = _format_physician_name(ref_phys_raw, msg.comp_sep)

    # Performing physician: OBR-34
    perf_phys_raw = msg.get_field("OBR", 34)
    performing_physician = _format_physician_name(perf_phys_raw, msg.comp_sep)

    # Reading physician: OBR-32
    read_phys_raw = msg.get_field("OBR", 32)
    reading_physician = _format_physician_name(read_phys_raw, msg.comp_sep)

    # Timing / Scheduled Date & Time
    # OBR-27 or ORC-7 or current time
    scheduled_dt = _extract_hl7_datetime(msg.get_field("OBR", 27), msg.comp_sep)
    if not scheduled_dt:
        scheduled_dt = _extract_hl7_datetime(msg.get_field("ORC", 7), msg.comp_sep)

    # Study Instance UID: ZDS-1 if available
    study_uid = msg.get_component("ZDS", 1, 1) or msg.get_field("ZDS", 1) or None

    return {
        "message_control_id": message_control_id,
        "sending_application": sending_app,
        "sending_facility": sending_facility,
        "message_type": message_type,
        "order_control": order_control,
        "patient_id": patient_id,
        "patient_name": patient_name,
        "dob": dob,
        "sex": sex,
        "accession": accession,
        "modality": modality,
        "study_description": study_description,
        "reason": obr_31_reason or study_description,
        "referring_physician": referring_physician,
        "performing_physician": performing_physician,
        "reading_physician": reading_physician,
        "scheduled_at": scheduled_dt,
        "study_uid": study_uid,
    }


def _format_physician_name(raw_pn: str, comp_sep: str = "^") -> str:
    """Format HL7 physician composite (ID^Family^Given...) to Family^Given."""
    if not raw_pn:
        return ""
    comps = raw_pn.split(comp_sep)
    if len(comps) == 1:
        return comps[0]
    # Check if first component is numeric ID
    if comps[0].isalnum() and len(comps) > 1 and any(c.isalpha() for c in comps[1]):
        family = comps[1]
        given = comps[2] if len(comps) > 2 else ""
        return f"{family}^{given}".strip("^")
    family = comps[0]
    given = comps[1] if len(comps) > 1 else ""
    return f"{family}^{given}".strip("^")


def _extract_hl7_datetime(field_val: str, comp_sep: str = "^") -> datetime | None:
    """Extract datetime from composite HL7 field like TQ/timing or plain timestamp."""
    if not field_val:
        return None
    comps = field_val.split(comp_sep)
    for part in comps:
        cleaned = "".join(filter(str.isdigit, part))
        if len(cleaned) >= 8:
            try:
                if len(cleaned) >= 14:
                    return datetime.strptime(cleaned[:14], "%Y%m%d%H%M%S")
                return datetime.strptime(cleaned[:8], "%Y%m%d")
            except ValueError:
                continue
    return None


def build_hl7_ack(
    msh_fields: dict[str, Any] | Hl7Message,
    ack_code: str = "AA",
    text_message: str = "Success",
    app_name: str = "GOSMART_MWL",
    facility: str = "GOSMART_HOSP",
) -> str:
    """Construct standard HL7 v2 ACK message."""
    if isinstance(msh_fields, Hl7Message):
        ctrl_id = msh_fields.get_field("MSH", 10) or "UNKNOWN_MSG_ID"
        recv_app = msh_fields.get_field("MSH", 3) or "SENDER"
        recv_facility = msh_fields.get_field("MSH", 4) or "FACILITY"
    else:
        ctrl_id = msh_fields.get("message_control_id", "UNKNOWN_MSG_ID")
        recv_app = msh_fields.get("sending_application", "SENDER")
        recv_facility = msh_fields.get("sending_facility", "FACILITY")

    now_str = datetime.now().strftime("%Y%m%d%H%M%S")
    ack_ctrl_id = f"ACK-{ctrl_id}"

    msh = f"MSH|^~\\&|{app_name}|{facility}|{recv_app}|{recv_facility}|{now_str}||ACK^O01|{ack_ctrl_id}|P|2.3"
    msa = f"MSA|{ack_code}|{ctrl_id}|{text_message}"
    return f"{msh}\r{msa}\r"
