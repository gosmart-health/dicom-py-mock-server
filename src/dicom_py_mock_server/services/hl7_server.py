"""Non-blocking asyncio MLLP TCP Server for receiving HL7 v2 messages and generating MWL entries."""

import asyncio
from typing import Any

import structlog

from dicom_py_mock_server.config import AppConfig
from dicom_py_mock_server.config import config as global_config
from dicom_py_mock_server.services.hl7_parser import build_hl7_ack, extract_hl7_orm_fields, parse_hl7_message
from dicom_py_mock_server.services.mwl_generator import MwlGeneratorService

logger = structlog.get_logger(__name__)

# MLLP Framing Bytes
MLLP_START_BLOCK = b"\x0b"  # <SB> (Vertical Tab 0x0B)
MLLP_END_BLOCK = b"\x1c\r"  # <EB><CR> (File Separator 0x1C + Carriage Return 0x0D)


class Hl7MllpServer:
    """Non-blocking asyncio MLLP TCP server for HL7 v2 communication."""

    def __init__(
        self,
        mwl_service: MwlGeneratorService,
        app_config: AppConfig | None = None,
    ) -> None:
        self.mwl_service = mwl_service
        self.config = app_config or global_config
        self.host = self.config.hl7_host
        self.port = self.config.hl7_port
        self.app_name = self.config.hl7_app_name
        self.facility = self.config.hl7_facility

        self.server: asyncio.Server | None = None
        self.is_running = False
        self.messages_received = 0
        self.messages_processed = 0
        self.messages_rejected = 0

    def process_raw_message(self, raw_text: str) -> tuple[dict[str, Any], str]:
        """Process a raw HL7 message string, update MWL, and return (summary, ack_string)."""
        self.messages_received += 1

        # Debug-level dump of raw payload
        logger.debug("hl7_raw_message_dump", raw_payload=raw_text)

        try:
            msg = parse_hl7_message(raw_text)
            fields = extract_hl7_orm_fields(msg)
        except Exception as exc:
            self.messages_rejected += 1
            err_msg = f"Failed to parse HL7 message: {exc!s}"
            logger.error("hl7_message_parse_failed", error=str(exc))
            ack = build_hl7_ack(
                {"message_control_id": "UNKNOWN"},
                ack_code="AE",
                text_message=err_msg,
                app_name=self.app_name,
                facility=self.facility,
            )
            return {"status": "rejected", "error": err_msg}, ack

        # Log high-level summary at INFO level
        logger.info(
            "hl7_message_received",
            order_control=fields["order_control"],
            patient_id=fields["patient_id"],
            patient_name=fields["patient_name"],
            accession=fields["accession"],
            modality=fields["modality"],
            message_control_id=fields["message_control_id"],
        )

        order_control = fields["order_control"]

        # Order Cancellation
        if order_control in ("CA", "OC", "DC"):
            removed_count = self.mwl_service.remove_entry(
                accession=fields["accession"],
                study_uid=fields.get("study_uid"),
                patient_id=fields["patient_id"],
            )
            self.messages_processed += 1
            logger.info(
                "hl7_order_cancelled",
                accession=fields["accession"],
                removed_entries=removed_count,
            )
            ack = build_hl7_ack(
                fields,
                ack_code="AA",
                text_message=f"Order cancelled. Removed {removed_count} active MWL entries.",
                app_name=self.app_name,
                facility=self.facility,
            )
            return {
                "status": "cancelled",
                "removed_entries": removed_count,
                "fields": fields,
            }, ack

        # Modality Validation: check if template images exist for the requested modality
        requested_modality = fields.get("modality", "").upper()
        if not self.mwl_service.has_modality_template(requested_modality):
            self.messages_rejected += 1
            rejection_text = f"Rejected: No template images available for modality '{requested_modality}'"
            logger.warning(
                "hl7_modality_rejected_no_template",
                modality=requested_modality,
                patient_id=fields["patient_id"],
                accession=fields["accession"],
                available_modalities=self.mwl_service.get_template_modalities(),
            )
            ack = build_hl7_ack(
                fields,
                ack_code="AE",
                text_message=rejection_text,
                app_name=self.app_name,
                facility=self.facility,
            )
            return {
                "status": "rejected",
                "error": rejection_text,
                "fields": fields,
            }, ack

        # Create MWL entry with raw, unaltered demographics (no anonymization or _GSH suffix)
        custom_dict: dict[str, Any] = {
            "patientName": fields["patient_name"],
            "patientId": fields["patient_id"],
            "mrn": fields["patient_id"],
            "dob": fields["dob"],
            "sex": fields["sex"],
            "gender": fields["sex"],
            "modality": requested_modality,
            "accession": fields["accession"],
            "studyDescription": fields["study_description"],
            "reason": fields["reason"],
            "referringPhysician": fields["referring_physician"],
            "performingPhysician": fields["performing_physician"],
            "readingPhysician": fields["reading_physician"],
        }
        if fields.get("study_uid"):
            custom_dict["studyUid"] = fields["study_uid"]
        if fields.get("scheduled_at"):
            custom_dict["studyDate"] = fields["scheduled_at"]

        entry = self.mwl_service.add_entry(
            custom=custom_dict,
            scheduled_at=fields.get("scheduled_at"),
        )
        if not entry:
            self.messages_rejected += 1
            err_msg = f"Failed to generate MWL entry for modality '{requested_modality}'"
            logger.error("hl7_mwl_creation_failed", modality=requested_modality)
            ack = build_hl7_ack(
                fields,
                ack_code="AE",
                text_message=err_msg,
                app_name=self.app_name,
                facility=self.facility,
            )
            return {"status": "failed", "error": err_msg, "fields": fields}, ack

        self.messages_processed += 1
        logger.info(
            "hl7_mwl_entry_created",
            accession=entry["accession"],
            patient_id=entry["patient_id"],
            modality=entry["modality"],
            study_uid=entry["study_uid"],
        )
        ack = build_hl7_ack(
            fields,
            ack_code="AA",
            text_message="Order received and MWL entry created successfully",
            app_name=self.app_name,
            facility=self.facility,
        )
        return {
            "status": "created",
            "entry": {
                "patient_id": entry["patient_id"],
                "patient_name": entry["patient_name"],
                "accession": entry["accession"],
                "modality": entry["modality"],
                "study_uid": entry["study_uid"],
            },
            "fields": fields,
        }, ack

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle an incoming TCP connection running MLLP protocol."""
        peer = writer.get_extra_info("peername")
        logger.info("hl7_client_connected", peer=peer)

        buffer = bytearray()
        try:
            while not reader.at_eof():
                chunk = await reader.read(4096)
                if not chunk:
                    break
                buffer.extend(chunk)

                # Process all complete MLLP frames in buffer
                while True:
                    sb_idx = buffer.find(MLLP_START_BLOCK)
                    if sb_idx == -1:
                        # No start block found, discard noise
                        buffer.clear()
                        break

                    eb_idx = buffer.find(MLLP_END_BLOCK, sb_idx + 1)
                    if eb_idx == -1:
                        # Message still in transit, keep waiting for end block
                        if sb_idx > 0:
                            buffer = buffer[sb_idx:]
                        break

                    # Complete frame extracted
                    payload_bytes = buffer[sb_idx + 1 : eb_idx]
                    buffer = buffer[eb_idx + len(MLLP_END_BLOCK) :]

                    raw_text = payload_bytes.decode("utf-8", errors="replace")
                    _, ack_str = self.process_raw_message(raw_text)

                    # Wrap and send MLLP ACK frame
                    ack_frame = MLLP_START_BLOCK + ack_str.encode("utf-8") + MLLP_END_BLOCK
                    writer.write(ack_frame)
                    await writer.drain()

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("hl7_client_connection_error", peer=peer, error=str(exc))
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info("hl7_client_disconnected", peer=peer)

    async def start(self) -> dict[str, Any]:
        """Start the MLLP TCP listener server."""
        if self.is_running and self.server:
            return self.get_status()

        try:
            self.server = await asyncio.start_server(
                self._handle_client,
                host=self.host,
                port=self.port,
            )
            self.is_running = True
            logger.info(
                "hl7_mllp_server_started",
                host=self.host,
                port=self.port,
                app_name=self.app_name,
                facility=self.facility,
            )
        except Exception as exc:
            logger.error("hl7_mllp_server_start_failed", error=str(exc))
            raise exc

        return self.get_status()

    async def stop(self) -> dict[str, Any]:
        """Stop the MLLP TCP listener server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        self.is_running = False
        logger.info("hl7_mllp_server_stopped", port=self.port)
        return self.get_status()

    def get_status(self) -> dict[str, Any]:
        """Get current status and telemetry of HL7 server."""
        return {
            "is_running": self.is_running,
            "host": self.host,
            "port": self.port,
            "app_name": self.app_name,
            "facility": self.facility,
            "messages_received": self.messages_received,
            "messages_processed": self.messages_processed,
            "messages_rejected": self.messages_rejected,
        }
