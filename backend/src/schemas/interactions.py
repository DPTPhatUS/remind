from pydantic import BaseModel, Field

from schemas.common import TimestampedResponse


class InteractionCreate(BaseModel):
    started_at: str
    confidence: float = 0.0
    summary: str | None = None


class InteractionResponse(TimestampedResponse):
    patient_id: str
    started_at: str
    ended_at: str | None
    summary: str | None
    confidence: float
    status: str


class TranscriptCreate(BaseModel):
    text: str = Field(min_length=1)
    speaker_label: str | None = None
    confidence: float | None = None
    started_at_ms: int | None = None
    ended_at_ms: int | None = None


class TranscriptResponse(TimestampedResponse):
    interaction_id: str
    speaker_label: str | None
    text: str
    confidence: float | None
    started_at_ms: int | None
    ended_at_ms: int | None
