from pydantic import BaseModel, Field

from schemas.common import TimestampedResponse


class PersonCreate(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    relationship_to_patient: str | None = Field(default=None, max_length=160)
    notes: str | None = None
    recognition_status: str = "unknown"
    consent_status: str = "unknown"
    sensitive: bool = False


class PersonUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    relationship_to_patient: str | None = Field(default=None, max_length=160)
    notes: str | None = None
    recognition_status: str | None = None
    consent_status: str | None = None
    sensitive: bool | None = None


class PersonResponse(TimestampedResponse):
    patient_id: str
    display_name: str | None
    relationship_to_patient: str | None
    notes: str | None
    recognition_status: str
    consent_status: str
    sensitive: bool


class FaceEnrollmentResponse(BaseModel):
    person_id: str
    subject: str
    provider_image_id: str
