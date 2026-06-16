from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Interaction, TranscriptSegment
from db.repositories.memory import MemoryRepository
from schemas.extraction import MemoryExtraction
from schemas.interactions import InteractionCreate, TranscriptCreate


class InteractionService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = MemoryRepository(session)

    async def create_interaction(self, patient_id: str, data: InteractionCreate) -> Interaction:
        return await self.repository.create_interaction(patient_id, data.model_dump())

    async def list_interactions(self, patient_id: str) -> list[Interaction]:
        return await self.repository.list_interactions(patient_id)

    async def add_transcript(
        self,
        *,
        interaction_id: str,
        data: TranscriptCreate,
    ) -> TranscriptSegment:
        return await self.repository.add_transcript(interaction_id, data.model_dump())

    async def create_claims_from_extraction(
        self,
        *,
        patient_id: str,
        interaction_id: str,
        extraction: MemoryExtraction,
    ) -> None:
        for claim in extraction.claims:
            await self.repository.create_claim(
                patient_id,
                {
                    "subject_type": "interaction",
                    "subject_id": interaction_id,
                    "claim_text": claim,
                    "structured_value": {},
                    "source_type": "interaction",
                    "source_id": interaction_id,
                    "confidence": 0.5,
                    "patient_visible": True,
                },
            )
