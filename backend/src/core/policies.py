from dataclasses import dataclass
from enum import StrEnum


class RecognitionStatus(StrEnum):
    UNKNOWN = "unknown"
    RECOGNIZED = "recognized"
    INTRODUCED = "introduced"
    CONFIRMED = "confirmed"


@dataclass(frozen=True)
class IdentityDisplayDecision:
    text: str
    patient_visible: bool
    is_identity_assertion: bool


def build_identity_display(
    *,
    status: RecognitionStatus,
    display_name: str | None,
    similarity: float | None,
    high_confidence: float = 0.95,
    medium_confidence: float = 0.80,
    recognized_confidence: float = 0.60,
) -> IdentityDisplayDecision:
    if not display_name:
        if similarity is not None and similarity >= recognized_confidence:
            return IdentityDisplayDecision(
                "You may have seen this person before.",
                True,
                False,
            )
        return IdentityDisplayDecision("I do not recognize this person.", True, False)

    if status == RecognitionStatus.INTRODUCED:
        return IdentityDisplayDecision(
            f"They introduced themselves as {display_name}.",
            True,
            False,
        )

    if status == RecognitionStatus.CONFIRMED:
        if similarity is not None and similarity >= high_confidence:
            return IdentityDisplayDecision(display_name, True, True)
        if similarity is not None and similarity >= medium_confidence:
            return IdentityDisplayDecision(
                f"This may be {display_name}.",
                True,
                False,
            )
        return IdentityDisplayDecision(
            "You may have met this person before.",
            True,
            False,
        )

    if status == RecognitionStatus.RECOGNIZED:
        return IdentityDisplayDecision(
            "You may recognize this person. Their name has not been confirmed yet.",
            True,
            False,
        )

    return IdentityDisplayDecision("I do not recognize this person.", True, False)
