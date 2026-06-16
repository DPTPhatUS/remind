from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Event, Interaction, MemoryClaim, Relationship, TranscriptSegment


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_interaction(self, patient_id: str, values: dict) -> Interaction:
        interaction = Interaction(patient_id=patient_id, **values)
        self.session.add(interaction)
        await self.session.commit()
        await self.session.refresh(interaction)
        return interaction

    async def list_interactions(self, patient_id: str) -> list[Interaction]:
        result = await self.session.execute(
            select(Interaction)
            .where(Interaction.patient_id == patient_id)
            .order_by(Interaction.created_at.desc())
        )
        return list(result.scalars())

    async def add_transcript(self, interaction_id: str, values: dict) -> TranscriptSegment:
        segment = TranscriptSegment(interaction_id=interaction_id, **values)
        self.session.add(segment)
        await self.session.commit()
        await self.session.refresh(segment)
        return segment

    async def create_claim(self, patient_id: str, values: dict) -> MemoryClaim:
        claim = MemoryClaim(patient_id=patient_id, **values)
        self.session.add(claim)
        await self.session.commit()
        await self.session.refresh(claim)
        return claim

    async def search_claims(self, patient_id: str, query: str, limit: int) -> list[MemoryClaim]:
        result = await self.session.execute(
            select(MemoryClaim)
            .where(MemoryClaim.patient_id == patient_id)
            .where(MemoryClaim.patient_visible.is_(True))
            .where(MemoryClaim.claim_text.ilike(f"%{query}%"))
            .order_by(MemoryClaim.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def create_relationship(self, patient_id: str, values: dict) -> Relationship:
        relationship = Relationship(patient_id=patient_id, **values)
        self.session.add(relationship)
        await self.session.commit()
        await self.session.refresh(relationship)
        return relationship

    async def list_relationships(self, patient_id: str) -> list[Relationship]:
        result = await self.session.execute(
            select(Relationship).where(Relationship.patient_id == patient_id)
        )
        return list(result.scalars())

    async def create_event(self, patient_id: str, values: dict) -> Event:
        event = Event(patient_id=patient_id, **values)
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def list_events(self, patient_id: str) -> list[Event]:
        result = await self.session.execute(select(Event).where(Event.patient_id == patient_id))
        return list(result.scalars())
