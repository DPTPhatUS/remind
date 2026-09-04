import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from core.policies import RecognitionStatus
from providers.compreface import CompreFaceClient
from realtime.audio import AudioFormatError, AudioWindowBuffer, SpeechDetector
from realtime.frame_sampler import FrameSampler
from realtime.interaction_detector import (
    DetectionEvent,
    InteractionDetector,
    InteractionDetectorConfig,
)
from realtime.message_types import (
    RecognitionUpdateMessage,
    ReminderUpdateMessage,
    SessionErrorMessage,
    SessionReadyMessage,
)
from services.reminder_service import ReminderContext, compose_reminder


@dataclass(frozen=True)
class ResolvedIdentity:
    display_name: str | None
    recognition_status: RecognitionStatus
    person_id: str | None = None
    relationship_to_patient: str | None = None
    recent_event: str | None = None


SubjectResolver = Callable[[str], Awaitable[ResolvedIdentity | None]]
AudioTranscriber = Callable[[bytes, str], Awaitable[str]]
InteractionStarter = Callable[[float], Awaitable[str]]
InteractionCloser = Callable[[str, float], Awaitable[None]]
TranscriptRecorder = Callable[[str, str, int, int], Awaitable[None]]
ParticipantRecorder = Callable[
    [str, str | None, str | None, float | None, str],
    Awaitable[None],
]


