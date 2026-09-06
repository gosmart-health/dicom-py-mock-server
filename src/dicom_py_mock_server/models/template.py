"""Data structures for multi-slice DICOM template series and datasets."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydicom.dataset import Dataset


@dataclass
class TemplateSeriesDataset:
    """Represents a multi-slice DICOM template series loaded into memory."""

    name: str
    modality: str
    slices: list[Dataset] = field(default_factory=list)
    source_dir: Path | None = None
    series_instance_uid: str | None = None
    series_number: int | None = None
    series_description: str | None = None
    study_instance_uid: str | None = None
    study_description: str | None = None
    rows: int | None = None
    columns: int | None = None

    @property
    def slice_count(self) -> int:
        """Total number of image slices in this template series."""
        return len(self.slices)

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata summary to dictionary."""
        return {
            "name": self.name,
            "modality": self.modality,
            "slice_count": self.slice_count,
            "series_instance_uid": self.series_instance_uid,
            "series_number": self.series_number,
            "series_description": self.series_description,
            "rows": self.rows,
            "columns": self.columns,
            "source_dir": str(self.source_dir) if self.source_dir else None,
        }
