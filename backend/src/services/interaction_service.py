from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Interaction, InteractionParticipant, TranscriptSegment
from db.repositories.memory import MemoryRepository
from db.repositories.people import PeopleRepository
from schemas.extraction import MemoryExtraction
from schemas.interactions import InteractionCreate, TranscriptCreate


class EmbeddingProvider(Protocol):
    async def embed_text(self, text: str) -> list[float]:
        ...


class InteractionService:
    def __init__(
        self,
        session: AsyncSession | None = None,
        *,
        memory_repository: MemoryRepository | None = None,
        people_repository: PeopleRepository | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        if session is None and memory_repository is None:
            raise ValueError("A session or memory repository is required.")
        self.repository = memory_repository or MemoryRepository(session)  # type: ignore[arg-type]
        self.people_repository = people_repository or (
            PeopleRepository(session) if session is not None else None
        )
        self.embedding_provider = embedding_provider

    async def create_interaction(self, patient_id: str, data: InteractionCreate) -> Interaction:
        return await self.repository.create_interaction(patient_id, data.model_dump())

    async def list_interactions(self, patient_id: str) -> list[Interaction]:
        return await self.repository.list_interactions(patient_id)

    async def start_live_interaction(
        self,
        *,
        patient_id: str,
        started_at: str,
        confidence: float,
    ) -> Interaction:
        return await self.repository.create_interaction(
            patient_id,
            {
                "started_at": started_at,
                "confidence": confidence,
                "summary": None,
            },
        )

    async def close_live_interaction(
        self,
        *,
        interaction_id: str,
        ended_at: str,
        confidence: float,
    ) -> Interaction | None:
        return await self.repository.close_interaction(
            interaction_id,
            {
                "ended_at": ended_at,
                "confidence": confidence,
                "status": "closed",
            },
        )

    async def add_participant(
        self,
        *,
        interaction_id: str,
        person_id: str | None,
        face_subject: str | None,
        face_track_id: str | None,
        recognition_confidence: float | None,
        recognition_status: str,
    ) -> InteractionParticipant:
        return await self.repository.add_participant(
            interaction_id,
            {
                "person_id": person_id,
                "face_subject": face_subject,
                "face_track_id": face_track_id,
                "recognition_confidence": recognition_confidence,
                "recognition_status": recognition_status,
            },
        )

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
        introduced_person_id: str | None = None
        if extraction.introduced_person is not None and self.people_repository is not None:
            introduced_person = await self.people_repository.create_person(
                patient_id,
                {
                    "display_name": extraction.introduced_person.display_name,
                    "relationship_to_patient": extraction.introduced_person.relationship_to_patient,
                    "notes": None,
                    "recognition_status": "introduced",
                    "consent_status": "unknown",
                },
            )
            introduced_person_id = introduced_person.id

        for event in extraction.events:
            await self.repository.create_event(
                patient_id,
                {
                    "title": event.title,
                    "description": event.description,
                    "event_date": event.date_text,
                    "confidence": event.confidence,
                    "emotional_importance": "normal",
                    "patient_visible": True,
                },
            )

        for claim in extraction.claims:
            embedding = None
            if self.embedding_provider is not None:
                embedding = await self.embedding_provider.embed_text(claim)
            await self.repository.create_claim(
                patient_id,
                {
                    "subject_type": "person" if introduced_person_id else "interaction",
                    "subject_id": introduced_person_id or interaction_id,
                    "claim_text": claim,
                    "structured_value": {},
                    "source_type": "interaction",
                    "source_id": interaction_id,
                    "confidence": 0.5,
                    "patient_visible": True,
                    "embedding": embedding,
                },
            )
