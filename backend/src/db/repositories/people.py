from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import FaceSubjectLink, Person


class PeopleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_people(self, patient_id: str) -> list[Person]:
        result = await self.session.execute(
            select(Person).where(Person.patient_id == patient_id).order_by(Person.created_at.desc())
        )
        return list(result.scalars())

    async def get_person(self, person_id: str) -> Person | None:
        return await self.session.get(Person, person_id)

    async def get_person_by_subject(self, subject: str) -> Person | None:
        result = await self.session.execute(
            select(Person)
            .join(FaceSubjectLink, FaceSubjectLink.person_id == Person.id)
            .where(FaceSubjectLink.subject == subject)
        )
        return result.scalar_one_or_none()

    async def create_person(self, patient_id: str, values: dict) -> Person:
        person = Person(patient_id=patient_id, **values)
        self.session.add(person)
        await self.session.commit()
        await self.session.refresh(person)
        return person

    async def update_person(self, person: Person, values: dict) -> Person:
        for key, value in values.items():
            if value is not None:
                setattr(person, key, value)
        await self.session.commit()
        await self.session.refresh(person)
        return person

    async def link_subject(
        self,
        *,
        person_id: str,
        subject: str,
        confirmed: bool = False,
        source_interaction_id: str | None = None,
    ) -> FaceSubjectLink:
        link = FaceSubjectLink(
            person_id=person_id,
            subject=subject,
            confirmed=confirmed,
            source_interaction_id=source_interaction_id,
        )
        self.session.add(link)
        await self.session.commit()
        await self.session.refresh(link)
        return link
