import base64

import pytest

from core.policies import RecognitionStatus
from providers.compreface import BoundingBox, FaceRecognitionResult
from realtime.interaction_detector import InteractionDetectorConfig
from realtime.session_orchestrator import LiveSessionOrchestrator, ResolvedIdentity

PCM_FRAME = b"\x01\x00" * 320


class FakeCompreFace:
    def __init__(self) -> None:
        self.image_bytes: bytes | None = None

    async def recognize(self, image_bytes: bytes, *, filename: str = "frame.jpg"):
        self.image_bytes = image_bytes
        return [
            FaceRecognitionResult(
                subject="subject-1",
                similarity=0.97,
                face_probability=0.99,
                box=BoundingBox(probability=0.99, x_min=1, y_min=2, x_max=3, y_max=4),
            )
        ]


class FakeSpeechDetector:
    def __init__(self, decisions: list[bool]) -> None:
        self.decisions = decisions

    def is_speech(self, frame: bytes, sample_rate_hz: int) -> bool:
        assert sample_rate_hz == 16000
        return self.decisions.pop(0)


@pytest.mark.asyncio
async def test_video_frame_calls_compreface_and_returns_backend_recognition() -> None:
    compreface = FakeCompreFace()

    async def resolve_subject(subject: str) -> ResolvedIdentity | None:
        assert subject == "subject-1"
        return ResolvedIdentity(
            display_name="Anna",
            recognition_status=RecognitionStatus.CONFIRMED,
            relationship_to_patient="daughter",
            recent_event="visited last Sunday",
        )

    orchestrator = LiveSessionOrchestrator(
        session_id="session-1",
        compreface=compreface,
        subject_resolver=resolve_subject,
        frame_sample_interval_ms=500,
    )

    response = await orchestrator.handle_message(
        {
            "type": "video.frame",
            "payload": {
                "image_base64": base64.b64encode(b"frame-bytes").decode("ascii"),
                "filename": "frame.jpg",
                "content_type": "image/jpeg",
                "sequence": 1,
                "captured_at_ms": 1000,
            },
        }
    )

    assert compreface.image_bytes == b"frame-bytes"
    assert response is not None
    assert isinstance(response, list)
    assert [event["type"] for event in response] == [
        "media.accepted",
        "recognition.update",
        "reminder.update",
    ]
    recognition = response[1]
    assert recognition["payload"]["subject"] == "subject-1"
    assert recognition["payload"]["similarity"] == 0.97
    assert recognition["payload"]["reminder"]["title"] == "Anna"
    assert recognition["payload"]["reminder"]["lines"] == [
        "Your daughter",
        "They visited last Sunday.",
    ]
    assert response[2]["payload"] == recognition["payload"]["reminder"]


@pytest.mark.asyncio
async def test_frame_observed_rejects_client_supplied_identity_context() -> None:
    orchestrator = LiveSessionOrchestrator(session_id="session-1")

    response = await orchestrator.handle_message(
        {
            "type": "frame.observed",
            "payload": {
                "display_name": "David",
                "recognition_status": "confirmed",
                "similarity": 0.99,
            },
        }
    )

    assert response == {
        "type": "session.error",
        "payload": {"message": "frame.observed only accepts image_base64 during migration."},
    }


@pytest.mark.asyncio
async def test_video_frame_can_emit_candidate_after_recent_speech() -> None:
    compreface = FakeCompreFace()

    async def resolve_subject(subject: str) -> ResolvedIdentity | None:
        return ResolvedIdentity(
            display_name="Anna",
            recognition_status=RecognitionStatus.CONFIRMED,
        )

    orchestrator = LiveSessionOrchestrator(
        session_id="session-1",
        compreface=compreface,
        subject_resolver=resolve_subject,
    )
    orchestrator.detector.observe_speech(now_ms=1000)

    response = await orchestrator.handle_message(
        {
            "type": "video.frame",
            "payload": {
                "image_base64": base64.b64encode(b"frame-bytes").decode("ascii"),
                "filename": "frame.jpg",
                "content_type": "image/jpeg",
                "sequence": 1,
                "captured_at_ms": 1000,
            },
        }
    )

    assert isinstance(response, list)
    assert [event["type"] for event in response] == [
        "media.accepted",
        "recognition.update",
        "reminder.update",
        "interaction.candidate",
    ]


