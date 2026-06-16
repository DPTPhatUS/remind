from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Correction, ReviewItem


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_item(
        self,
        *,
        patient_id: str,
        item_type: str,
        target_type: str,
        title: str,
        target_id: str | None = None,
        summary: str | None = None,
        payload: dict | None = None,
    ) -> ReviewItem:
        item = ReviewItem(
            patient_id=patient_id,
            item_type=item_type,
            target_type=target_type,
            target_id=target_id,
            title=title,
            summary=summary,
            payload=payload or {},
        )
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def list_items(self, patient_id: str, status: str = "pending") -> list[ReviewItem]:
        result = await self.session.execute(
            select(ReviewItem)
            .where(ReviewItem.patient_id == patient_id)
            .where(ReviewItem.status == status)
            .order_by(ReviewItem.created_at.desc())
        )
        return list(result.scalars())

    async def update_item(self, item_id: str, status: str, payload: dict) -> ReviewItem | None:
        item = await self.session.get(ReviewItem, item_id)
        if item is None:
            return None
        item.status = status
        if payload:
            item.payload = {**item.payload, "decision": payload}
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def add_correction(
        self,
        *,
        target_type: str,
        target_id: str,
        correction_type: str,
        old_value: dict | None,
        new_value: dict,
        corrected_by_user_id: str | None,
    ) -> Correction:
        correction = Correction(
            target_type=target_type,
            target_id=target_id,
            correction_type=correction_type,
            old_value=old_value,
            new_value=new_value,
            corrected_by_user_id=corrected_by_user_id,
        )
        self.session.add(correction)
        await self.session.commit()
        await self.session.refresh(correction)
        return correction
