"""Deterministic source checks; semantic fixture results are not accuracy estimates."""

import pytest

from remind.memory.extraction import validate_extraction


def turn(ident, text, role="visitor"):
    return {
        "id": ident,
        "text": text,
        "role": role,
        "speaker": "A",
        "association": {
            "status": "attributed",
            "visitor_id": "person",
            "encounter_id": "encounter",
            "person_version": 1,
        },
    }


def fact(value="Anna", **kwargs):
    return {
        "subject": "visitor",
        "category": "identity",
        "predicate": "name",
        "value": value,
        "polarity": "affirmative",
        "temporal_status": "current",
        "valid_from": None,
        "valid_to": None,
        "operation": "add",
        "target_fact_id": None,
        "evidence": [{"segment_id": "new:1", "quote": "Everyone calls me Anna."}],
        **kwargs,
    }


def verified(*supported):
    return {
        "assessments": [
            {"fact_index": i, "supported": yes, "affirmative": yes, "reason": "Fixture assessment"}
            for i, yes in enumerate(supported)
        ]
    }


def accepted(claim, segments, verification=None, **kwargs):
    return validate_extraction(
        {"summary": "An encounter.", "facts": [claim]},
        segments,
        verification if verification is not None else verified(True),
        **kwargs,
        visitor_id="person",
        encounter_id="encounter",
    )["facts"]


def test_natural_introduction_does_not_require_fixed_phrase():
    assert accepted(fact(), [turn("new:1", "Everyone calls me Anna.")])[0]["value"] == "Anna"


@pytest.mark.parametrize("role", ["user", "uncertain", None])
def test_user_or_unassigned_statement_is_not_visitor_support(role):
    assert accepted(fact(), [turn("new:1", "Everyone calls me Anna.", role)]) == []


def test_independent_verification_required_and_cannot_be_ambiguous():
    segments = [turn("new:1", "Everyone calls me Anna.")]
    for result in (
        {"assessments": []},
        verified(False),
        {"assessments": verified(True)["assessments"] * 2},
    ):
        assert accepted(fact(), segments, result) == []


@pytest.mark.parametrize(
    "evidence",
    [
        [{"segment_id": "missing", "quote": "Everyone calls me Anna."}],
        [{"segment_id": "new:1", "quote": "Everyone calls me Bob."}],
        [{"segment_id": "new:1", "quote": ""}],
    ],
)
def test_fabricated_or_empty_evidence_rejected_even_if_model_approves(evidence):
    assert accepted(fact(evidence=evidence), [turn("new:1", "Everyone calls me Anna.")]) == []


def test_contextual_answer_and_confirmation_can_use_previous_clip():
    segments = [
        turn("previous:7", "You still work at the primary school?", "user"),
        turn("new:1", "Yes, I do."),
    ]
    claim = fact(
        "primary school",
        category="work",
        predicate="workplace",
        evidence=[
            {"segment_id": "previous:7", "quote": "You still work at the primary school?"},
            {"segment_id": "new:1", "quote": "Yes, I do."},
        ],
    )
    result = accepted(claim, segments, current_ids={"new:1"})
    assert result[0]["evidence"][0]["segment_id"] == "previous:7"
    assert accepted(claim, segments, current_ids={"unrelated:1"}) == []


def test_uncertain_context_cannot_establish_answer_subject():
    segments = [turn("q", "Is your daughter Mai?", "uncertain"), turn("a", "Yes.")]
    claim = fact(
        "Mai",
        subject="daughter",
        evidence=[
            {"segment_id": "q", "quote": "Is your daughter Mai?"},
            {"segment_id": "a", "quote": "Yes."},
        ],
    )
    assert accepted(claim, segments) == []


def test_relative_subject_preserved_separately_from_visitor():
    claim = fact(
        "teacher",
        subject="brother",
        category="work",
        predicate="occupation",
        evidence=[{"segment_id": "new:1", "quote": "My brother teaches."}],
    )
    assert accepted(claim, [turn("new:1", "My brother teaches.")])[0]["subject"] == "brother"


