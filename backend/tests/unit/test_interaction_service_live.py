import pytest

from services.interaction_service import InteractionService


class FakeMemoryRepository:
    def __init__(self) -> None:
        self.created_interactions: list[tuple[str, dict]] = []
        self.closed_interactions: list[tuple[str, dict]] = []
        self.participants: list[tuple[str, dict]] = []

    async def create_interaction(self, patient_id: str, values: dict):
        self.created_interactions.append((patient_id, values))
        return type("Interaction", (), {"id": "interaction-1", **values})()

    async def close_interaction(self, interaction_id: str, values: dict):
        self.closed_interactions.append((interaction_id, values))
        return type("Interaction", (), {"id": interaction_id, **values})()

    async def add_participant(self, interaction_id: str, values: dict):
        self.participants.append((interaction_id, values))
        return type("Participant", (), {"id": "participant-1", **values})()


@pytest.mark.asyncio
async def test_live_interaction_helpers_create_close_and_add_participant() -> None:
    repository = FakeMemoryRepository()
    service = InteractionService(memory_repository=repository)

    interaction = await service.start_live_interaction(
        patient_id="patient-1",
        started_at="2026-06-16T10:00:00+00:00",
        confidence=0.8,
    )
    await service.add_participant(
        interaction_id=interaction.id,
        person_id="person-1",
        face_subject="subject-1",
        face_track_id="primary",
        recognition_confidence=0.97,
        recognition_status="confirmed",
    )
    await service.close_live_interaction(
        interaction_id=interaction.id,
        ended_at="2026-06-16T10:01:00+00:00",
        confidence=0.72,
    )

    assert repository.created_interactions == [
        (
            "patient-1",
            {
                "started_at": "2026-06-16T10:00:00+00:00",
                "confidence": 0.8,
                "summary": None,
            },
        )
    ]
    assert repository.participants == [
        (
            "interaction-1",
            {
                "person_id": "person-1",
                "face_subject": "subject-1",
                "face_track_id": "primary",
                "recognition_confidence": 0.97,
                "recognition_status": "confirmed",
            },
        )
    ]
    assert repository.closed_interactions == [
        (
            "interaction-1",
            {
                "ended_at": "2026-06-16T10:01:00+00:00",
                "confidence": 0.72,
                "status": "closed",
            },
        )
    ]
