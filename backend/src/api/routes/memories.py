from fastapi import APIRouter

from api.deps import PatientDep, SessionDep, SettingsDep
from providers.openai import OpenAIEmbeddingProvider
from schemas.memories import MemoryClaimResponse, MemorySearchRequest
from services.memory_graph_service import MemoryGraphService

router = APIRouter()


@router.post("/search", response_model=list[MemoryClaimResponse])
async def search_memories(
    request: MemorySearchRequest,
    patient: PatientDep,
    session: SessionDep,
    settings: SettingsDep,
) -> list[MemoryClaimResponse]:
    embedding_provider = None
    if settings.openai_api_key:
        embedding_provider = OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
            dimensions=settings.openai_embedding_dimensions,
        )
    claims = await MemoryGraphService(
        session,
        embedding_provider=embedding_provider,
    ).search_claims(patient_id=patient.id, request=request)
    return [MemoryClaimResponse.model_validate(claim) for claim in claims]
