from dataclasses import dataclass, field

from core.policies import RecognitionStatus, build_identity_display


@dataclass(frozen=True)
class ReminderContext:
    display_name: str | None
    recognition_status: RecognitionStatus
    similarity: float | None
    relationship_to_patient: str | None = None
    recent_event: str | None = None
    sensitive: bool = False


@dataclass(frozen=True)
class Reminder:
    title: str
    lines: list[str] = field(default_factory=list)
    patient_visible: bool = True
    requires_review: bool = False


def compose_reminder(context: ReminderContext) -> Reminder:
    decision = build_identity_display(
        status=context.recognition_status,
        display_name=context.display_name,
        similarity=context.similarity,
    )
    if context.sensitive or not decision.patient_visible:
        return Reminder(
            title="I cannot identify this person.",
            lines=[],
            patient_visible=False,
            requires_review=decision.requires_review,
        )

    lines: list[str] = []
    if context.relationship_to_patient:
        if decision.is_identity_assertion:
            lines.append(f"Your {context.relationship_to_patient}")
        else:
            lines.append(f"They said they are your {context.relationship_to_patient}.")
    if context.recent_event:
        if decision.is_identity_assertion:
            lines.append(f"They {context.recent_event}.")
        else:
            lines.append(f"They {context.recent_event}.")
    return Reminder(
        title=decision.text,
        lines=lines,
        patient_visible=decision.patient_visible,
        requires_review=decision.requires_review,
    )
