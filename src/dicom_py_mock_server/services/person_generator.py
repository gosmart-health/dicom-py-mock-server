"""Service for generating realistic random patient demographics."""

import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass
class PersonInfo:
    name: str
    mrn: str
    gender: str
    dob: date


# Common last names for synthetic patient generation
LAST_NAMES: list[str] = [
    "SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES", "GARCIA", "MILLER", "DAVIS",
    "RODRIGUEZ", "MARTINEZ", "HERNANDEZ", "LOPEZ", "GONZALEZ", "WILSON", "ANDERSON",
    "THOMAS", "TAYLOR", "MOORE", "JACKSON", "MARTIN", "LEE", "PEREZ", "THOMPSON",
    "WHITE", "HARRIS", "SANCHEZ", "CLARK", "RAMIREZ", "LEWIS", "ROBINSON", "WALKER",
    "YOUNG", "ALLEN", "KING", "WRIGHT", "SCOTT", "TORRES", "NGUYEN", "HILL", "FLORES",
    "GREEN", "ADAMS", "NELSON", "BAKER", "HALL", "RIVERA", "CAMPBELL", "MITCHELL",
    "CARTER", "ROBERTS", "GOMEZ", "PHILLIPS", "EVANS", "TURNER", "DIAZ", "PARKER",
]

# Common first names with gender association (name, DICOM sex code M/F)
FIRST_NAMES: list[tuple[str, str]] = [
    ("JAMES", "M"), ("JOHN", "M"), ("ROBERT", "M"), ("MICHAEL", "M"), ("WILLIAM", "M"),
    ("DAVID", "M"), ("RICHARD", "M"), ("CHARLES", "M"), ("JOSEPH", "M"), ("THOMAS", "M"),
    ("CHRISTOPHER", "M"), ("DANIEL", "M"), ("PAUL", "M"), ("MARK", "M"), ("DONALD", "M"),
    ("GEORGE", "M"), ("KENNETH", "M"), ("STEVEN", "M"), ("EDWARD", "M"), ("BRIAN", "M"),
    ("MARY", "F"), ("PATRICIA", "F"), ("JENNIFER", "F"), ("LINDA", "F"), ("ELIZABETH", "F"),
    ("BARBARA", "F"), ("SUSAN", "F"), ("JESSICA", "F"), ("SARAH", "F"), ("KAREN", "F"),
    ("NANCY", "F"), ("LISA", "F"), ("BETTY", "F"), ("MARGARET", "F"), ("SANDRA", "F"),
    ("ASHLEY", "F"), ("KIMBERLY", "F"), ("EMILY", "F"), ("DONNA", "F"), ("MICHELLE", "F"),
]


class PersonGenerator:
    """Generates synthetic patient demographics."""

    _id_sequence: int = 0
    _base_id: int = 0

    @classmethod
    def generate_random_id(cls, size: int = 8) -> str:
        """Generate a sequential/timestamp-based zero-padded ID string."""
        if cls._base_id == 0:
            cls._base_id = int(time.time() * 1000)
        cls._id_sequence += 1
        num_str = str(cls._base_id + cls._id_sequence)
        if len(num_str) > size:
            return num_str[-size:]
        return num_str.zfill(size)

    def generate(self, suffix: str = "") -> PersonInfo:
        """Generate a random person record (Patient or Physician)."""
        last_name = random.choice(LAST_NAMES)
        first_name, gender = random.choice(FIRST_NAMES)

        patient_name = f"{last_name}^{first_name}^^^{suffix}"
        mrn = self.generate_random_id(8)

        today = datetime.now().date()
        # Random age between 0 and 95 years
        days_old = random.randint(0, 95 * 365)
        dob = today - timedelta(days=days_old)

        return PersonInfo(
            name=patient_name,
            mrn=mrn,
            gender=gender,
            dob=dob,
        )

