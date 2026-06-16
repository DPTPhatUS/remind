from pydantic import BaseModel, Field

from schemas.common import TimestampedResponse


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class MemoryClaimResponse(TimestampedResponse):
    patient_id: str
    subject_type: str
    subject_id: str | None
    claim_text: str
    structured_value: dict
    source_type: str
    source_id: str | None
    confidence: float
    confirmed_by_user_id: str | None
    patient_visible: bool
