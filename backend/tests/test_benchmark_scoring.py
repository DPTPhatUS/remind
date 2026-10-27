import pytest

from remind.benchmark.scoring import (
    fraction,
    percentiles,
    score_facts,
    score_roles,
    word_error_rate,
)


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
    assert report["raw_exact_precision"] == {"numerator": 2, "denominator": 4, "rate": 0.5}
    assert report["fact_coverage"] == {"numerator": 2, "denominator": 4, "rate": 0.5}
    assert report["missing_expected"] == expected[1:2] + expected[3:4]
    assert report["wrong_subject_additions"] == [actual[2]]
    assert report["unmatched_additions_require_review"] == [actual[3]]
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
    assert report["unmatched_additions_require_review"] == actual[:1]


def test_duplicate_claims_cannot_inflate_matching_or_coverage():
    report = score_facts([fact("Anna"), fact(" Anna ")], [fact("Anna"), fact("ANNA")])
    assert report["expected_count"] == report["actual_count"] == 1
    assert report["accepted_records"] == 2
    assert report["duplicate_records"] == 1
    assert report["raw_exact_precision"]["rate"] == 1
    assert report["fact_coverage"]["rate"] == 1


def test_abstaining_preserves_absence_but_does_not_pass_positive_fact_coverage():
    report = score_facts([fact("Anna"), fact("Bob", present=False)], [])
    assert report["raw_exact_precision"]["rate"] is None
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


@pytest.mark.parametrize("latency", [-1, float("nan"), float("inf")])
def test_latency_reports_reject_invalid_measurements(latency):
    with pytest.raises(ValueError, match="finite and non-negative"):
        percentiles([latency])


def test_fraction_supports_duration_sums_and_preserves_missing_denominators():
    assert fraction(12.5, 25) == {"numerator": 12.5, "denominator": 25, "rate": 0.5}
    assert fraction(0, 0) == {"numerator": 0, "denominator": 0, "rate": None}
    assert fraction(0.1 + 0.2, 0.3) == {
        "numerator": 0.3,
        "denominator": 0.3,
        "rate": 1,
    }
    assert fraction(-1e-12, 5)["rate"] == 0


@pytest.mark.parametrize(
    "numerator,denominator",
    [
        (2, 1),
        (-1, 5),
        (1, 0),
        (0, -1),
        (1.01, 1.0),
        (-0.01, 1.0),
        (float("nan"), 1),
        (1, float("inf")),
        (10**12 + 1, 10**12),
        (10**12 + 1.0, 10**12),
        (1e-12, 0),
    ],
)
def test_fraction_rejects_invalid_inputs_instead_of_clamping_real_errors(numerator, denominator):
    with pytest.raises(ValueError, match="Invalid metric"):
        fraction(numerator, denominator)


def test_identity_mapping_requires_faces_and_cannot_use_learned_names():
    from remind.benchmark.scoring import score_identity

    labels = [{"start_ms": 0, "end_ms": 1000, "face_count": 1, "visitor_id": "visitor"}]
    result = score_identity(
        labels,
        [{"source_ms": 100, "tracks": [{"person_id": None, "memory": {"name": "Anna"}}]}],
        {},
        aligned=True,
    )
    assert result["identity_map"] == {}
    assert result["frame_accuracy"]["rate"] == 0
    assert result["missed_associations"] == 1


def test_ambiguous_face_mappings_require_review_and_multiple_faces_are_counted():
    from remind.benchmark.scoring import score_identity

    labels = [
        {"start_ms": 0, "end_ms": 1000, "face_count": 1, "visitor_id": "visitor"},
        {"start_ms": 1000, "end_ms": 2000, "face_count": 2, "visitor_id": None},
    ]
    frames = [
        {"source_ms": 100, "tracks": [{"person_id": "one"}]},
        {"source_ms": 200, "tracks": [{"person_id": "two"}]},
        {"source_ms": 1100, "tracks": [{"person_id": "one"}, {"person_id": "two"}]},
    ]
    result = score_identity(labels, frames, {}, aligned=True)
    assert result["ambiguous_mappings"] == ["visitor"]
    assert result["face_count_accuracy"]["rate"] == 1
    assert result["frame_accuracy"]["rate"] == 0
    assert result["duplicate_profiles"] == {"visitor": ["one", "two"]}


def test_invalid_alignment_cannot_establish_a_new_identity():
    from remind.benchmark.scoring import score_identity

    result = score_identity([], [], {"visitor": "known"}, aligned=False)
    assert result["identity_map"] == {"visitor": "known"}
    assert result["frame_accuracy"]["rate"] is None


def test_fact_latency_uses_only_new_current_evidence_with_polling_uncertainty():
    from remind.benchmark.scoring import score_latency

    facts = [
        {"id": "new", "evidence": [{"segment_id": "current", "quote": "Hello"}]},
        {"id": "old", "evidence": [{"segment_id": "prior", "quote": "Old"}]},
    ]
    segments = [
        {"id": "current", "end_ms": 1000, "current_encounter": True},
        {"id": "prior", "end_ms": 500, "current_encounter": False},
    ]
    observed = {
        "alignment_valid": True,
        "prior_fact_ids": ["old"],
        "clock_samples": [
            {"source_ms": 0, "performance_ms": 0},
            {"source_ms": 2000, "performance_ms": 2100},
        ],
        "fact_observations": [
            {"fact_id": "new", "performance_ms": 3000, "poll_interval_ms": 500},
            {"fact_id": "old", "performance_ms": 3000, "poll_interval_ms": 500},
        ],
    }
    report = score_latency(facts, observed, segments)
    assert report["speech_to_saved"]["count"] == 1
    assert report["measurements"][0]["latency_ms"] == 1950
    assert report["measurements"][0]["poll_uncertainty_ms"] == 500
    observed["alignment_valid"] = False
    assert score_latency(facts, observed, segments)["speech_to_saved"]["count"] == 0


@pytest.mark.parametrize(
    "samples",
    [
        [{"source_ms": 0, "performance_ms": 0}, {"source_ms": 1, "performance_ms": float("nan")}],
        [{"source_ms": 1, "performance_ms": 0}, {"source_ms": 0, "performance_ms": 1}],
    ],
)
def test_clock_rejects_nonfinite_or_nonmonotonic_samples(samples):
    from remind.benchmark.scoring import clock_time

    with pytest.raises(ValueError):
        clock_time(samples, 0)


def test_duplicate_frame_responses_cannot_inflate_face_denominators():
    from remind.benchmark.scoring import score_identity

    visible = [{"start_ms": 0, "end_ms": 1000, "face_count": 1, "visitor_id": "visitor"}]
    frame = {"source_ms": 100, "tracks": [{"person_id": "profile"}]}
    result = score_identity(visible, [frame, dict(frame)], {}, aligned=True)
    assert result["frame_accuracy"]["denominator"] == 1
    assert result["duplicate_frame_responses"] == 1
