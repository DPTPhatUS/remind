import hashlib
import json

import pytest
from pydantic import ValidationError

from remind.benchmark.inputs import (
    ConversationManifest,
    TextEncounter,
    load_manifest,
)


def media(tmp_path, ident, start, end, source="source"):
    path = tmp_path / f"{ident}.wav"
    path.write_bytes(ident.encode())
    return {
        "id": ident,
        "path": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_id": source,
        "source_start_ms": start,
        "source_end_ms": end,
    }


def audio_input(tmp_path):
    return {
        "title": "Labelled recordings",
        "annotation_notes": "Independent fixture labels",
        "sources": [{"id": "source", "description": "Fixture", "usage_terms": "Test fixture"}],
        "cases": [
            {
                "id": "wearer",
                "enrollment": [
                    media(tmp_path, f"sample-{i}", i * 4000, i * 4000 + 3000) for i in range(3)
                ],
                "recordings": [
                    {
                        **media(tmp_path, "test", 20000, 28000),
                        "turns": [
                            {
                                "id": "t1",
                                "start_ms": 0,
                                "end_ms": 1000,
                                "role": "visitor",
                                "text": "Hello",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def write_input(tmp_path, value):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value))
    return path


def test_hashes_paths_and_production_enrollment_durations(tmp_path):
    manifest = load_manifest("audio", write_input(tmp_path, audio_input(tmp_path)))
    assert manifest.cases[0].enrollment[0].path == tmp_path / "sample-0.wav"
    assert manifest.cases[0].enrollment[0].duration_ms == 3000
    assert len(manifest.cases) == 1  # No minimum pilot size is imposed.
    (tmp_path / "test.wav").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        load_manifest("audio", tmp_path / "manifest.json")


@pytest.mark.parametrize(
    "change",
    ["overlap", "few_samples", "duration", "source", "duplicate", "bounds", "nonfinite", "extra"],
)
def test_invalid_inputs_fail_before_execution(tmp_path, change):
    value = audio_input(tmp_path)
    case = value["cases"][0]
    recording = case["recordings"][0]
    if change == "overlap":
        recording.update(source_start_ms=0, source_end_ms=8000)
    elif change == "few_samples":
        case["enrollment"] = case["enrollment"][:2]
    elif change == "duration":
        case["enrollment"][0]["source_end_ms"] = 2500
    elif change == "source":
        recording["source_id"] = "missing"
    elif change == "duplicate":
        recording["id"] = case["enrollment"][0]["id"]
    elif change == "bounds":
        recording["turns"][0]["end_ms"] = 9000
    elif change == "nonfinite":
        recording["source_end_ms"] = float("nan")
    else:
        value["legacy_version"] = 1
    with pytest.raises(ValueError):
        load_manifest("audio", write_input(tmp_path, value))


def test_missing_reference_is_an_explicit_supported_test(tmp_path):
    value = audio_input(tmp_path)
    value["cases"][0]["enrollment"] = []
    manifest = load_manifest("audio", write_input(tmp_path, value))
    assert manifest.cases[0].enrollment == []


def test_text_inputs_need_no_media_or_voice_reference():
    manifest = ConversationManifest.model_validate(
        {
            "title": "Dialogue",
            "annotation_notes": "Scripted",
            "cases": [
                {
                    "id": "one",
                    "encounters": [
                        {
                            "id": "meeting",
                            "started_at": "2026-10-27T10:00:00+07:00",
                            "batches": [
                                {
                                    "id": "first",
                                    "start_ms": 0,
                                    "end_ms": 1000,
                                    "turns": [
                                        {
                                            "id": "hello",
                                            "start_ms": 0,
                                            "end_ms": 1000,
                                            "role": "visitor",
                                            "text": "I'm Anna",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )
    assert manifest.cases[0].encounters[0].started_at.utcoffset().total_seconds() == 25200


@pytest.mark.parametrize("change", ["timezone", "batch_overlap", "turn_bounds", "duplicate_turn"])
def test_text_order_and_dates_are_validated(change):
    turn = {"id": "turn", "start_ms": 0, "end_ms": 1000, "role": "visitor", "text": "Hello"}
    value = {
        "id": "meeting",
        "started_at": "2026-10-27T00:00:00+00:00",
        "batches": [{"id": "one", "start_ms": 0, "end_ms": 1000, "turns": [turn]}],
    }
    if change == "timezone":
        value["started_at"] = "2026-10-27T00:00:00"
    elif change == "batch_overlap":
        value["batches"].append(
            {
                "id": "two",
                "start_ms": 500,
                "end_ms": 1500,
                "turns": [{**turn, "id": "second", "start_ms": 500, "end_ms": 1500}],
            }
        )
    elif change == "turn_bounds":
        turn["end_ms"] = 1100
    else:
        value["batches"][0]["turns"].append(dict(turn))
    with pytest.raises(ValidationError):
        TextEncounter.model_validate(value)


def test_enrollment_can_be_reused_across_independent_cases(tmp_path):
    value = audio_input(tmp_path)
    second = json.loads(json.dumps(value["cases"][0]))
    second["id"] = "another-condition"
    value["cases"].append(second)
    manifest = load_manifest("audio", write_input(tmp_path, value))
    assert len(manifest.cases) == 2


def test_relabelling_a_source_cannot_hide_identical_enrollment_and_test_bytes(tmp_path):
    value = audio_input(tmp_path)
    sample = value["cases"][0]["enrollment"][0]
    recording = value["cases"][0]["recordings"][0]
    recording["path"] = sample["path"]
    recording["sha256"] = sample["sha256"]
    with pytest.raises(ValueError, match="overlap"):
        load_manifest("audio", write_input(tmp_path, value))


def test_contradictory_fact_expectations_fail_before_cloud_calls():
    fact = {"id": "yes", "subject": "visitor", "predicate": "name", "value": "Anna"}
    value = {
        "title": "Text",
        "annotation_notes": "Fixture",
        "cases": [
            {
                "id": "case",
                "encounters": [
                    {
                        "id": "meeting",
                        "started_at": "2026-10-27T00:00:00+00:00",
                        "batches": [
                            {
                                "id": "batch",
                                "start_ms": 0,
                                "end_ms": 1000,
                                "turns": [
                                    {
                                        "id": "t",
                                        "role": "visitor",
                                        "text": "Anna",
                                        "start_ms": 0,
                                        "end_ms": 1000,
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "facts": [fact, {**fact, "id": "no", "present": False}],
            }
        ],
    }
    with pytest.raises(ValidationError, match="expected and forbidden"):
        ConversationManifest.model_validate(value)
