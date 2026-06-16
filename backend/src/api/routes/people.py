from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from api.deps import CompreFaceDep, PatientDep, SessionDep, to_http_error
from core.errors import AppError
from schemas.people import FaceEnrollmentResponse, PersonCreate, PersonResponse, PersonUpdate
from services.person_service import PersonService

router = APIRouter()


@router.get("", response_model=list[PersonResponse])
async def list_people(patient: PatientDep, session: SessionDep) -> list[PersonResponse]:
    people = await PersonService(session).list_people(patient.id)
    return [PersonResponse.model_validate(person) for person in people]


@router.post("", response_model=PersonResponse)
async def create_person(
    request: PersonCreate,
    patient: PatientDep,
    session: SessionDep,
) -> PersonResponse:
    person = await PersonService(session).create_person(patient.id, request)
    return PersonResponse.model_validate(person)


@router.patch("/{person_id}", response_model=PersonResponse)
async def update_person(
    person_id: str,
    request: PersonUpdate,
    session: SessionDep,
) -> PersonResponse:
    try:
        person = await PersonService(session).update_person(person_id, request)
    except AppError as error:
        raise to_http_error(error) from error
    return PersonResponse.model_validate(person)


@router.post("/{person_id}/face-examples", response_model=FaceEnrollmentResponse)
async def enroll_face(
    person_id: str,
    session: SessionDep,
    compreface: CompreFaceDep,
    file: Annotated[UploadFile, File()],
) -> FaceEnrollmentResponse:
    try:
        return await PersonService(session, compreface).enroll_face(
            person_id=person_id,
            image_bytes=await file.read(),
            filename=file.filename or "face.jpg",
        )
    except AppError as error:
        raise to_http_error(error) from error
