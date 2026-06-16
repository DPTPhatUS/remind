from fastapi import APIRouter

from api.deps import CurrentUserDep, PatientDep, SessionDep
from schemas.relationships import RelationshipCreate, RelationshipResponse
from services.memory_graph_service import MemoryGraphService

router = APIRouter()


@router.get("", response_model=list[RelationshipResponse])
async def list_relationships(
    patient: PatientDep,
    session: SessionDep,
) -> list[RelationshipResponse]:
    relationships = await MemoryGraphService(session).list_relationships(patient.id)
    return [RelationshipResponse.model_validate(item) for item in relationships]


@router.post("", response_model=RelationshipResponse)
async def create_relationship(
    request: RelationshipCreate,
    patient: PatientDep,
    user: CurrentUserDep,
    session: SessionDep,
) -> RelationshipResponse:
    relationship = await MemoryGraphService(session).create_relationship(
        patient_id=patient.id,
        data=request,
        confirmed_by_user_id=user.id,
    )
    return RelationshipResponse.model_validate(relationship)
