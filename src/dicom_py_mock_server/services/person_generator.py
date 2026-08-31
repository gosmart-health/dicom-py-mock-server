"""Service for generating realistic random patient demographics."""

import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from dicom_py_mock_server.config import config


@dataclass
class PersonInfo:
    name: str
    mrn: str
    gender: str
    dob: date


# Common last names for synthetic patient generation
LAST_NAMES: list[str] = [
    "SMITH",
    "JOHNSON",
    "WILLIAMS",
    "BROWN",
    "JONES",
    "GARCIA",
    "MILLER",
    "DAVIS",
    "RODRIGUEZ",
    "MARTINEZ",
    "HERNANDEZ",
    "LOPEZ",
    "GONZALEZ",
    "WILSON",
    "ANDERSON",
    "THOMAS",
    "TAYLOR",
    "MOORE",
    "JACKSON",
    "MARTIN",
    "LEE",
    "PEREZ",
    "THOMPSON",
    "WHITE",
    "HARRIS",
    "SANCHEZ",
    "CLARK",
    "RAMIREZ",
    "LEWIS",
    "ROBINSON",
    "WALKER",
    "YOUNG",
    "ALLEN",
    "KING",
    "WRIGHT",
    "SCOTT",
    "TORRES",
    "NGUYEN",
    "HILL",
    "FLORES",
    "GREEN",
    "ADAMS",
    "NELSON",
    "BAKER",
    "HALL",
    "RIVERA",
    "CAMPBELL",
    "MITCHELL",
    "CARTER",
    "ROBERTS",
    "GOMEZ",
    "PHILLIPS",
    "EVANS",
    "TURNER",
    "DIAZ",
    "PARKER",
]

# Common first names with gender association (name, DICOM sex code M/F)
FIRST_NAMES: list[tuple[str, str]] = [
    ("JAMES", "M"),
    ("JOHN", "M"),
    ("ROBERT", "M"),
    ("MICHAEL", "M"),
    ("WILLIAM", "M"),
    ("DAVID", "M"),
    ("RICHARD", "M"),
    ("CHARLES", "M"),
    ("JOSEPH", "M"),
    ("THOMAS", "M"),
    ("CHRISTOPHER", "M"),
    ("DANIEL", "M"),
    ("PAUL", "M"),
    ("MARK", "M"),
    ("DONALD", "M"),
    ("GEORGE", "M"),
    ("KENNETH", "M"),
    ("STEVEN", "M"),
    ("EDWARD", "M"),
    ("BRIAN", "M"),
    ("MARY", "F"),
    ("PATRICIA", "F"),
    ("JENNIFER", "F"),
    ("LINDA", "F"),
    ("ELIZABETH", "F"),
    ("BARBARA", "F"),
    ("SUSAN", "F"),
    ("JESSICA", "F"),
    ("SARAH", "F"),
    ("KAREN", "F"),
    ("NANCY", "F"),
    ("LISA", "F"),
    ("BETTY", "F"),
    ("MARGARET", "F"),
    ("SANDRA", "F"),
    ("ASHLEY", "F"),
    ("KIMBERLY", "F"),
    ("EMILY", "F"),
    ("DONNA", "F"),
    ("MICHELLE", "F"),
]


class PersonGenerator:
    """Generates synthetic patient demographics."""

    _id_sequence: int = 0
    _base_id: int = 0

    def __init__(
        self,
        patient_suffix: str | None = None,
        id_prefix: str | None = None,
        pn_suffix: str | None = None,
    ) -> None:
        self.patient_suffix = (
            patient_suffix if patient_suffix is not None else getattr(config, "patient_suffix", "_GSH")
        )
        self.pn_suffix = pn_suffix if pn_suffix is not None else getattr(config, "pn_suffix", "_GSH")
        self.id_prefix = id_prefix if id_prefix is not None else getattr(config, "id_prefix", "GSH-")

    @classmethod
    def generate_random_id(cls, size: int = 8, prefix: str = "") -> str:
        """Generate a sequential/timestamp-based zero-padded ID string with optional prefix."""
        if cls._base_id == 0:
            cls._base_id = int(time.time() * 1000)
        cls._id_sequence += 1
        num_str = str(cls._base_id + cls._id_sequence)
        if len(num_str) > size:
            raw_id = num_str[-size:]
        else:
            raw_id = num_str.zfill(size)
        return f"{prefix}{raw_id}"

    def generate(self, suffix: str = "", is_patient: bool = True) -> PersonInfo:
        """Generate a random person record (Patient or Physician)."""
        last_name = random.choice(LAST_NAMES)
        first_name, gender = random.choice(FIRST_NAMES)

        if is_patient and self.patient_suffix:
            last_name = f"{last_name}{self.patient_suffix}"
        elif not is_patient and self.pn_suffix:
            last_name = f"{last_name}{self.pn_suffix}"

        person_name = f"{last_name}^{first_name}^^^{suffix}" if suffix else f"{last_name}^{first_name}"
        mrn = self.generate_random_id(8, prefix=self.id_prefix if is_patient else "")

        today = datetime.now().date()
        # Random age between 0 and 95 years
        days_old = random.randint(0, 95 * 365)
        dob = today - timedelta(days=days_old)

        return PersonInfo(
            name=person_name,
            mrn=mrn,
            gender=gender,
            dob=dob,
        )

    def generate_physician(self, title: str = "MD") -> PersonInfo:
        """Generate a random physician record."""
        return self.generate(suffix=title, is_patient=False)

    def generate_physician_pool(self, count: int = 3, title: str = "MD") -> list[str]:
        """Generate a list of distinct physician names."""
        pool: list[str] = []
        for _ in range(count):
            physician = self.generate_physician(title=title)
            pool.append(physician.name)
        return pool
