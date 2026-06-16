from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.deps import get_compreface_client
from core.config import get_settings
from core.policies import RecognitionStatus
from db.repositories.people import PeopleRepository
from db.session import AsyncSessionLocal
from providers.openai import OpenAITranscriptionProvider
from realtime.connection_manager import ConnectionManager
from realtime.session_orchestrator import LiveSessionOrchestrator, ResolvedIdentity

router = APIRouter()
manager = ConnectionManager()


@router.websocket("/sessions/{session_id}")
async def live_session(websocket: WebSocket, session_id: str) -> None:
    await manager.connect(session_id, websocket)
    settings = get_settings()

    async def resolve_subject(subject: str) -> ResolvedIdentity | None:
        async with AsyncSessionLocal() as session:
            person = await PeopleRepository(session).get_person_by_subject(subject)
            if person is None:
                return None
            try:
                status = RecognitionStatus(person.recognition_status)
            except ValueError:
                status = RecognitionStatus.UNKNOWN
            return ResolvedIdentity(
                display_name=person.display_name,
                recognition_status=status,
                relationship_to_patient=person.relationship_to_patient,
                recent_event=None,
                sensitive=person.sensitive,
            )

    audio_transcriber = None
    if settings.openai_api_key:
        transcription_provider = OpenAITranscriptionProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_transcribe_model,
        )

        async def transcribe_audio(audio_bytes: bytes, content_type: str) -> str:
            suffix = ".webm" if content_type == "audio/webm" else ".audio"
            with NamedTemporaryFile(delete=False, suffix=suffix) as audio_file:
                audio_file.write(audio_bytes)
                audio_path = Path(audio_file.name)
            try:
                return await transcription_provider.transcribe_file(audio_path)
            finally:
                audio_path.unlink(missing_ok=True)

        audio_transcriber = transcribe_audio

    orchestrator = LiveSessionOrchestrator(
        session_id=session_id,
        compreface=get_compreface_client(settings),
        subject_resolver=resolve_subject,
        audio_transcriber=audio_transcriber,
    )
    await manager.send(session_id, orchestrator.ready_message())
    try:
        while True:
            message = await websocket.receive_json()
            response = await orchestrator.handle_message(message)
            if response is not None:
                await manager.send(session_id, response)
            if message.get("type") == "session.stop":
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(session_id)
