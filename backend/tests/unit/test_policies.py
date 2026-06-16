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
    assert decision.requires_review is False


def test_medium_confidence_confirmed_identity_is_uncertain() -> None:
    decision = build_identity_display(
        status=RecognitionStatus.CONFIRMED,
        display_name="David",
        similarity=0.84,
    )

    assert decision.patient_visible is True
    assert decision.text == "This may be David."
    assert decision.is_identity_assertion is False
    assert decision.requires_review is True


def test_introduced_identity_is_presented_as_heard_evidence() -> None:
    decision = build_identity_display(
        status=RecognitionStatus.INTRODUCED,
        display_name="David",
        similarity=0.91,
    )

    assert decision.patient_visible is True
    assert decision.text == "They introduced themselves as David."
    assert decision.is_identity_assertion is False
    assert decision.requires_review is True


def test_opted_out_identity_is_never_patient_visible() -> None:
    decision = build_identity_display(
        status=RecognitionStatus.OPTED_OUT,
        display_name="David",
        similarity=0.99,
    )

    assert decision.patient_visible is False
    assert decision.text == ""
    assert decision.is_identity_assertion is False
    assert decision.requires_review is False
