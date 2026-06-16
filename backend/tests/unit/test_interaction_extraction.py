import pytest

from schemas.extraction import ExtractedEvent, ExtractedPerson, MemoryExtraction
from services.interaction_service import InteractionService


class FakeMemoryRepository:
    def __init__(self) -> None:
        self.claims: list[tuple[str, dict]] = []
        self.events: list[tuple[str, dict]] = []

    async def create_claim(self, patient_id: str, values: dict):
        self.claims.append((patient_id, values))
        return values

    async def create_event(self, patient_id: str, values: dict):
        self.events.append((patient_id, values))
        return values


class FakePeopleRepository:
    def __init__(self) -> None:
        self.people: list[tuple[str, dict]] = []

    async def create_person(self, patient_id: str, values: dict):
        self.people.append((patient_id, values))
        return type("Person", (), {"id": "person-1", **values})()


class FakeReviewRepository:
    def __init__(self) -> None:
        self.items: list[dict] = []

    async def create_item(self, **values):
        self.items.append(values)
        return values


class FakeEmbeddingProvider:
    async def embed_text(self, text: str) -> list[float]:
        assert text
        return [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_extraction_creates_pending_person_events_claims_and_review_items() -> None:
    memory_repo = FakeMemoryRepository()
    people_repo = FakePeopleRepository()
    review_repo = FakeReviewRepository()
    service = InteractionService(
        memory_repository=memory_repo,
        people_repository=people_repo,
        review_repository=review_repo,
        embedding_provider=FakeEmbeddingProvider(),
    )
    extraction = MemoryExtraction(
        introduced_person=ExtractedPerson(
            display_name="David",
            relationship_to_patient="neighbor",
            confidence=0.74,
        ),
        events=[
            ExtractedEvent(
                title="Helped with groceries",
                description="David said he helped with groceries yesterday.",
                date_text="yesterday",
                confidence=0.68,
            )
        ],
        claims=["David said he lives next door."],
        needs_caregiver_review=True,
    )

    await service.create_claims_from_extraction(
        patient_id="patient-1",
        interaction_id="interaction-1",
        extraction=extraction,
    )

    assert people_repo.people == [
        (
            "patient-1",
            {
                "display_name": "David",
                "relationship_to_patient": "neighbor",
                "notes": None,
                "recognition_status": "introduced",
                "consent_status": "unknown",
                "sensitive": False,
            },
        )
    ]
    assert memory_repo.events[0][1]["title"] == "Helped with groceries"
    assert memory_repo.claims[0][1]["claim_text"] == "David said he lives next door."
    assert memory_repo.claims[0][1]["embedding"] == [0.1, 0.2, 0.3]
    assert {item["item_type"] for item in review_repo.items} == {
        "new_person_candidate",
        "new_event_claim",
        "memory_claim",
    }
