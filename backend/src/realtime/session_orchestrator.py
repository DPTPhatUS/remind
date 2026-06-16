from core.policies import RecognitionStatus
from providers.compreface import CompreFaceClient
from realtime.message_types import ReminderUpdateMessage, SessionErrorMessage, SessionReadyMessage
from services.reminder_service import ReminderContext, compose_reminder


class LiveSessionOrchestrator:
    def __init__(self, *, session_id: str, compreface: CompreFaceClient | None = None) -> None:
        self.session_id = session_id
        self.compreface = compreface

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
        if message_type in {"audio.chunk", "interaction.marker"}:
            return None
        if message_type == "session.stop":
            return None
        return SessionErrorMessage(
            payload={"message": f"Unsupported message type: {message_type}"}
        ).model_dump()

    async def _handle_frame(self, payload: dict) -> dict:
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