@pytest.mark.parametrize(
    "text,value,subject",
    [
        ("My brother teaches.", "teacher", "visitor"),
        ("I am not your daughter.", "daughter", "visitor"),
        ("If I were a teacher, I would enjoy it.", "teacher", "visitor"),
        ("Everyone calls me Anna.", "Bob", "visitor"),
    ],
)
def test_semantically_rejected_candidates_never_reach_store(text, value, subject):
    claim = fact(value, subject=subject, evidence=[{"segment_id": "new:1", "quote": text}])
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
        claim = fact(
            "visit Da Nang",
            category="plans",
            predicate="trip",
            temporal_status=status,
            valid_from="2026-10-27",
            evidence=[{"segment_id": "new:1", "quote": text}],
        )
        saved = accepted(claim, [turn("new:1", text)])[0]
        assert saved["temporal_status"] == status
        assert saved["valid_from"] == "2026-10-27"


@pytest.mark.parametrize(
    "category,predicate",
    [
        ("relationship", "relationship to user"),
        ("relationship", "relationship_to_user"),
        ("identity", "relationship"),
        ("age", "stated_age"),
        ("family", "relationship"),
    ],
)
def test_identity_fields_require_canonical_category_and_predicate(category, predicate):
    claim = fact("daughter", category=category, predicate=predicate)
    assert accepted(claim, [turn("new:1", "Everyone calls me Anna.")]) == []


def test_misplaced_core_field_is_rejected_without_discarding_valid_sibling_claims():
    from remind.memory.extraction import ExtractionResult

    text = "My name is Anna. My brother is forty two."
    evidence = [{"segment_id": "new:1", "quote": text}]
    result = ExtractionResult.model_validate(
        {
            "summary": "Anna introduced herself and mentioned her brother's age.",
            "facts": [
                fact("Anna", evidence=evidence),
                fact(
                    "42", subject="brother", category="family", predicate="age", evidence=evidence
                ),
            ],
        }
    )
    validated = validate_extraction(
        result.model_dump(),
        [turn("new:1", text)],
        verified(True, True),
        current_ids={"new:1"},
        visitor_id="person",
        encounter_id="encounter",
    )
    assert [(claim["predicate"], claim["value"]) for claim in validated["facts"]] == [
        ("name", "Anna"),
    ]


@pytest.mark.parametrize(
    "category,predicate,value",
    [
        ("identity", "name", "Ben"),
        ("age", "age", "48"),
        ("relationship", "relationship", "brother"),
    ],
)
def test_denied_identity_values_cannot_become_positive_profile_fields(category, predicate, value):
    text = "No, that is not correct. Please do not assume those things about me."
    claim = fact(
        value,
        category=category,
        predicate=predicate,
        polarity="negative",
        evidence=[{"segment_id": "new:1", "quote": text}],
    )
    # Even an incorrect affirmative assessment cannot turn a declared denial into a fact.
    assert accepted(claim, [turn("new:1", text)]) == []
    claim["polarity"] = "affirmative"
    assessment = {
        "assessments": [
            {"fact_index": 0, "supported": True, "affirmative": False, "reason": "Denial only"}
        ]
    }
    assert accepted(claim, [turn("new:1", text)], assessment) == []


def test_asserted_negative_preference_and_approximate_age_remain_supported():
    for category, predicate, value, text in [
        ("preferences", "drink_preference", "dislikes coffee", "I do not like coffee."),
        ("age", "age", "about 50", "I am about fifty."),
        ("age", "age", "in my thirties", "I am in my thirties."),
    ]:
        claim = fact(
            value,
            category=category,
            predicate=predicate,
            evidence=[{"segment_id": "new:1", "quote": text}],
        )
        saved = accepted(claim, [turn("new:1", text)])[0]
        assert saved["value"] == value
        assert "polarity" not in saved


