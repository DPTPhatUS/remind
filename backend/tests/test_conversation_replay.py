import hashlib

import numpy as np
import pytest
from pydantic import ValidationError

from remind.audio.media import wav_bytes
from remind.benchmark.conversation_replay import (
    AudioFile,
    AudioScenario,
    LabelledTurn,
    capture_payload,
    run_scenario,
    verified_path,
)
from remind.config import Settings
from remind.memory.worker import MemoryWorker
from remind.vision.models import ModelRegistry


def test_recordings_are_checksum_verified_before_evaluation(tmp_path):
    path = tmp_path / "recording.wav"
    path.write_bytes(b"recorded audio")
    recording = AudioFile(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    assert verified_path(tmp_path, recording) == path
    path.write_bytes(b"changed recording")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verified_path(tmp_path, recording)


@pytest.mark.parametrize("start,end", [(100, 50), (0, 8200), (float("nan"), 1000)])
def test_turn_labels_must_fit_the_recorded_clip(start, end):
    with pytest.raises(ValidationError):
        LabelledTurn(start_ms=start, end_ms=end, role="visitor", text="Hello.")


def test_expected_words_and_facts_are_not_part_of_worker_payload(tmp_path):
    payload = capture_payload(
        {"id": "visitor", "version": 1}, "encounter", 2, tmp_path / "clip.webm", 8000
    )
    assert set(payload) == {
        "encounter",
        "visitor_id",
        "versions",
        "voice_version",
        "clip_path",
        "start_ms",
        "end_ms",
        "timeline",
    }
    assert payload["timeline"][0]["ms"] == 8000
    assert payload["timeline"][-1]["ms"] >= 16000
    assert payload["versions"] == {"visitor": 1}


@pytest.mark.parametrize("fail", [False, True])
async def test_replay_reports_durable_results_and_provider_failures(tmp_path, monkeypatch, fail):
    path = tmp_path / "clip.wav"
    path.write_bytes(wav_bytes(np.zeros(8 * 16000, dtype=np.int16)))
    scenario = AudioScenario.model_validate(
        {
            "id": "fixture",
            "clips": [
                {
                    "path": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "turns": [
                        {
                            "start_ms": 0,
                            "end_ms": 2000,
                            "role": "visitor",
                            "text": "My name is Anna.",
                        }
                    ],
                }
            ],
            "expected_facts": [{"subject": "visitor", "predicate": "name", "value": "Anna"}],
        }
    )
    if fail:
        scenario.clips.append(scenario.clips[0].model_copy())

    async def process(self, job, providers):
        if fail:
            raise RuntimeError("Injected provider failure")
        segment_id = f"{job['id']}:0"
        return {
            "segments": [
                {
                    "id": segment_id,
                    "start_ms": 0,
                    "end_ms": 2000,
                    "role": "visitor",
                    "text": "My name is Anna.",
                }
            ],
            "facts": [
                {
                    "subject": "visitor",
                    "category": "identity",
                    "predicate": "name",
                    "value": "Anna",
                    "temporal_status": "current",
                    "operation": "add",
                    "evidence": [{"segment_id": segment_id, "quote": "My name is Anna."}],
                }
            ],
            "summary": "Anna introduced herself.",
        }

    # This tests the evaluation runner and real database, not model accuracy.
    monkeypatch.setattr(MemoryWorker, "_process_job", process)
    settings = Settings(data_dir=tmp_path, openai_api_key="fixture-key")
    result = await run_scenario(
        scenario,
        tmp_path,
        settings,
        ModelRegistry(tmp_path),
        object(),
        {"model": "fixture", "embeddings": [[1, 0]] * 3},
        max_attempts=1,
    )
    assert result["restart_recall_matches"]
    assert result["processing_complete"] is not fail
    assert result["facts"]["fact_coverage"]["rate"] == (0 if fail else 1)
    if fail:
        assert "Injected provider failure" in result["jobs"][0]["error"]
        assert result["transcription"]["errors"] == 8
        assert result["roles"]["expected_turns"] == 2
        assert len(result["jobs"]) == 1
    else:
        assert result["saved_profile"]["name"] == "Anna"
        assert result["roles"]["role_accuracy"]["rate"] == 1
        assert result["transcription"]["errors"] == 0