@pytest.mark.asyncio
async def test_audio_chunk_and_interaction_marker_return_acknowledgements() -> None:
    orchestrator = LiveSessionOrchestrator(
        session_id="session-1",
        speech_detector=FakeSpeechDetector([False]),
    )

    audio_response = await orchestrator.handle_message(
        {
            "type": "audio.chunk",
            "payload": {
                "content_type": "audio/pcm",
                "sample_rate_hz": 16000,
                "channels": 1,
                "sample_width_bits": 16,
                "captured_at_ms": 1000,
                "data": base64.b64encode(PCM_FRAME).decode("ascii"),
            },
        }
    )
    marker_response = await orchestrator.handle_message(
        {
            "type": "interaction.marker",
            "payload": {"marker": "conversation_started"},
        }
    )

    assert audio_response == [
        {
            "type": "media.accepted",
            "payload": {
                "media_type": "audio",
                "content_type": "audio/pcm",
                "size_bytes": len(PCM_FRAME),
            },
        }
    ]
    assert marker_response == {
        "type": "interaction.marked",
        "payload": {"marker": "conversation_started"},
    }


@pytest.mark.asyncio
async def test_audio_chunk_starts_interaction_and_persists_transcript_when_speech_repeats() -> None:
    started: list[float] = []
    transcripts: list[tuple[str, str, int, int]] = []

    async def transcribe_audio(audio_bytes: bytes, content_type: str) -> str:
        assert audio_bytes.startswith(PCM_FRAME * 2)
        assert content_type == "audio/pcm"
        return "Hi, I am David."

    async def start_interaction(confidence: float) -> str:
        started.append(confidence)
        return "interaction-1"

    async def record_transcript(
        interaction_id: str,
        text: str,
        started_at_ms: int,
        ended_at_ms: int,
    ) -> None:
        transcripts.append((interaction_id, text, started_at_ms, ended_at_ms))

    orchestrator = LiveSessionOrchestrator(
        session_id="session-1",
        speech_detector=FakeSpeechDetector(
            [True, True, *([False] * 35), True, True, *([False] * 35)]
        ),
        audio_transcriber=transcribe_audio,
        interaction_starter=start_interaction,
        transcript_recorder=record_transcript,
        detector_config=InteractionDetectorConfig(min_candidate_ms=0),
    )
    orchestrator.detector.observe_face(
        now_ms=1000,
        face_present=True,
        recognized=True,
    )

    first_response = await orchestrator.handle_message(
        {
            "type": "audio.chunk",
            "payload": {
                "content_type": "audio/pcm",
                "sample_rate_hz": 16000,
                "channels": 1,
                "sample_width_bits": 16,
                "captured_at_ms": 1000,
                "data": base64.b64encode(PCM_FRAME * 37).decode("ascii"),
            },
        }
    )
    second_response = await orchestrator.handle_message(
        {
            "type": "audio.chunk",
            "payload": {
                "content_type": "audio/pcm",
                "sample_rate_hz": 16000,
                "channels": 1,
                "sample_width_bits": 16,
                "captured_at_ms": 1800,
                "data": base64.b64encode(PCM_FRAME * 37).decode("ascii"),
            },
        }
    )

    assert isinstance(first_response, list)
    assert "interaction.candidate" in [event["type"] for event in first_response]
    assert isinstance(second_response, list)
    assert [event["type"] for event in second_response] == [
        "media.accepted",
        "interaction.started",
        "transcript.received",
    ]
    assert second_response[1]["payload"]["interaction_id"] == "interaction-1"
    assert second_response[2]["payload"]["interaction_id"] == "interaction-1"
    assert started and started[0] >= 0.70
    assert transcripts == [("interaction-1", "Hi, I am David.", 1740, 1780)]


@pytest.mark.asyncio
async def test_audio_window_emits_candidate_even_when_started_long_before_face() -> None:
    """Regression: a speech window that began long before the most recent face
    observation must still produce ``interaction.candidate`` when it closes.
    The detector has to be evaluated at the *current* chunk timestamp, not at
    the window's old ``started_at_ms``; otherwise the recent face looks stale
    and the score drops below the candidate threshold.
    """
    orchestrator = LiveSessionOrchestrator(
        session_id="session-1",
        speech_detector=FakeSpeechDetector(
            [True, True]
            + [False] * 35
            + [False] * 35
        ),
        detector_config=InteractionDetectorConfig(
            candidate_score=0.45,
            active_score=0.70,
            min_candidate_ms=2000,
            end_silence_ms=8000,
        ),
    )

    first_response = await orchestrator.handle_message(
        {
            "type": "audio.chunk",
            "payload": {
                "content_type": "audio/pcm",
                "sample_rate_hz": 16000,
                "channels": 1,
                "sample_width_bits": 16,
                "captured_at_ms": 1000,
                "data": base64.b64encode(PCM_FRAME * 2).decode("ascii"),
            },
        }
    )
    assert isinstance(first_response, list)
    assert "interaction.candidate" not in [
        event["type"] for event in first_response
    ], "No face observed yet — candidate should not fire on first chunk"

    orchestrator.detector.observe_face(
        now_ms=4500,
        face_present=True,
        recognized=True,
    )

    second_response = await orchestrator.handle_message(
        {
            "type": "audio.chunk",
            "payload": {
                "content_type": "audio/pcm",
                "sample_rate_hz": 16000,
                "channels": 1,
                "sample_width_bits": 16,
                "captured_at_ms": 5000,
                "data": base64.b64encode(PCM_FRAME * 70).decode("ascii"),
            },
        }
    )

    assert isinstance(second_response, list)
    assert "interaction.candidate" in [
        event["type"] for event in second_response
    ], (
        "Expected interaction.candidate once face has been observed "
        f"recently, got: {[event['type'] for event in second_response]}"
    )


