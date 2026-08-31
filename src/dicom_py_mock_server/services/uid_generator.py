"""Deterministic DICOM UID Generator adhering to ITU-T X.667 / ISO/IEC 9834-8 (2.25.<u128>)."""

import uuid
from typing import Any

from dicom_py_mock_server.config import config

# Default persistent application namespace UUID (RFC 4122 DNS namespace or custom)
DEFAULT_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
DICOM_UID_ROOT = "2.25"


def uuid_to_dicom_uid(u: uuid.UUID) -> str:
    """Convert a 128-bit UUID into an ITU-T X.667 / ISO/IEC 9834-8 compliant DICOM UID string.

    The standard specifies representing UUIDs as an OSI OID under the 2.25 arc
    formatted as 2.25.<decimal-representation-of-128bit-integer>.
    Max length: '2.25.' (5) + up to 39 decimal digits = 44 characters (<= 64 chars DICOM VR UI limit).
    """
    return f"{DICOM_UID_ROOT}.{u.int}"


def dicom_uid_to_uuid(dicom_uid: str) -> uuid.UUID:
    """Parse an ITU-T X.667 2.25.<u128> DICOM UID back into a Python uuid.UUID instance."""
    prefix = f"{DICOM_UID_ROOT}."
    if not dicom_uid.startswith(prefix):
        raise ValueError(f"Invalid DICOM UUID prefix for '{dicom_uid}', expected root '{prefix}'")
    int_str = dicom_uid[len(prefix) :]
    return uuid.UUID(int=int(int_str))


def _resolve_namespace(namespace: uuid.UUID | str | None) -> uuid.UUID:
    """Resolve namespace parameter to a valid uuid.UUID."""
    if isinstance(namespace, uuid.UUID):
        return namespace
    if isinstance(namespace, str) and namespace.strip():
        return uuid.UUID(namespace.strip())
    config_ns = getattr(config, "dicom_namespace_uuid", None)
    if config_ns:
        if isinstance(config_ns, uuid.UUID):
            return config_ns
        return uuid.UUID(str(config_ns).strip())
    return DEFAULT_NAMESPACE


def generate_deterministic_uid(
    name: str,
    namespace: uuid.UUID | str | None = None,
    version: int | None = None,
) -> str:
    """Generate a deterministic ITU-T X.667 / ISO/IEC 9834-8 DICOM UID under root 2.25.

    Uses UUIDv5 (SHA-1 hashing) by default or UUIDv3 (MD5 hashing).
    """
    ns = _resolve_namespace(namespace)
    ver = version if version is not None else getattr(config, "dicom_uid_version", 5)

    if ver == 3:
        u = uuid.uuid3(ns, name)
    elif ver == 5:
        u = uuid.uuid5(ns, name)
    else:
        raise ValueError(f"Unsupported UUID version {ver}. Only Version 5 (SHA-1) and Version 3 (MD5) are supported.")

    return uuid_to_dicom_uid(u)


def generate_study_uid(
    patient_name: Any = None,
    patient_id: Any = None,
    accession_number: Any = None,
    namespace: uuid.UUID | str | None = None,
    version: int | None = None,
) -> str:
    """Generate a deterministic StudyInstanceUID from PatientName, PatientID, and AccessionNumber.

    If all parameters are empty/missing, generates a unique random UUIDv4 under root 2.25.
    """
    p_name = str(patient_name or "").strip()
    p_id = str(patient_id or "").strip()
    acc = str(accession_number or "").strip()

    if not p_name and not p_id and not acc:
        return uuid_to_dicom_uid(uuid.uuid4())

    seed = f"study:{p_name}:{p_id}:{acc}"
    return generate_deterministic_uid(seed, namespace=namespace, version=version)


def generate_series_uid(
    study_uid: str,
    series_number: int | str = 1,
    namespace: uuid.UUID | str | None = None,
    version: int | None = None,
) -> str:
    """Generate a deterministic SeriesInstanceUID from StudyInstanceUID and SeriesNumber."""
    s_uid = str(study_uid or "").strip()
    s_num = str(series_number).strip() if series_number is not None else "1"
    seed = f"series:{s_uid}:{s_num}"
    return generate_deterministic_uid(seed, namespace=namespace, version=version)


def generate_sop_instance_uid(
    series_uid: str,
    instance_number: int | str = 1,
    namespace: uuid.UUID | str | None = None,
    version: int | None = None,
) -> str:
    """Generate a deterministic SOPInstanceUID from SeriesInstanceUID and InstanceNumber (Image Number)."""
    s_uid = str(series_uid or "").strip()
    i_num = str(instance_number).strip() if instance_number is not None else "1"
    seed = f"instance:{s_uid}:{i_num}"
    return generate_deterministic_uid(seed, namespace=namespace, version=version)


def generate_dicom_uid(
    seed: str | None = None,
    namespace: uuid.UUID | str | None = None,
    version: int | None = None,
) -> str:
    """General DICOM UID generator under 2.25.

    Returns deterministic UID if seed is supplied, otherwise returns random UUIDv4 under 2.25.
    """
    if seed:
        return generate_deterministic_uid(seed, namespace=namespace, version=version)
    return uuid_to_dicom_uid(uuid.uuid4())
