"""Pydantic models for DICOM metadata and requests."""


from pydantic import BaseModel, Field


class PatientModel(BaseModel):
    """Patient metadata schema."""

    patient_id: str = Field(default="MOCK-PATIENT-001", description="Patient ID")
    patient_name: str = Field(default="Doe^John", description="Patient Name (DICOM PN format)")
    patient_birth_date: str | None = Field(default="19800101", description="Patient Birth Date (YYYYMMDD)")
    patient_sex: str | None = Field(default="M", description="Patient Sex (M/F/O)")


class StudyModel(BaseModel):
    """Study metadata schema."""

    study_instance_uid: str | None = Field(default=None, description="Study Instance UID (generated if omitted)")
    study_date: str | None = Field(default="20260828", description="Study Date (YYYYMMDD)")
    study_time: str | None = Field(default="120000", description="Study Time (HHMMSS)")
    accession_number: str | None = Field(default="ACC-001", description="Accession Number")
    study_description: str | None = Field(default=None, description="Study Description (generated based on modality if omitted)")


class SeriesModel(BaseModel):
    """Series metadata schema."""

    series_instance_uid: str | None = Field(default=None, description="Series Instance UID (generated if omitted)")
    modality: str = Field(default="CT", description="Modality (CT, MR, US, CR, DX, etc.)")
    series_number: int = Field(default=1, description="Series Number")
    series_description: str | None = Field(default="Axial Standard", description="Series Description")


class MockDicomRequest(BaseModel):
    """Request schema for generating mock DICOM objects."""

    patient: PatientModel = Field(default_factory=PatientModel)
    study: StudyModel = Field(default_factory=StudyModel)
    series: SeriesModel = Field(default_factory=SeriesModel)
    num_instances: int = Field(default=1, ge=1, le=100, description="Number of DICOM instances to generate")
    rows: int = Field(default=512, ge=16, le=2048, description="Image Rows")
    columns: int = Field(default=512, ge=16, le=2048, description="Image Columns")
    transfer_syntax: str | None = Field(default=None, description="Transfer syntax (RAW, JPEG, JPEG2000, RLE)")
    burn_in_text: bool = Field(default=True, description="Burn patient/study metadata strings into image pixels")


class RawImageGeneratorRequest(BaseModel):
    """Request schema specifically for raw image generation with burned-in text."""

    patient_name: str = Field(default="Doe^John", description="Patient Name")
    patient_id: str = Field(default="MOCK-PATIENT-001", description="Patient ID")
    study_date: str = Field(default="20260828", description="Study Date (YYYYMMDD)")
    study_time: str = Field(default="120000", description="Study Time (HHMMSS)")
    image_number: int = Field(default=1, ge=1, description="Image / Instance Number")
    rows: int = Field(default=512, ge=16, le=2048, description="Image Rows")
    columns: int = Field(default=512, ge=16, le=2048, description="Image Columns")
    transfer_syntax: str | None = Field(default=None, description="Transfer syntax (RAW, JPEG, JPEG2000, RLE)")


class MockDicomResponse(BaseModel):
    """Response schema following mock DICOM generation."""

    success: bool = True
    message: str = "Mock DICOM objects generated successfully"
    patient_id: str
    study_instance_uid: str
    series_instance_uid: str
    generated_instances: int
    file_paths: list[str]


class ScpStatusResponse(BaseModel):
    """Response schema for DICOM SCP status."""

    ae_title: str
    port: int
    is_running: bool
    supported_services: list[str]


class MwlGenerateRequest(BaseModel):
    """Optional customization parameters for MWL entry generation."""

    patient_name: str | None = Field(default=None, alias="patientName")
    patient_id: str | None = Field(default=None, alias="patientId")
    mrn: str | None = None
    dob: str | None = None
    sex: str | None = None
    gender: str | None = None
    modality: str | None = None
    accession: str | None = None
    study_uid: str | None = Field(default=None, alias="studyUid")
    reason: str | None = None
    study_description: str | None = Field(default=None, alias="studyDescription")
    department: str | None = None
    num_instances: int | None = Field(default=None, alias="numInstances")


class MwlStatusResponse(BaseModel):
    """Response schema for MWL generator service status."""

    active_entries_count: int
    window_hr: int
    base_rate_per_hr: float
    current_rate_per_hr: float
    is_business_hours: bool
    template_modalities: list[str]
    is_auto_generating: bool


class MwlEntrySummary(BaseModel):
    """Summary representation of a Modality Worklist entry."""

    patient_id: str
    patient_name: str
    accession: str
    modality: str
    study_uid: str
    num_instances: int | None = None
    created_at: str
    json_entry: dict


