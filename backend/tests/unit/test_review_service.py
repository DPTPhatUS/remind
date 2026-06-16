import pytest

from schemas.review import ReviewDecision
from services.review_service import ReviewService


class FakeReviewRepository:
    async def update_item(self, item_id: str, status: str, payload: dict):
        assert item_id == "review-1"
        assert status == "approved"
        return type(
            "ReviewItem",
            (),
            {
                "id": item_id,
                "status": status,
                "target_type": "person",
                "target_id": "person-1",
                "payload": {"decision": payload},
            },
        )()


class FakePeopleRepository:
    def __init__(self) -> None:
        self.updated: list[tuple[str, dict]] = []

    async def update_person_by_id(self, person_id: str, values: dict):
        self.updated.append((person_id, values))


@pytest.mark.asyncio
async def test_approved_person_review_updates_person_profile() -> None:
    people_repository = FakePeopleRepository()
    service = ReviewService(
        review_repository=FakeReviewRepository(),
        people_repository=people_repository,
    )

    await service.decide(
        "review-1",
        ReviewDecision(
            status="approved",
            payload={
                "display_name": "David",
                "relationship_to_patient": "neighbor",
                "recognition_status": "confirmed",
                "consent_status": "granted",
            },
        ),
    )

    assert people_repository.updated == [
        (
            "person-1",
            {
                "display_name": "David",
                "relationship_to_patient": "neighbor",
                "recognition_status": "confirmed",
                "consent_status": "granted",
            },
        )
    ]