def test_explicit_age_correction_keeps_new_value_target_and_current_evidence():
    previous = turn("old:1", "I am 42 years old.")
    current = turn("new:1", "I misspoke about my age. I am thirty two, not forty two.")
    existing = [{"id": "age-42", "subject": "visitor", "predicate": "age", "manual": False}]
    replacement = fact(
        "32",
        category="age",
        predicate="age",
        operation="correct",
        target_fact_id="age-42",
        evidence=[
            {
                "segment_id": "new:1",
                "quote": current["text"],
            }
        ],
    )
    saved = accepted(
        replacement, [previous, current], existing_facts=existing, current_ids={"new:1"}
    )[0]
    assert (saved["value"], saved["operation"], saved["target_fact_id"]) == (
        "32",
        "correct",
        "age-42",
    )
    stale = {
        **replacement,
        "value": "42",
        "temporal_status": "past",
        "evidence": [
            {
                "segment_id": "old:1",
                "quote": previous["text"],
            }
        ],
    }
    assert (
        accepted(stale, [previous, current], existing_facts=existing, current_ids={"new:1"}) == []
    )


def test_provider_schema_has_required_polarity_and_canonical_identity_branches():
    from remind.memory.extraction import ExtractionResult, VerificationResult

    schema = ExtractionResult.model_json_schema()
    assert len(schema["properties"]["facts"]["items"]["anyOf"]) == 4
    for branch, category, predicate in [
        ("NameFact", "identity", "name"),
        ("AgeFact", "age", "age"),
        ("RelationshipFact", "relationship", "relationship"),
    ]:
        definition = schema["$defs"][branch]
        assert definition["properties"]["category"]["const"] == category
        assert definition["properties"]["predicate"]["const"] == predicate
        assert "polarity" in definition["required"]
    verifier = VerificationResult.model_json_schema()["$defs"]["FactAssessment"]
    assert "affirmative" in verifier["required"]
    assert schema["$defs"]["RelationshipFact"]["properties"]["subject"]["const"] == "visitor"


def test_visitor_relationship_cannot_turn_the_relationship_value_into_a_subject():
    text = "I am your daughter."
    claim = fact(
        "daughter",
        category="relationship",
        predicate="relationship",
        evidence=[{"segment_id": "new:1", "quote": text}],
    )
    assert accepted({**claim, "subject": "daughter"}, [turn("new:1", text)]) == []
    saved = accepted(claim, [turn("new:1", text)])[0]
    assert (saved["subject"], saved["predicate"], saved["value"]) == (
        "visitor",
        "relationship",
        "daughter",
    )


def test_mentioned_relative_relationship_remains_a_family_claim():
    text = "My brother is your nephew."
    claim = fact(
        "nephew",
        category="family",
        predicate="relationship_to_user",
        subject="brother",
        evidence=[{"segment_id": "new:1", "quote": text}],
    )
    saved = accepted(claim, [turn("new:1", text)])[0]
    assert (saved["subject"], saved["category"], saved["predicate"]) == (
        "brother",
        "family",
        "relationship_to_user",
    )


@pytest.mark.parametrize(
    "category,predicate,value", [("identity", "name", "Ben"), ("age", "age", "42")]
)
def test_name_and_age_claims_can_still_describe_a_relative(category, predicate, value):
    text = "My brother is Ben, and he is forty two."
    claim = fact(
        value,
        category=category,
        predicate=predicate,
        subject="brother",
        evidence=[{"segment_id": "new:1", "quote": text}],
    )
    assert accepted(claim, [turn("new:1", text)])[0]["subject"] == "brother"


@pytest.mark.parametrize(
    "association",
    [
        None,
        {"status": "pending", "visitor_id": "person", "encounter_id": "encounter"},
        {"status": "attributed", "visitor_id": "someone_else", "encounter_id": "encounter"},
        {"status": "attributed", "visitor_id": "person", "encounter_id": "other_encounter"},
    ],
)
def test_voice_role_alone_cannot_authorize_personal_evidence(association):
    source = turn("new:1", "Everyone calls me Anna.")
    source["association"] = association or {}
    assert accepted(fact(), [source]) == []
