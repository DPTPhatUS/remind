import pytest

from core.config import Settings
from realtime.audio import AudioFormatError, AudioWindowBuffer
from realtime.frame_sampler import FrameSampler
from realtime.interaction_detector import InteractionDetector, InteractionDetectorConfig

PCM_FRAME = b"\x01\x00" * 320


class FakeSpeechDetector:
    def __init__(self, decisions: list[bool]) -> None:
        self.decisions = decisions
        self.frames: list[bytes] = []

    def is_speech(self, frame: bytes, sample_rate_hz: int) -> bool:
        self.frames.append(frame)
        assert sample_rate_hz == 16000
        return self.decisions.pop(0)


def test_live_detection_settings_have_safe_defaults() -> None:
    settings = Settings()

    assert settings.live_frame_sample_interval_ms == 500
    assert settings.live_interaction_candidate_score == 0.45
    assert settings.live_interaction_active_score == 0.70
    assert settings.live_interaction_min_candidate_ms == 2000
    assert settings.live_interaction_end_silence_ms == 8000
    assert settings.live_audio_sample_rate_hz == 16000
    assert settings.live_audio_vad_mode == 2
    assert settings.live_audio_utterance_max_ms == 12000


def test_frame_sampler_processes_first_frame_then_configured_interval() -> None:
    sampler = FrameSampler(sample_interval_ms=500)

    assert sampler.should_process(1000) is True
    assert sampler.should_process(1200) is False
    assert sampler.should_process(1499) is False
    assert sampler.should_process(1500) is True


def test_audio_buffer_rejects_non_pcm_live_audio() -> None:
    buffer = AudioWindowBuffer(speech_detector=FakeSpeechDetector([]))

    with pytest.raises(AudioFormatError, match="audio/pcm"):
        buffer.accept(
            data=PCM_FRAME,
            content_type="audio/webm",
            sample_rate_hz=16000,
            channels=1,
            sample_width_bits=16,
            captured_at_ms=0,
        )


def test_audio_buffer_emits_utterance_after_trailing_silence() -> None:
    detector = FakeSpeechDetector([True, True, *([False] * 35)])
    buffer = AudioWindowBuffer(
        speech_detector=detector,
        trailing_silence_ms=700,
        max_utterance_ms=12000,
    )

    windows = buffer.accept(
        data=PCM_FRAME * 37,
        content_type="audio/pcm",
        sample_rate_hz=16000,
        channels=1,
        sample_width_bits=16,
        captured_at_ms=1000,
    )

    assert len(windows) == 1
    assert windows[0].started_at_ms == 1000
    assert windows[0].ended_at_ms == 1040
    assert windows[0].speech_ms == 40
    assert windows[0].data.startswith(PCM_FRAME * 2)


def test_interaction_detector_ignores_brief_face_without_speech() -> None:
    detector = InteractionDetector(InteractionDetectorConfig())

    detector.observe_face(now_ms=1000, face_present=True, recognized=True, opted_out=False)
    events = detector.evaluate(now_ms=1000)

    assert events == []
    assert detector.state == "idle"


def test_interaction_detector_starts_after_stable_face_and_speech() -> None:
    detector = InteractionDetector(
        InteractionDetectorConfig(
            min_candidate_ms=2000,
            end_silence_ms=8000,
        )
    )

    detector.observe_face(now_ms=1000, face_present=True, recognized=True, opted_out=False)
    detector.observe_speech(now_ms=1000)
    candidate_events = detector.evaluate(now_ms=1000)
    detector.observe_face(now_ms=3100, face_present=True, recognized=True, opted_out=False)
    detector.observe_speech(now_ms=3100)
    active_events = detector.evaluate(now_ms=3100)

    assert [event.type for event in candidate_events] == ["interaction.candidate"]
    assert [event.type for event in active_events] == ["interaction.started"]
    assert active_events[0].payload["confidence"] >= 0.70
    assert detector.state == "active"


def test_interaction_detector_ends_after_no_recent_activity() -> None:
    detector = InteractionDetector(
        InteractionDetectorConfig(
            min_candidate_ms=0,
            end_silence_ms=8000,
        )
    )
    detector.observe_face(now_ms=1000, face_present=True, recognized=True, opted_out=False)
    detector.observe_speech(now_ms=1000)
    detector.evaluate(now_ms=1000)
    detector.observe_face(now_ms=1100, face_present=True, recognized=True, opted_out=False)
    detector.observe_speech(now_ms=1100)
    detector.evaluate(now_ms=1100)

    ended_events = detector.evaluate(now_ms=9200)

    assert [event.type for event in ended_events] == ["interaction.ended"]
    assert ended_events[0].payload["duration_ms"] == 8200
    assert detector.state == "idle"
