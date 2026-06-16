from pydantic import BaseModel, Field


class ExtractedPerson(BaseModel):
    display_name: str | None = Field(default=None, description="Name heard in the conversation.")
    relationship_to_patient: str | None = Field(
        default=None,
        description="Relationship claim heard in the conversation.",
    )
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedEvent(BaseModel):
    title: str
    description: str | None = None
    date_text: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class MemoryExtraction(BaseModel):
    introduced_person: ExtractedPerson | None = None
    events: list[ExtractedEvent] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    needs_caregiver_review: bool = True
