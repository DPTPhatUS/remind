from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Event, MemoryClaim, Relationship
from db.repositories.memory import MemoryRepository
from schemas.events import EventCreate
from schemas.memories import MemorySearchRequest
from schemas.relationships import RelationshipCreate


class EmbeddingProvider(Protocol):
    async def embed_text(self, text: str) -> list[float]:
        ...


class MemoryGraphService:
    def __init__(
        self,
        session: AsyncSession | None = None,
        *,
        memory_repository: MemoryRepository | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        if session is None and memory_repository is None:
            raise ValueError("A session or memory repository is required.")
        self.repository = memory_repository or MemoryRepository(session)  # type: ignore[arg-type]
        self.embedding_provider = embedding_provider

    async def search_claims(
        self,
        *,
        patient_id: str,
        request: MemorySearchRequest,
    ) -> list[MemoryClaim]:
        if self.embedding_provider is not None:
            embedding = await self.embedding_provider.embed_text(request.query)
            return await self.repository.search_claims_by_embedding(
                patient_id,
                embedding,
                request.limit,
            )
        return await self.repository.search_claims(patient_id, request.query, request.limit)

    async def create_relationship(
        self,
        *,
        patient_id: str,
        data: RelationshipCreate,
        confirmed_by_user_id: str | None = None,
    ) -> Relationship:
        values = data.model_dump()
        values["confirmed_by_user_id"] = confirmed_by_user_id
        return await self.repository.create_relationship(patient_id, values)

    async def list_relationships(self, patient_id: str) -> list[Relationship]:
        return await self.repository.list_relationships(patient_id)

    async def create_event(self, *, patient_id: str, data: EventCreate) -> Event:
        return await self.repository.create_event(patient_id, data.model_dump())

    async def list_events(self, patient_id: str) -> list[Event]:
        return await self.repository.list_events(patient_id)
