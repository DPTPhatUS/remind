from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, PermissionDeniedError
from db.models import Person
from db.repositories.people import PeopleRepository
from providers.compreface import CompreFaceClient
from schemas.people import FaceEnrollmentResponse, PersonCreate, PersonUpdate


class PersonService:
    def __init__(
        self,
        session: AsyncSession | None = None,
        compreface: CompreFaceClient | None = None,
        repository: PeopleRepository | None = None,
    ) -> None:
        if session is None and repository is None:
            raise ValueError("A session or people repository is required.")
        self.repository = repository or PeopleRepository(session)  # type: ignore[arg-type]
        self.compreface = compreface

    async def list_people(self, patient_id: str) -> list[Person]:
        return await self.repository.list_people(patient_id)

    async def create_person(self, patient_id: str, data: PersonCreate) -> Person:
        return await self.repository.create_person(patient_id, data.model_dump())

    async def update_person(self, patient_id: str, person_id: str, data: PersonUpdate) -> Person:
        person = await self.repository.get_person(person_id)
        if person is None:
            raise NotFoundError("Person not found.")
        if person.patient_id != patient_id:
            raise PermissionDeniedError("Person does not belong to the current patient.")
        return await self.repository.update_person(person, data.model_dump(exclude_unset=True))

    async def enroll_face(
        self,
        *,
        person_id: str,
        image_bytes: bytes,
        filename: str,
        patient_id: str | None = None,
    ) -> FaceEnrollmentResponse:
        if self.compreface is None:
            raise RuntimeError("CompreFace provider is not configured.")
        person = await self.repository.get_person(person_id)
        if person is None:
            raise NotFoundError("Person not found.")
        if patient_id is not None and person.patient_id != patient_id:
            raise PermissionDeniedError("Person does not belong to the current patient.")
        subject = f"person-{person.id}-{uuid4()}"
        provider_result = await self.compreface.add_face_example(
            subject=subject,
            image_bytes=image_bytes,
            filename=filename,
        )
        await self.repository.link_subject(person_id=person.id, subject=subject, confirmed=False)
        return FaceEnrollmentResponse(
            person_id=person.id,
            subject=subject,
            provider_image_id=provider_result.image_id,
        )
