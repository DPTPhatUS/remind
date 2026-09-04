from core.policies import RecognitionStatus, build_identity_display


def test_confirmed_high_confidence_identity_is_asserted() -> None:
    decision = build_identity_display(
        status=RecognitionStatus.CONFIRMED,
        display_name="David",
        similarity=0.96,
    )

    assert decision.patient_visible is True
    assert decision.text == "David"
    assert decision.is_identity_assertion is True


def test_medium_confidence_confirmed_identity_is_uncertain() -> None:
    decision = build_identity_display(
        status=RecognitionStatus.CONFIRMED,
        display_name="David",
        similarity=0.84,
    )

    assert decision.patient_visible is True
    assert decision.text == "This may be David."
    assert decision.is_identity_assertion is False


def test_introduced_identity_is_presented_as_heard_evidence() -> None:
    decision = build_identity_display(
        status=RecognitionStatus.INTRODUCED,
        display_name="David",
        similarity=0.91,
    )

    assert decision.patient_visible is True
    assert decision.text == "They introduced themselves as David."
    assert decision.is_identity_assertion is False


def test_recognized_identity_is_presented_as_unconfirmed_recognition() -> None:
    decision = build_identity_display(
        status=RecognitionStatus.RECOGNIZED,
        display_name="David",
        similarity=0.91,
    )

    assert decision.patient_visible is True
    assert (
        decision.text
        == "You may recognize this person. Their name has not been confirmed yet."
    )
    assert decision.is_identity_assertion is False


def test_unknown_identity_with_no_display_name_is_presented_safely() -> None:
    decision = build_identity_display(
        status=RecognitionStatus.UNKNOWN,
        display_name=None,
        similarity=None,
    )

    assert decision.patient_visible is True
    assert decision.text == "I do not recognize this person."
    assert decision.is_identity_assertion is False
