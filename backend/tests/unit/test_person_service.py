import pytest

from core.errors import PermissionDeniedError
from schemas.people import PersonUpdate
from services.person_service import PersonService


class FakePeopleRepository:
    async def get_person(self, person_id: str):
        assert person_id == "person-1"
        return type("Person", (), {"id": person_id, "patient_id": "other-patient"})()


@pytest.mark.asyncio
async def test_update_person_rejects_person_from_another_patient() -> None:
    service = PersonService(repository=FakePeopleRepository())

    with pytest.raises(PermissionDeniedError):
        await service.update_person(
            patient_id="patient-1",
            person_id="person-1",
            data=PersonUpdate(display_name="David"),
        )
