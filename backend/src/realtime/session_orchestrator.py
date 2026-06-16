import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from core.policies import RecognitionStatus
from providers.compreface import CompreFaceClient
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
    relationship_to_patient: str | None = None
    recent_event: str | None = None
    sensitive: bool = False


SubjectResolver = Callable[[str], Awaitable[ResolvedIdentity | None]]
AudioTranscriber = Callable[[bytes, str], Awaitable[str]]


class LiveSessionOrchestrator:
    def __init__(
        self,
        *,
        session_id: str,
        compreface: CompreFaceClient | None = None,
        subject_resolver: SubjectResolver | None = None,
        audio_transcriber: AudioTranscriber | None = None,
    ) -> None:
        self.session_id = session_id
        self.compreface = compreface
        self.subject_resolver = subject_resolver
        self.audio_transcriber = audio_transcriber

    def ready_message(self) -> dict:
        return SessionReadyMessage(payload={"session_id": self.session_id}).model_dump()

    async def handle_message(self, message: dict) -> dict | None:
        message_type = message.get("type")
        payload = message.get("payload") or {}
        if message_type == "session.start":
            return self.ready_message()
        if message_type == "correction.submitted":
            return ReminderUpdateMessage(
                payload={
                    "title": "Correction saved for caregiver review.",
                    "lines": [],
                    "requires_review": True,
                }
            ).model_dump()
        if message_type == "frame.observed":
            return await self._handle_frame(payload)
        if message_type == "audio.chunk":
            audio_data = base64.b64decode(payload.get("data", ""))
            content_type = payload.get("content_type", "application/octet-stream")
            if self.audio_transcriber is not None:
                transcript = await self.audio_transcriber(audio_data, content_type)
                return {
                    "type": "transcript.received",
                    "payload": {
                        "content_type": content_type,
                        "size_bytes": len(audio_data),
                        "text": transcript,
                    },
                }
            return {
                "type": "audio.received",
                "payload": {
                    "content_type": content_type,
                    "size_bytes": len(audio_data),
                },
            }
        if message_type == "interaction.marker":
            return {
                "type": "interaction.marked",
                "payload": {"marker": payload.get("marker")},
            }
        if message_type == "session.stop":
            return None
        return SessionErrorMessage(
            payload={"message": f"Unsupported message type: {message_type}"}
        ).model_dump()

    async def _handle_frame(self, payload: dict) -> dict:
        if payload.get("image_base64") and self.compreface is not None:
            return await self._recognize_frame(payload)

        display_name = payload.get("display_name")
        similarity = payload.get("similarity")
        status = RecognitionStatus(payload.get("recognition_status", "unknown"))
        reminder = compose_reminder(
            ReminderContext(
                display_name=display_name,
                recognition_status=status,
                similarity=float(similarity) if similarity is not None else None,
                relationship_to_patient=payload.get("relationship_to_patient"),
                recent_event=payload.get("recent_event"),
                sensitive=bool(payload.get("sensitive", False)),
            )
        )
        return ReminderUpdateMessage(payload=reminder.__dict__).model_dump()

    async def _recognize_frame(self, payload: dict) -> dict:
        assert self.compreface is not None
        image_bytes = base64.b64decode(payload["image_base64"])
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
                    sensitive=resolved.sensitive,
                )
            ).__dict__

        return RecognitionUpdateMessage(
            payload={
                "subject": primary.subject,
                "similarity": primary.similarity,
                "face_probability": primary.face_probability,
                "box": primary.box.__dict__,
                "reminder": reminder,
            }
        ).model_dump()
