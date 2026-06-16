from pydantic import BaseModel, Field

from schemas.common import TimestampedResponse


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str | None = None
    event_date: str | None = None
    confidence: float = 1.0
    emotional_importance: str = "normal"
    patient_visible: bool = True


class EventResponse(TimestampedResponse):
    patient_id: str
    title: str
    description: str | None
    event_date: str | None
    confidence: float
    emotional_importance: str
    patient_visible: bool
