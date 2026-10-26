"""Exercise the actual provider boundary with structured fixture responses."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from remind.audio.providers import Providers
from remind.config import Settings
from remind.memory.extraction import ExtractionResult, VerificationResult, validate_extraction


async def test_contextual_extraction_requires_a_separate_verification_pass():
    segments = [
        {"id": "clip1:q", "role": "user", "text": "How is your brother's teaching job?"},
        {"id": "clip2:a", "role": "visitor", "text": "He enjoys it, but I work at a bank."},
    ]
    candidates = [
        {
            "subject": subject, "category": "work", "predicate": "occupation", "value": value,
            "temporal_status": "current", "valid_from": None, "valid_to": None,
            "operation": "add", "target_fact_id": None,
            "evidence": [{"segment_id": s["id"], "quote": s["text"]} for s in segments],
        }
        for subject, value in (("visitor", "teacher"), ("visitor", "bank employee"))
    ]
    extraction = ExtractionResult(summary="They discussed work.", facts=candidates)
    assessment = VerificationResult(assessments=[
        {"fact_index": 0, "supported": False, "reason": "Teaching concerns the brother."},
        {"fact_index": 1, "supported": True, "reason": "Visitor explicitly states their work."},
    ])
    provider = Providers(Settings(openai_api_key="fixture-key"))
    original_client = provider.client
    parse = AsyncMock(side_effect=[SimpleNamespace(output_parsed=extraction),
                                   SimpleNamespace(output_parsed=assessment)])
    provider.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    try:
        result = await provider.extract(
            segments, "Earlier summary.", [], "2026-10-26T10:00:00+07:00", {"clip2:a"},
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
    finally:
        await original_client.close()


async def test_diarized_transcription_is_english_with_clip_local_labels():
    import numpy as np

    provider = Providers(Settings(openai_api_key="fixture-key"))
    original_client = provider.client
    create = AsyncMock(return_value=SimpleNamespace(model_dump=lambda: {"segments": [
        {"id": "s", "speaker": "A", "text": "Hello.", "start": 0.1, "end": 0.9},
    ]}))
    provider.client = SimpleNamespace(audio=SimpleNamespace(
        transcriptions=SimpleNamespace(create=create),
    ))
    try:
        result = await provider.transcribe(np.ones(16000, dtype=np.int16))
        assert result == [{"id": "s", "speaker": "A", "text": "Hello.",
                           "start_ms": 100., "end_ms": 900.}]
        request = create.await_args.kwargs
        assert request["response_format"] == "diarized_json"
        assert request["language"] == "en"
        assert request["chunking_strategy"] == "auto"
    finally:
        await original_client.close()
