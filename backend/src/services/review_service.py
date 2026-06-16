from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from db.models import ReviewItem
from db.repositories.review import ReviewRepository
from schemas.review import ReviewDecision


class ReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = ReviewRepository(session)

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
        return item
