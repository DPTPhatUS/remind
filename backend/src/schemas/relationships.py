from pydantic import BaseModel, Field

from schemas.common import TimestampedResponse


class RelationshipCreate(BaseModel):
    from_person_id: str
    to_person_id: str | None = None
    relationship_type: str = Field(min_length=1, max_length=160)
    confidence: float = 1.0


class RelationshipResponse(TimestampedResponse):
    patient_id: str
    from_person_id: str
    to_person_id: str | None
    relationship_type: str
    confidence: float
    source_claim_id: str | None
