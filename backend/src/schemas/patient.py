from pydantic import BaseModel, Field

from schemas.common import TimestampedResponse


class PatientUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    date_of_birth: str | None = None
    preferences: dict | None = None
    accessibility_settings: dict | None = None


class PatientResponse(TimestampedResponse):
    display_name: str
    date_of_birth: str | None
    preferences: dict
    accessibility_settings: dict
