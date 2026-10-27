import pytest

from remind.benchmark.conversation_metrics import score_facts, score_roles, word_error_rate


def fact(value, *, subject="visitor", predicate="name", **fields):
    return {"subject": subject, "predicate": predicate, "value": value, **fields}


def turn(start, end, role):
    return {"start_ms": start, "end_ms": end, "role": role}


def test_fact_scores_separate_missing_wrong_subject_unsupported_and_forbidden():
    expected = [
        fact("Anna"),
        fact("33", predicate="age"),
        fact("daughter", predicate="relationship"),
        fact("teacher", subject="brother", predicate="occupation"),
        fact("teacher", predicate="occupation", present=False),
    ]
    actual = [
        fact(" ANNA "),
        fact("daughter", predicate="relationship"),
        fact("teacher", predicate="occupation"),
        fact("doctor", predicate="occupation"),
    ]
    report = score_facts(expected, actual)
    assert report["fact_precision"] == {"numerator": 2, "denominator": 4, "rate": 0.5}
    assert report["fact_coverage"] == {"numerator": 2, "denominator": 4, "rate": 0.5}
    assert report["missing_expected"] == expected[1:2] + expected[3:4]
    assert report["wrong_subject_additions"] == [actual[2]]
    assert report["unsupported_additions"] == [actual[3]]
    assert report["forbidden_additions"] == [actual[2]]
    assert report["required_absence"] == {"numerator": 0, "denominator": 1, "rate": 0}


def test_fact_temporal_state_is_part_of_matching_and_unestablished_rows_do_not_count():
    expected = [fact("teacher", predicate="occupation", temporal_status="past")]
    actual = [
        fact("teacher", predicate="occupation", temporal_status="current"),
        fact("teacher", predicate="occupation", temporal_status="past", status="conflict"),
        fact("teacher", predicate="occupation", temporal_status="past", status="superseded"),
        fact("teacher", predicate="occupation", temporal_status="past", status="dismissed"),
    ]
    report = score_facts(expected, actual)
    assert report["actual_count"] == 1
    assert report["fact_coverage"]["rate"] == 0
    assert report["unsupported_additions"] == actual[:1]


def test_duplicate_claims_cannot_inflate_matching_or_coverage():
    report = score_facts([fact("Anna"), fact(" Anna ")], [fact("Anna"), fact("ANNA")])
    assert report["expected_count"] == report["actual_count"] == 1
    assert report["accepted_records"] == 2
    assert report["duplicate_records"] == 1
    assert report["fact_precision"]["rate"] == 1
    assert report["fact_coverage"]["rate"] == 1


def test_abstaining_preserves_absence_but_does_not_pass_positive_fact_coverage():
    report = score_facts([fact("Anna"), fact("Bob", present=False)], [])
    assert report["fact_precision"]["rate"] is None
    assert report["fact_coverage"]["rate"] == 0
    assert report["required_absence"]["rate"] == 1
    empty = score_facts([], [])
    assert empty["fact_coverage"]["rate"] is None
    assert empty["required_absence"]["rate"] is None


def test_inconsistent_or_incomplete_fact_labels_are_rejected():
    with pytest.raises(ValueError, match="both expected and forbidden"):
        score_facts([fact("Anna"), fact("Anna", present=False)], [])
    with pytest.raises(ValueError, match="require"):
        score_facts([{"predicate": "age", "value": "33"}], [])


def test_roles_are_scored_by_duration_and_not_transcript_segmentation():
    expected = [turn(0, 1000, "user"), turn(1000, 2000, "visitor")]
    actual = [turn(0, 300, "user"), turn(300, 1000, "user"), turn(1000, 2000, "visitor")]
    report = score_roles(expected, actual)
    assert report["role_accuracy"] == {"numerator": 2000, "denominator": 2000, "rate": 1}
    assert report["role_coverage"]["rate"] == 1
    assert report["turn_accuracy"]["rate"] == 1
    assert report["per_role"]["uncertain"]["accuracy"]["rate"] is None


def test_missed_speech_is_distinct_from_uncertain_or_wrong_roles():
    expected = [turn(0, 1000, "visitor")]
    actual = [turn(0, 250, "visitor"), turn(250, 500, "user"), turn(500, 750, "uncertain")]
    report = score_roles(expected, actual)
    assert report["correct_ms"] == 250
    assert report["wrong_role_ms"] == 250
    assert report["uncertain_ms"] == 250
    assert report["missed_ms"] == 250
    assert report["role_accuracy"]["rate"] == 0.25
    assert report["role_coverage"]["rate"] == 0.75
    assert report["decision_coverage"]["rate"] == 0.5
    assert report["decisive_accuracy"]["rate"] == 0.5
    assert report["turn_accuracy"]["rate"] == 0


def test_ambiguous_ground_truth_requires_an_actual_uncertain_decision():
    expected = [turn(0, 1000, "uncertain")]
    abstention = score_roles(expected, [turn(0, 1000, "uncertain")])
    assert abstention["role_accuracy"]["rate"] == 1
    assert abstention["decisive_accuracy"]["rate"] is None
    assert abstention["decision_coverage"]["rate"] == 0
    missing = score_roles(expected, [])
    assert missing["role_accuracy"]["rate"] == 0
    assert missing["role_coverage"]["rate"] == 0
    conflicting = score_roles(expected, [turn(0, 1000, "user"), turn(0, 1000, "visitor")])
    assert conflicting["conflicting_ms"] == 1000
    assert conflicting["role_accuracy"]["rate"] == 0
    assert conflicting["uncertain_ms"] == 0


def test_overlapping_same_role_segments_do_not_double_count_duration():
    report = score_roles(
        [turn(0, 1000, "visitor")],
        [
            turn(0, 750, "visitor"),
            turn(500, 1000, "visitor"),
        ],
    )
    assert report["covered_ms"] == report["correct_ms"] == 1000
    assert report["role_accuracy"]["rate"] == 1


@pytest.mark.parametrize(
    "bad",
    [
        turn(1, 0, "user"),
        turn(-1, 100, "user"),
        turn(0, float("inf"), "visitor"),
        turn(0, 100, "unknown"),
        turn(False, 100, "user"),
    ],
)
def test_invalid_role_annotations_fail_instead_of_looking_successful(bad):
    with pytest.raises(ValueError, match="Role"):
        score_roles([bad], [])


def test_empty_role_labels_have_no_accuracy_estimate():
    report = score_roles([], [turn(0, 1000, "visitor")])
    assert report["role_accuracy"]["rate"] is None
    assert report["role_coverage"]["rate"] is None
    assert report["expected_turns"] == 0
    assert report["actual_segments"] == 1


@pytest.mark.parametrize(
    "reference,hypothesis,errors,words",
    [
        ("My name is Anna.", "MY name is Anna", 0, 4),
        ("I am thirty three", "I am thirty", 1, 4),
        ("I am Anna", "I am Anne", 1, 3),
        ("Anna", "Anna and Anna", 2, 1),
        ("I’m your daughter", "I'm your daughter.", 0, 3),
        ("Anna", "", 1, 1),
    ],
)
def test_word_error_rate_counts_insertions_deletions_substitutions(
    reference, hypothesis, errors, words
):
    report = word_error_rate(reference, hypothesis)
    assert report["errors"] == errors
    assert report["reference_words"] == words
    assert report["rate"] == errors / words


def test_empty_reference_does_not_turn_hallucinated_words_into_a_successful_rate():
    report = word_error_rate("", "Invented speech")
    assert report["errors"] == report["hypothesis_words"] == 2
    assert report["reference_words"] == 0
    assert report["rate"] is None