class LiveSessionOrchestrator:
    def __init__(
        self,
        *,
        session_id: str,
        compreface: CompreFaceClient | None = None,
        subject_resolver: SubjectResolver | None = None,
        audio_transcriber: AudioTranscriber | None = None,
        speech_detector: SpeechDetector | None = None,
        detector_config: InteractionDetectorConfig | None = None,
        frame_sample_interval_ms: int = 500,
        audio_sample_rate_hz: int = 16000,
        audio_utterance_max_ms: int = 12000,
        interaction_starter: InteractionStarter | None = None,
        interaction_closer: InteractionCloser | None = None,
        transcript_recorder: TranscriptRecorder | None = None,
        participant_recorder: ParticipantRecorder | None = None,
    ) -> None:
        self.session_id = session_id
        self.compreface = compreface
        self.subject_resolver = subject_resolver
        self.audio_transcriber = audio_transcriber
        self.frame_sampler = FrameSampler(sample_interval_ms=frame_sample_interval_ms)
        self.detector = InteractionDetector(detector_config or InteractionDetectorConfig())
        self.audio_buffer = (
            AudioWindowBuffer(
                speech_detector=speech_detector,
                expected_sample_rate_hz=audio_sample_rate_hz,
                max_utterance_ms=audio_utterance_max_ms,
            )
            if speech_detector is not None
            else None
        )
        self.interaction_starter = interaction_starter
        self.interaction_closer = interaction_closer
        self.transcript_recorder = transcript_recorder
        self.participant_recorder = participant_recorder
        self.active_interaction_id: str | None = None
        self._recorded_participants: set[tuple[str, str | None, str | None]] = set()

    def ready_message(self) -> dict:
        return SessionReadyMessage(payload={"session_id": self.session_id}).model_dump()

    async def handle_message(self, message: dict) -> dict | list[dict] | None:
        message_type = message.get("type")
        payload = message.get("payload") or {}
        if message_type == "session.start":
            return self.ready_message()
        if message_type == "video.frame":
            return await self._handle_video_frame(payload)
        if message_type == "frame.observed":
            if self._has_client_supplied_identity(payload):
                return SessionErrorMessage(
                    payload={
                        "message": "frame.observed only accepts image_base64 during migration."
                    }
                ).model_dump()
            if not payload.get("image_base64"):
                return SessionErrorMessage(
                    payload={
                        "message": "frame.observed only accepts image_base64 during migration."
                    }
                ).model_dump()
            return await self._handle_video_frame(payload)
        if message_type == "audio.chunk":
            return await self._handle_audio_chunk(payload)
        if message_type == "interaction.marker":
            return {
                "type": "interaction.marked",
                "payload": {"marker": payload.get("marker")},
            }
        if message_type == "session.stop":
            return await self._handle_session_stop()
        return SessionErrorMessage(
            payload={"message": f"Unsupported message type: {message_type}"}
        ).model_dump()

    async def _handle_session_stop(self) -> dict | None:
        if self.active_interaction_id is None:
            return None
        interaction_id = self.active_interaction_id
        confidence = 0.0
        if self.interaction_closer is not None:
            await self.interaction_closer(interaction_id, confidence)
        self.active_interaction_id = None
        return {
            "type": "interaction.ended",
            "payload": {
                "interaction_id": interaction_id,
                "confidence": confidence,
                "reason": "session_stopped",
            },
        }

    async def _handle_video_frame(self, payload: dict) -> list[dict]:
        image_data = base64.b64decode(payload.get("image_base64", ""))
        content_type = payload.get("content_type", "image/jpeg")
        captured_at_ms = int(payload.get("captured_at_ms") or 0)
        events = [
            self._media_accepted(
                media_type="frame",
                content_type=content_type,
                size_bytes=len(image_data),
            )
        ]
        if self.compreface is None or not self.frame_sampler.should_process(captured_at_ms):
            return events
        recognition_event = await self._recognize_frame(payload, image_data, captured_at_ms)
        events.append(recognition_event)
        reminder = recognition_event.get("payload", {}).get("reminder")
        if reminder is not None:
            events.append(ReminderUpdateMessage(payload=reminder).model_dump())
        events.extend(
            await self._materialize_detection_events(
                self.detector.evaluate(now_ms=captured_at_ms)
            )
        )
        return events

    async def _recognize_frame(
        self,
        payload: dict,
        image_bytes: bytes,
        captured_at_ms: int,
    ) -> dict:
        assert self.compreface is not None
        results = await self.compreface.recognize(
            image_bytes,
            filename=payload.get("filename", "frame.jpg"),
        )
        primary = results[0] if results else None
        if primary is None:
            reminder = compose_reminder(
                ReminderContext(
                    display_name=None,
                    recognition_status=RecognitionStatus.UNKNOWN,
                    similarity=None,
                )
            )
            return RecognitionUpdateMessage(
                payload={"matches": [], "reminder": reminder.__dict__}
            ).model_dump()

        resolved = None
        if primary.subject and self.subject_resolver is not None:
            resolved = await self.subject_resolver(primary.subject)

        reminder = None
        if resolved is not None:
            reminder = compose_reminder(
                ReminderContext(
                    display_name=resolved.display_name,
                    recognition_status=resolved.recognition_status,
                    similarity=primary.similarity,
                    relationship_to_patient=resolved.relationship_to_patient,
                    recent_event=resolved.recent_event,
                )
            ).__dict__

        recognition_status = (
            resolved.recognition_status if resolved is not None else RecognitionStatus.UNKNOWN
        )
        self.detector.observe_face(
            now_ms=captured_at_ms,
            face_present=True,
            recognized=resolved is not None,
        )
        if self.active_interaction_id is not None and self.participant_recorder is not None:
            participant_key = (
                self.active_interaction_id,
                resolved.person_id if resolved is not None else None,
                primary.subject,
            )
            if participant_key not in self._recorded_participants:
                self._recorded_participants.add(participant_key)
                await self.participant_recorder(
                    self.active_interaction_id,
                    resolved.person_id if resolved is not None else None,
                    primary.subject,
                    primary.similarity,
                    str(recognition_status),
                )

        return RecognitionUpdateMessage(
            payload={
                "subject": primary.subject,
                "similarity": primary.similarity,
                "face_probability": primary.face_probability,
                "box": primary.box.__dict__,
                "reminder": reminder,
            }
        ).model_dump()

    async def _handle_audio_chunk(self, payload: dict) -> list[dict] | dict:
        audio_data = base64.b64decode(payload.get("data", ""))
        content_type = payload.get("content_type", "application/octet-stream")
        events = [
            self._media_accepted(
                media_type="audio",
                content_type=content_type,
                size_bytes=len(audio_data),
            )
        ]
        if self.audio_buffer is None:
            return events
        try:
            captured_at_ms = int(payload.get("captured_at_ms") or 0)
            windows = self.audio_buffer.accept(
                data=audio_data,
                content_type=content_type,
                sample_rate_hz=int(payload.get("sample_rate_hz") or 0),
                channels=int(payload.get("channels") or 0),
                sample_width_bits=int(payload.get("sample_width_bits") or 0),
                captured_at_ms=captured_at_ms,
            )
        except AudioFormatError as error:
            return SessionErrorMessage(payload={"message": str(error)}).model_dump()

        if not windows:
            events.extend(
                await self._materialize_detection_events(
                    self.detector.evaluate(now_ms=captured_at_ms)
                )
            )
            return events

        for window in windows:
            self.detector.observe_speech(now_ms=window.started_at_ms)
            events.extend(
                await self._materialize_detection_events(
                    self.detector.evaluate(now_ms=window.started_at_ms)
                )
            )
            if self.audio_transcriber is None or self.detector.state not in {
                "candidate",
                "active",
            }:
                continue
            transcript = await self.audio_transcriber(window.data, content_type)
            transcript_payload = {
                "content_type": content_type,
                "size_bytes": len(window.data),
                "text": transcript,
                "started_at_ms": window.started_at_ms,
                "ended_at_ms": window.ended_at_ms,
                "interaction_id": self.active_interaction_id,
            }
            events.append({"type": "transcript.received", "payload": transcript_payload})
            if self.active_interaction_id is not None and self.transcript_recorder is not None:
                await self.transcript_recorder(
                    self.active_interaction_id,
                    transcript,
                    window.started_at_ms,
                    window.ended_at_ms,
                )
        return events

    async def _materialize_detection_events(
        self,
        detection_events: list[DetectionEvent],
    ) -> list[dict]:
        events: list[dict] = []
        for event in detection_events:
            payload = dict(event.payload)
            if event.type == "interaction.started" and self.active_interaction_id is None:
                if self.interaction_starter is not None:
                    self.active_interaction_id = await self.interaction_starter(
                        float(payload["confidence"])
                    )
                payload["interaction_id"] = self.active_interaction_id
            if event.type == "interaction.ended":
                payload["interaction_id"] = self.active_interaction_id
                if self.active_interaction_id is not None and self.interaction_closer is not None:
                    await self.interaction_closer(
                        self.active_interaction_id,
                        float(payload["confidence"]),
                    )
                self.active_interaction_id = None
            events.append({"type": event.type, "payload": payload})
        return events

    def _media_accepted(self, *, media_type: str, content_type: str, size_bytes: int) -> dict:
        return {
            "type": "media.accepted",
            "payload": {
                "media_type": media_type,
                "content_type": content_type,
                "size_bytes": size_bytes,
            },
        }

    def _has_client_supplied_identity(self, payload: dict) -> bool:
        forbidden_fields = {
            "display_name",
            "recognition_status",
            "relationship_to_patient",
            "recent_event",
            "similarity",
        }
        return any(field in payload for field in forbidden_fields)