@pytest.mark.asyncio
async def test_active_video_recognition_records_interaction_participant() -> None:
    compreface = FakeCompreFace()
    participants: list[tuple[str, str | None, str | None, float | None, str]] = []

    async def resolve_subject(subject: str) -> ResolvedIdentity | None:
        return ResolvedIdentity(
            person_id="person-1",
            display_name="Anna",
            recognition_status=RecognitionStatus.CONFIRMED,
        )

    async def record_participant(
        interaction_id: str,
        person_id: str | None,
        face_subject: str | None,
        recognition_confidence: float | None,
        recognition_status: str,
    ) -> None:
        participants.append(
            (
                interaction_id,
                person_id,
                face_subject,
                recognition_confidence,
                recognition_status,
            )
        )

    orchestrator = LiveSessionOrchestrator(
        session_id="session-1",
        compreface=compreface,
        subject_resolver=resolve_subject,
        participant_recorder=record_participant,
    )
    orchestrator.active_interaction_id = "interaction-1"

    await orchestrator.handle_message(
        {
            "type": "video.frame",
            "payload": {
                "image_base64": base64.b64encode(b"frame-bytes").decode("ascii"),
                "filename": "frame.jpg",
                "content_type": "image/jpeg",
                "sequence": 1,
                "captured_at_ms": 1000,
            },
        }
    )

    assert participants == [
        (
            "interaction-1",
            "person-1",
            "subject-1",
            0.97,
            "confirmed",
        )
    ]


@pytest.mark.asyncio
async def test_session_stop_closes_active_interaction() -> None:
    closed: list[tuple[str, float]] = []

    async def close_interaction(interaction_id: str, confidence: float) -> None:
        closed.append((interaction_id, confidence))

    orchestrator = LiveSessionOrchestrator(
        session_id="session-1",
        interaction_closer=close_interaction,
    )
    orchestrator.active_interaction_id = "interaction-1"

    response = await orchestrator.handle_message({"type": "session.stop", "payload": {}})

    assert response == {
        "type": "interaction.ended",
        "payload": {
            "interaction_id": "interaction-1",
            "confidence": 0.0,
            "reason": "session_stopped",
        },
    }
    assert closed == [("interaction-1", 0.0)]
    assert orchestrator.active_interaction_id is None


@pytest.mark.asyncio
async def test_silent_audio_chunk_can_end_stale_active_interaction() -> None:
    closed: list[tuple[str, float]] = []

    async def close_interaction(interaction_id: str, confidence: float) -> None:
        closed.append((interaction_id, confidence))

    orchestrator = LiveSessionOrchestrator(
        session_id="session-1",
        speech_detector=FakeSpeechDetector([False]),
        interaction_closer=close_interaction,
        detector_config=InteractionDetectorConfig(min_candidate_ms=0, end_silence_ms=8000),
    )
    orchestrator.detector.observe_face(
        now_ms=1000,
        face_present=True,
        recognized=True,
    )
    orchestrator.detector.observe_speech(now_ms=1000)
    orchestrator.detector.evaluate(now_ms=1000)
    orchestrator.detector.observe_face(
        now_ms=1100,
        face_present=True,
        recognized=True,
    )
    orchestrator.detector.observe_speech(now_ms=1100)
    orchestrator.detector.evaluate(now_ms=1100)
    orchestrator.active_interaction_id = "interaction-1"

    response = await orchestrator.handle_message(
        {
            "type": "audio.chunk",
            "payload": {
                "content_type": "audio/pcm",
                "sample_rate_hz": 16000,
                "channels": 1,
                "sample_width_bits": 16,
                "captured_at_ms": 9200,
                "data": base64.b64encode(PCM_FRAME).decode("ascii"),
            },
        }
    )

    assert isinstance(response, list)
    assert [event["type"] for event in response] == ["media.accepted", "interaction.ended"]
    assert closed == [("interaction-1", 0.0)]
    assert orchestrator.active_interaction_id is None
