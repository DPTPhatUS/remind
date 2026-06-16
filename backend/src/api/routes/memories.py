from fastapi import APIRouter

from api.deps import PatientDep, SessionDep
from schemas.memories import MemoryClaimResponse, MemorySearchRequest
from services.memory_graph_service import MemoryGraphService

router = APIRouter()


@router.post("/search", response_model=list[MemoryClaimResponse])
async def search_memories(
    request: MemorySearchRequest,
    patient: PatientDep,
    session: SessionDep,
) -> list[MemoryClaimResponse]:
    claims = await MemoryGraphService(session).search_claims(patient_id=patient.id, request=request)
    return [MemoryClaimResponse.model_validate(claim) for claim in claims]
