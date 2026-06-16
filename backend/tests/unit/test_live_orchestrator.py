import base64

import pytest

from core.policies import RecognitionStatus
from providers.compreface import BoundingBox, FaceRecognitionResult
from realtime.session_orchestrator import LiveSessionOrchestrator, ResolvedIdentity


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


@pytest.mark.asyncio
async def test_frame_observed_with_image_calls_compreface_and_returns_resolved_reminder() -> None:
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
    )

    response = await orchestrator.handle_message(
        {
            "type": "frame.observed",
            "payload": {
                "image_base64": base64.b64encode(b"frame-bytes").decode("ascii"),
                "filename": "frame.jpg",
            },
        }
    )

    assert compreface.image_bytes == b"frame-bytes"
    assert response is not None
    assert response["type"] == "recognition.update"
    assert response["payload"]["subject"] == "subject-1"
    assert response["payload"]["similarity"] == 0.97
    assert response["payload"]["reminder"]["title"] == "Anna"
    assert response["payload"]["reminder"]["lines"] == [
        "Your daughter",
        "They visited last Sunday.",
    ]


@pytest.mark.asyncio
async def test_audio_chunk_and_interaction_marker_return_acknowledgements() -> None:
    orchestrator = LiveSessionOrchestrator(session_id="session-1")

    audio_response = await orchestrator.handle_message(
        {
            "type": "audio.chunk",
            "payload": {"content_type": "audio/webm", "data": "YWJj"},
        }
    )
    marker_response = await orchestrator.handle_message(
        {
            "type": "interaction.marker",
            "payload": {"marker": "conversation_started"},
        }
    )

    assert audio_response == {
        "type": "audio.received",
        "payload": {
            "content_type": "audio/webm",
            "size_bytes": 3,
        },
    }
    assert marker_response == {
        "type": "interaction.marked",
        "payload": {"marker": "conversation_started"},
    }


@pytest.mark.asyncio
async def test_audio_chunk_uses_transcriber_when_configured() -> None:
    async def transcribe_audio(audio_bytes: bytes, content_type: str) -> str:
        assert audio_bytes == b"abc"
        assert content_type == "audio/webm"
        return "Hi, I am David."

    orchestrator = LiveSessionOrchestrator(
        session_id="session-1",
        audio_transcriber=transcribe_audio,
    )

    response = await orchestrator.handle_message(
        {
            "type": "audio.chunk",
            "payload": {"content_type": "audio/webm", "data": "YWJj"},
        }
    )

    assert response == {
        "type": "transcript.received",
        "payload": {
            "content_type": "audio/webm",
            "size_bytes": 3,
            "text": "Hi, I am David.",
        },
    }
