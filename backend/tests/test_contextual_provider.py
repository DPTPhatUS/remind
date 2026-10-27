"""Exercise the actual provider boundary with structured fixture responses."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from remind.audio.providers import Providers
from remind.config import Settings
from remind.memory.extraction import ExtractionResult, VerificationResult, validate_extraction


@pytest.fixture
async def provider():
    instance = Providers(Settings(openai_api_key="fixture-key"))
    try:
        yield instance
    finally:
        await instance.close()


async def test_contextual_extraction_requires_a_separate_verification_pass(provider, monkeypatch):
    segments = [
        {"id": "clip1:q", "role": "user", "text": "How is your brother's teaching job?"},
        {"id": "clip2:a", "role": "visitor", "text": "He enjoys it, but I work at a bank."},
    ]
    candidates = [
        {
            "subject": subject,
            "category": "work",
            "predicate": "occupation",
            "value": value,
            "polarity": "affirmative",
            "temporal_status": "current",
            "valid_from": None,
            "valid_to": None,
            "operation": "add",
            "target_fact_id": None,
            "evidence": [{"segment_id": s["id"], "quote": s["text"]} for s in segments],
        }
        for subject, value in (("visitor", "teacher"), ("visitor", "bank employee"))
    ]
    extraction = ExtractionResult(summary="They discussed work.", facts=candidates)
    assessment = VerificationResult(
        assessments=[
            {
                "fact_index": 0,
                "supported": False,
                "affirmative": False,
                "reason": "Teaching concerns the brother.",
            },
            {
                "fact_index": 1,
                "supported": True,
                "affirmative": True,
                "reason": "Visitor explicitly states their work.",
            },
        ]
    )
    parse = AsyncMock(
        side_effect=[
            SimpleNamespace(output_parsed=extraction),
            SimpleNamespace(output_parsed=assessment),
        ]
    )
    monkeypatch.setattr(provider.client.responses, "parse", parse)
    result = await provider.extract(
        segments,
        "Earlier summary.",
        [],
        "2026-10-26T10:00:00+07:00",
        {"clip2:a"},
    )
    verified = await provider.verify(result["facts"], segments)
    validated = validate_extraction(result, segments, verified, current_ids={"clip2:a"})
    assert [f["value"] for f in validated["facts"]] == ["bank employee"]
    assert parse.await_count == 2
    first, second = [call.kwargs for call in parse.await_args_list]
    assert first["text_format"] is ExtractionResult
    assert second["text_format"] is VerificationResult
    assert first["instructions"] != second["instructions"]
    assert json.loads(first["input"])["segments"] == segments
    assert json.loads(first["input"])["current_segment_ids"] == ["clip2:a"]
    assert json.loads(second["input"])["facts"] == candidates


async def test_diarized_transcription_is_english_with_clip_local_labels(provider, monkeypatch):
    create = AsyncMock(
        return_value=SimpleNamespace(
            model_dump=lambda: {
                "segments": [
                    {"id": "s", "speaker": "A", "text": "Hello.", "start": 0.1, "end": 0.9},
                ]
            }
        )
    )
    monkeypatch.setattr(provider.client.audio.transcriptions, "create", create)
    result = await provider.transcribe(np.ones(16000, dtype=np.int16))
    assert result == [
        {"id": "s", "speaker": "A", "text": "Hello.", "start_ms": 100.0, "end_ms": 900.0}
    ]
    request = create.await_args.kwargs
    assert request["response_format"] == "diarized_json"
    assert request["language"] == "en"
    assert request["chunking_strategy"] == "auto"


@pytest.mark.parametrize("label", [None, ["A"], 7])
async def test_invalid_diarization_labels_remain_unknown(provider, monkeypatch, label):
    create = AsyncMock(
        return_value=SimpleNamespace(
            model_dump=lambda: {
                "segments": [
                    {"id": "s", "speaker": label, "text": "Hello.", "start": 0, "end": 1},
                ]
            }
        )
    )
    monkeypatch.setattr(provider.client.audio.transcriptions, "create", create)
    result = await provider.transcribe(np.ones(16000, dtype=np.int16))
    assert result[0]["speaker"] == "unknown"


@pytest.mark.parametrize("method", ["extract", "verify"])
async def test_missing_structured_output_is_reported(provider, monkeypatch, method):
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=None))
    monkeypatch.setattr(provider.client.responses, "parse", parse)
    with pytest.raises(ValueError, match="no valid structured result"):
        if method == "extract":
            await provider.extract([])
        else:
            await provider.verify([{"value": "Unsupported claim"}], [])


async def test_no_candidates_skips_cloud_verification(provider, monkeypatch):
    parse = AsyncMock()
    monkeypatch.setattr(provider.client.responses, "parse", parse)
    assert await provider.verify([], []) == {"assessments": []}
    parse.assert_not_awaited()
