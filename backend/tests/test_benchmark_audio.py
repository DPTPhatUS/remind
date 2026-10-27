import numpy as np
import pytest

from remind.audio import processing
from remind.benchmark import audio
from remind.benchmark.inputs import AudioCase
from remind.config import Settings


class Provider:
    def __init__(self):
        self.calls = 0

    async def transcribe(self, pcm):
        self.calls += 1
        return [{"id": "s", "speaker": "A", "text": "Hello", "start_ms": 0, "end_ms": 2000}]


class Verifier:
    def classify(self, pcm, segments, profile):
        return [{**segment, "role": "visitor"} for segment in segments]


def decoded(monkeypatch, *, speech=True, continuous=True):
    monkeypatch.setattr(
        processing,
        "decode_audio",
        lambda _: {"pcm": np.ones(32000, dtype=np.int16), "continuous": continuous},
    )
    monkeypatch.setattr(processing, "has_speech", lambda _: speech)


@pytest.mark.parametrize(
    "reference,continuous,expected",
    [(True, True, "visitor"), (False, True, "uncertain"), (True, False, "uncertain")],
)
async def test_automatic_transcription_precedes_voice_assignment(
    monkeypatch, reference, continuous, expected
):
    decoded(monkeypatch, continuous=continuous)
    provider = Provider()
    result = await processing.process_audio(
        "audio.wav", "clip", provider, Verifier(), {"model": "fixture"} if reference else None
    )
    assert provider.calls == 1
    assert result["segments"][0]["role"] == expected
    assert result["segments"][0]["speaker"] == "A"
    assert result["segments"][0]["id"].startswith("clip:")


async def test_silence_stays_local(monkeypatch):
    decoded(monkeypatch, speech=False)
    provider = Provider()
    result = await processing.process_audio("audio.wav", "clip", provider, Verifier(), None)
    assert not result["has_speech"]
    assert result["segments"] == []
    assert provider.calls == 0


async def test_voice_failure_preserves_transcript_with_uncertain_roles(monkeypatch):
    decoded(monkeypatch)

    class Unavailable(Verifier):
        def classify(self, *args):
            raise RuntimeError("Model unavailable")

    result = await processing.process_audio(
        "audio.wav", "clip", Provider(), Unavailable(), {"model": "fixture"}
    )
    assert result["segments"][0]["role"] == "uncertain"
    assert "unavailable" in result["status"]


async def test_provider_failure_is_not_retried(monkeypatch):
    decoded(monkeypatch)

    class Broken(Provider):
        async def transcribe(self, pcm):
            self.calls += 1
            raise TimeoutError("Provider timeout")

    provider = Broken()
    with pytest.raises(TimeoutError):
        await processing.process_audio("audio.wav", "clip", provider, Verifier(), None)
    assert provider.calls == 1


async def test_audio_runner_uses_model_output_not_expected_labels(tmp_path, monkeypatch):
    recording = {
        "id": "recording",
        "path": "unused.wav",
        "sha256": "0" * 64,
        "source_id": "test",
        "source_start_ms": 0,
        "source_end_ms": 16000,
        "turns": [
            {
                "id": "expected",
                "start_ms": 8000,
                "end_ms": 10000,
                "role": "visitor",
                "text": "Expected words must not reach the model",
            }
        ],
    }
    case = AudioCase.model_validate({"id": "case", "recordings": [recording]})
    monkeypatch.setattr(
        audio,
        "prepare_media",
        lambda *args, **kwargs: {
            "metadata": {},
            "clips": [
                {"path": "first", "start_ms": 0, "end_ms": 8000},
                {"path": "second", "start_ms": 8000, "end_ms": 16000},
            ],
        },
    )

    class ClosingProvider(Provider):
        async def close(self):
            pass

    monkeypatch.setattr(audio, "Providers", lambda _: ClosingProvider())
    calls = []

    async def process(path, source_id, providers, verifier, profile):
        calls.append(path)
        assert profile is None
        return {
            "segments": [
                {
                    "id": source_id,
                    "speaker": "A",
                    "role": "user",
                    "text": "Actual words",
                    "start_ms": 0,
                    "end_ms": 2000,
                }
            ],
            "metrics": {},
            "voice_ready": False,
            "has_speech": True,
            "status": "No reference",
        }

    monkeypatch.setattr(audio, "process_audio", process)
    result = await audio.run_case(
        case, tmp_path, Settings(data_dir=tmp_path, openai_api_key="fixture")
    )
    assert calls == ["first", "second"]
    outcome = result["outcomes"][0]
    assert outcome["segments"][1]["start_ms"] == 8000
    assert outcome["scores"]["roles"]["wrong_role_ms"] == 2000
    assert outcome["scores"]["roles"]["role_accuracy"]["rate"] == 0
