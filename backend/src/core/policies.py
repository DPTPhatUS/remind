from dataclasses import dataclass
from enum import StrEnum


class RecognitionStatus(StrEnum):
    UNKNOWN = "unknown"
    SEEN_BEFORE = "seen_before"
    INTRODUCED = "introduced"
    CONFIRMED = "confirmed"
    TRUSTED = "trusted"
    OPTED_OUT = "opted_out"


@dataclass(frozen=True)
class IdentityDisplayDecision:
    text: str
    patient_visible: bool
    is_identity_assertion: bool
    requires_review: bool


def build_identity_display(
    *,
    status: RecognitionStatus,
    display_name: str | None,
    similarity: float | None,
    high_confidence: float = 0.95,
    medium_confidence: float = 0.80,
    seen_before_confidence: float = 0.60,
) -> IdentityDisplayDecision:
    if status == RecognitionStatus.OPTED_OUT:
        return IdentityDisplayDecision("", False, False, False)

    if not display_name:
        if similarity is not None and similarity >= seen_before_confidence:
            return IdentityDisplayDecision(
                "You may have seen this person before.",
                True,
                False,
                True,
            )
        return IdentityDisplayDecision("I do not recognize this person.", True, False, False)

    if status == RecognitionStatus.INTRODUCED:
        return IdentityDisplayDecision(
            f"They introduced themselves as {display_name}.",
            True,
            False,
            True,
        )

    if status in {RecognitionStatus.CONFIRMED, RecognitionStatus.TRUSTED}:
        if similarity is not None and similarity >= high_confidence:
            return IdentityDisplayDecision(display_name, True, True, False)
        if similarity is not None and similarity >= medium_confidence:
            return IdentityDisplayDecision(
                f"This may be {display_name}.",
                True,
                False,
                True,
            )
        return IdentityDisplayDecision(
            "You may have met this person before.",
            True,
            False,
            True,
        )

    if status == RecognitionStatus.SEEN_BEFORE:
        return IdentityDisplayDecision(
            "You have seen this person before. Their name has not been confirmed yet.",
            True,
            False,
            True,
        )

    return IdentityDisplayDecision("I do not recognize this person.", True, False, False)
