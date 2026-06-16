import pytest

from schemas.memories import MemorySearchRequest
from services.memory_graph_service import MemoryGraphService


class FakeMemoryRepository:
    def __init__(self) -> None:
        self.vector_search: tuple[str, list[float], int] | None = None
        self.text_search: tuple[str, str, int] | None = None

    async def search_claims_by_embedding(
        self,
        patient_id: str,
        embedding: list[float],
        limit: int,
    ):
        self.vector_search = (patient_id, embedding, limit)
        return ["vector-result"]

    async def search_claims(self, patient_id: str, query: str, limit: int):
        self.text_search = (patient_id, query, limit)
        return ["text-result"]


class FakeEmbeddingProvider:
    async def embed_text(self, text: str) -> list[float]:
        assert text == "groceries"
        return [0.4, 0.5, 0.6]


@pytest.mark.asyncio
async def test_memory_search_uses_vector_search_when_embedding_provider_exists() -> None:
    repository = FakeMemoryRepository()
    service = MemoryGraphService(
        memory_repository=repository,
        embedding_provider=FakeEmbeddingProvider(),
    )

    result = await service.search_claims(
        patient_id="patient-1",
        request=MemorySearchRequest(query="groceries", limit=3),
    )

    assert result == ["vector-result"]
    assert repository.vector_search == ("patient-1", [0.4, 0.5, 0.6], 3)
    assert repository.text_search is None
