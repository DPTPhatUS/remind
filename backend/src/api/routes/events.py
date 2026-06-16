from fastapi import APIRouter

from api.deps import PatientDep, SessionDep
from schemas.events import EventCreate, EventResponse
from services.memory_graph_service import MemoryGraphService

router = APIRouter()


@router.get("", response_model=list[EventResponse])
async def list_events(patient: PatientDep, session: SessionDep) -> list[EventResponse]:
    events = await MemoryGraphService(session).list_events(patient.id)
    return [EventResponse.model_validate(item) for item in events]


@router.post("", response_model=EventResponse)
async def create_event(
    request: EventCreate,
    patient: PatientDep,
    session: SessionDep,
) -> EventResponse:
    event = await MemoryGraphService(session).create_event(patient_id=patient.id, data=request)
    return EventResponse.model_validate(event)
