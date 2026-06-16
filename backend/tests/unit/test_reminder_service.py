from core.policies import RecognitionStatus
from services.reminder_service import ReminderContext, compose_reminder


def test_compose_reminder_uses_relationship_and_recent_event_for_trusted_person() -> None:
    reminder = compose_reminder(
        ReminderContext(
            display_name="Anna Nguyen",
            recognition_status=RecognitionStatus.TRUSTED,
            similarity=0.98,
            relationship_to_patient="daughter",
            recent_event="visited last Sunday",
        )
    )

    assert reminder.title == "Anna Nguyen"
    assert reminder.lines == ["Your daughter", "They visited last Sunday."]
    assert reminder.requires_review is False


def test_compose_reminder_keeps_pending_claims_uncertain() -> None:
    reminder = compose_reminder(
        ReminderContext(
            display_name="David",
            recognition_status=RecognitionStatus.INTRODUCED,
            similarity=0.88,
            relationship_to_patient="neighbor",
            recent_event="said he helped with groceries yesterday",
        )
    )

    assert reminder.title == "They introduced themselves as David."
    assert reminder.lines == [
        "They said they are your neighbor.",
        "They said he helped with groceries yesterday.",
    ]
    assert reminder.requires_review is True


def test_compose_reminder_hides_opted_out_people() -> None:
    reminder = compose_reminder(
        ReminderContext(
            display_name="David",
            recognition_status=RecognitionStatus.OPTED_OUT,
            similarity=0.99,
            relationship_to_patient="neighbor",
            recent_event="visited yesterday",
        )
    )

    assert reminder.title == "I cannot identify this person."
    assert reminder.lines == []
    assert reminder.patient_visible is False
