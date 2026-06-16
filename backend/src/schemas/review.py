from pydantic import BaseModel

from schemas.common import TimestampedResponse


class ReviewItemResponse(TimestampedResponse):
    patient_id: str
    item_type: str
    target_type: str
    target_id: str | None
    title: str
    summary: str | None
    payload: dict
    status: str


class ReviewDecision(BaseModel):
    status: str
    payload: dict = {}
