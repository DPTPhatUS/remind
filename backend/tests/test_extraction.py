"""Deterministic source checks; semantic fixture results are not accuracy estimates."""

import pytest

from remind.memory.extraction import validate_extraction


def turn(ident, text, role="visitor"):
    return {"id": ident, "text": text, "role": role, "speaker": "A"}


def fact(value="Anna", **kwargs):
    return {
        "subject": "visitor", "category": "identity", "predicate": "name", "value": value,
        "temporal_status": "current", "valid_from": None, "valid_to": None,
        "operation": "add", "target_fact_id": None,
        "evidence": [{"segment_id": "new:1", "quote": "Everyone calls me Anna."}],
        **kwargs,
    }


def verified(*supported):
    return {"assessments": [
        {"fact_index": i, "supported": yes, "reason": "Fixture assessment"}
        for i, yes in enumerate(supported)
    ]}


def accepted(claim, segments, verification=None, **kwargs):
    return validate_extraction(
        {"summary": "An encounter.", "facts": [claim]}, segments,
        verification if verification is not None else verified(True), **kwargs,
    )["facts"]


def test_natural_introduction_does_not_require_fixed_phrase():
    assert accepted(fact(), [turn("new:1", "Everyone calls me Anna.")])[0]["value"] == "Anna"


@pytest.mark.parametrize("role", ["user", "uncertain", None])
def test_user_or_unassigned_statement_is_not_visitor_support(role):
    assert accepted(fact(), [turn("new:1", "Everyone calls me Anna.", role)]) == []


def test_independent_verification_required_and_cannot_be_ambiguous():
    segments = [turn("new:1", "Everyone calls me Anna.")]
    for result in ({"assessments": []}, verified(False),
                   {"assessments": verified(True)["assessments"] * 2}):
        assert accepted(fact(), segments, result) == []


@pytest.mark.parametrize("evidence", [
    [{"segment_id": "missing", "quote": "Everyone calls me Anna."}],
    [{"segment_id": "new:1", "quote": "Everyone calls me Bob."}],
    [{"segment_id": "new:1", "quote": ""}],
])
def test_fabricated_or_empty_evidence_rejected_even_if_model_approves(evidence):
    assert accepted(fact(evidence=evidence), [turn("new:1", "Everyone calls me Anna.")]) == []


def test_contextual_answer_and_confirmation_can_use_previous_clip():
    segments = [
        turn("previous:7", "You still work at the primary school?", "user"),
        turn("new:1", "Yes, I do."),
    ]
    claim = fact("primary school", category="work", predicate="workplace", evidence=[
        {"segment_id": "previous:7", "quote": "You still work at the primary school?"},
        {"segment_id": "new:1", "quote": "Yes, I do."},
    ])
    result = accepted(claim, segments, current_ids={"new:1"})
    assert result[0]["evidence"][0]["segment_id"] == "previous:7"
    assert accepted(claim, segments, current_ids={"unrelated:1"}) == []


def test_uncertain_context_cannot_establish_answer_subject():
    segments = [turn("q", "Is your daughter Mai?", "uncertain"), turn("a", "Yes.")]
    claim = fact("Mai", subject="daughter", evidence=[
        {"segment_id": "q", "quote": "Is your daughter Mai?"},
        {"segment_id": "a", "quote": "Yes."},
    ])
    assert accepted(claim, segments) == []


def test_relative_subject_preserved_separately_from_visitor():
    claim = fact("teacher", subject="brother", category="work", predicate="occupation",
                 evidence=[{"segment_id": "new:1", "quote": "My brother teaches."}])
    assert accepted(claim, [turn("new:1", "My brother teaches.")])[0]["subject"] == "brother"


@pytest.mark.parametrize("text,value,subject", [
    ("My brother teaches.", "teacher", "visitor"),
    ("I am not your daughter.", "daughter", "visitor"),
    ("If I were a teacher, I would enjoy it.", "teacher", "visitor"),
    ("Everyone calls me Anna.", "Bob", "visitor"),
])
def test_semantically_rejected_candidates_never_reach_store(text, value, subject):
    claim = fact(value, subject=subject,
                 evidence=[{"segment_id": "new:1", "quote": text}])
    assert accepted(claim, [turn("new:1", text)], verified(False)) == []


def test_correction_target_must_match_supplied_subject_and_predicate():
    segments = [turn("new:1", "Everyone calls me Anna.")]
    claim = fact(operation="correct", target_fact_id="f")
    existing = [{"id": "f", "subject": "visitor", "predicate": "name", "manual": False}]
    assert accepted(claim, segments, existing_facts=existing)
    assert accepted(claim, segments, existing_facts=[]) == []
    for changed in ({"subject": "brother"}, {"predicate": "occupation"}, {"manual": True}):
        assert accepted(claim, segments, existing_facts=[{**existing[0], **changed}]) == []


def test_add_cannot_smuggle_target_and_model_cannot_choose_person_id():
    segments = [turn("new:1", "Everyone calls me Anna.")]
    assert accepted(fact(target_fact_id="foreign-fact"), segments) == []
    assert accepted(fact(person_id="foreign-person"), segments) == []


def test_past_and_planned_claims_keep_dates_and_temporal_meaning():
    for status in ("past", "planned"):
        text = "I visited Da Nang." if status == "past" else "I plan to visit Da Nang."
        claim = fact("visit Da Nang", category="plans", predicate="trip",
                     temporal_status=status, valid_from="2026-10-27",
                     evidence=[{"segment_id": "new:1", "quote": text}])
        saved = accepted(claim, [turn("new:1", text)])[0]
        assert saved["temporal_status"] == status
        assert saved["valid_from"] == "2026-10-27"
