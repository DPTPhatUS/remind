from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from db.models import ReviewItem
from db.repositories.people import PeopleRepository
from db.repositories.review import ReviewRepository
from schemas.review import ReviewDecision


class ReviewService:
    def __init__(
        self,
        session: AsyncSession | None = None,
        *,
        review_repository: ReviewRepository | None = None,
        people_repository: PeopleRepository | None = None,
    ) -> None:
        if session is None and review_repository is None:
            raise ValueError("A session or review repository is required.")
        self.repository = review_repository or ReviewRepository(session)  # type: ignore[arg-type]
        self.people_repository = people_repository or (
            PeopleRepository(session) if session is not None else None
        )

    async def create_new_person_candidate(
        self,
        *,
        patient_id: str,
        person_id: str,
        display_name: str | None,
        payload: dict,
    ) -> ReviewItem:
        return await self.repository.create_item(
            patient_id=patient_id,
            item_type="new_person_candidate",
            target_type="person",
            target_id=person_id,
            title=f"Review new person: {display_name or 'Unknown person'}",
            payload=payload,
        )

    async def list_pending(self, patient_id: str) -> list[ReviewItem]:
        return await self.repository.list_items(patient_id, "pending")

    async def decide(self, item_id: str, decision: ReviewDecision) -> ReviewItem:
        item = await self.repository.update_item(item_id, decision.status, decision.payload)
        if item is None:
            raise NotFoundError("Review item not found.")
        if (
            decision.status == "approved"
            and item.target_type == "person"
            and item.target_id is not None
            and self.people_repository is not None
        ):
            allowed_fields = {
                "display_name",
                "relationship_to_patient",
                "notes",
                "recognition_status",
                "consent_status",
                "sensitive",
            }
            updates = {
                key: value for key, value in decision.payload.items() if key in allowed_fields
            }
            if updates:
                await self.people_repository.update_person_by_id(item.target_id, updates)
        return item
