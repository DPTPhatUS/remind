from remind.memory.extraction import validate_extraction


def test_unknown_speaker_and_fabricated_evidence_rejected():
    segments = [
        {"id": "s", "speaker": "A", "text": "My name is Anna.", "start_ms": 0, "end_ms": 1000}
    ]
    result = {
        "summary": "A visitor introduced themselves.",
        "facts": [
            {
                "person_id": "p",
                "predicate": "name",
                "value": "Anna",
                "segment_ids": ["s"],
                "quote": "My name is Anna.",
            }
        ],
    }
    assert validate_extraction(result, segments, {})["facts"] == []
    accepted = validate_extraction(result, segments, {"A": "p"})
    assert accepted["facts"][0]["value"] == "Anna"
    result["facts"][0]["quote"] = "I am 35 years old."
    assert validate_extraction(result, segments, {"A": "p"})["facts"] == []


def test_third_person_or_conflicting_subject_not_allowed():
    segments = [
        {"id": "s", "speaker": "A", "text": "Anna is my sister.", "start_ms": 0, "end_ms": 1000}
    ]
    result = {
        "summary": "They discussed Anna.",
        "facts": [
            {
                "person_id": "other",
                "predicate": "relationship",
                "value": "sister",
                "segment_ids": ["s"],
                "quote": "Anna is my sister.",
            }
        ],
    }
    assert validate_extraction(result, segments, {"A": "p"})["facts"] == []


def test_value_must_be_supported_by_direct_statement():
    for text, predicate, value in [
        ("My name is Anna.", "name", "Bob"),
        ("I am not your daughter.", "relationship", "daughter"),
        ("She said my name is Anna.", "name", "Anna"),
        ("I am 45 years old.", "age", "35"),
    ]:
        result = {
            "summary": "",
            "facts": [
                {
                    "person_id": "p",
                    "predicate": predicate,
                    "value": value,
                    "segment_ids": ["s"],
                    "quote": text,
                }
            ],
        }
        segments = [{"id": "s", "speaker": "A", "text": text}]
        assert validate_extraction(result, segments, {"A": "p"})["facts"] == []
