from fastapi import APIRouter

from api.deps import PatientDep, SessionDep
from schemas.patient import PatientResponse, PatientUpdate

router = APIRouter()


@router.get("/me", response_model=PatientResponse)
async def get_patient(patient: PatientDep) -> PatientResponse:
    return PatientResponse.model_validate(patient)


@router.patch("/me", response_model=PatientResponse)
async def update_patient(
    request: PatientUpdate,
    patient: PatientDep,
    session: SessionDep,
) -> PatientResponse:
    for key, value in request.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(patient, key, value)
    await session.commit()
    await session.refresh(patient)
    return PatientResponse.model_validate(patient)
