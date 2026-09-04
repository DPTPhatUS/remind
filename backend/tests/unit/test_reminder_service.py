from core.policies import RecognitionStatus
from services.reminder_service import ReminderContext, compose_reminder


def test_compose_reminder_uses_relationship_and_recent_event_for_confirmed_person() -> None:
    reminder = compose_reminder(
        ReminderContext(
            display_name="Anna Nguyen",
            recognition_status=RecognitionStatus.CONFIRMED,
            similarity=0.98,
            relationship_to_patient="daughter",
            recent_event="visited last Sunday",
        )
    )

    assert reminder.title == "Anna Nguyen"
    assert reminder.lines == ["Your daughter", "They visited last Sunday."]
    assert reminder.patient_visible is True


def test_compose_reminder_keeps_introduced_claims_uncertain() -> None:
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
    assert reminder.patient_visible is True


def test_compose_reminder_hides_unknown_identity_when_no_display_name() -> None:
    reminder = compose_reminder(
        ReminderContext(
            display_name=None,
            recognition_status=RecognitionStatus.UNKNOWN,
            similarity=None,
        )
    )

    assert reminder.patient_visible is True
    assert reminder.title == "I do not recognize this person."
