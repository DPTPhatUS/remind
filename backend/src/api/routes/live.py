import wave
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from api.deps import get_compreface_client
from core.config import get_settings
from core.policies import RecognitionStatus
from db.models import Patient
from db.repositories.people import PeopleRepository
from db.session import AsyncSessionLocal
from providers.openai import (
    OpenAIEmbeddingProvider,
    OpenAIExtractionProvider,
    OpenAITranscriptionProvider,
)
from realtime.audio import WebRtcSpeechDetector
from realtime.connection_manager import ConnectionManager
from realtime.interaction_detector import InteractionDetectorConfig
from realtime.session_orchestrator import LiveSessionOrchestrator, ResolvedIdentity
from schemas.interactions import TranscriptCreate
from services.interaction_service import InteractionService

router = APIRouter()
manager = ConnectionManager()


@router.websocket("/sessions/{session_id}")
async def live_session(websocket: WebSocket, session_id: str) -> None:
    await manager.connect(session_id, websocket)
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Patient).order_by(Patient.created_at.asc()).limit(1))
        patient = result.scalars().first()
    if patient is None:
        await manager.send(
            session_id,
            {
                "type": "session.error",
                "payload": {"message": "Patient profile not found for live session."},
            },
        )
        await websocket.close(code=1008)
        manager.disconnect(session_id)
        return

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
                person_id=person.id,
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
            suffix = ".wav" if content_type == "audio/pcm" else ".audio"
            with NamedTemporaryFile(delete=False, suffix=suffix) as audio_file:
                audio_path = Path(audio_file.name)
                if content_type == "audio/pcm":
                    with wave.open(audio_file, "wb") as wav_file:
                        wav_file.setnchannels(1)
                        wav_file.setsampwidth(2)
                        wav_file.setframerate(settings.live_audio_sample_rate_hz)
                        wav_file.writeframes(audio_bytes)
                else:
                    audio_file.write(audio_bytes)
            try:
                return await transcription_provider.transcribe_file(audio_path)
            finally:
                audio_path.unlink(missing_ok=True)

        audio_transcriber = transcribe_audio

    async def start_interaction(confidence: float) -> str:
        async with AsyncSessionLocal() as session:
            interaction = await InteractionService(session).start_live_interaction(
                patient_id=patient.id,
                started_at=datetime.now(UTC).isoformat(),
                confidence=confidence,
            )
            return interaction.id

    async def close_interaction(interaction_id: str, confidence: float) -> None:
        async with AsyncSessionLocal() as session:
            await InteractionService(session).close_live_interaction(
                interaction_id=interaction_id,
                ended_at=datetime.now(UTC).isoformat(),
                confidence=confidence,
            )

    async def record_participant(
        interaction_id: str,
        person_id: str | None,
        face_subject: str | None,
        recognition_confidence: float | None,
        recognition_status: str,
    ) -> None:
        async with AsyncSessionLocal() as session:
            await InteractionService(session).add_participant(
                interaction_id=interaction_id,
                person_id=person_id,
                face_subject=face_subject,
                face_track_id="primary",
                recognition_confidence=recognition_confidence,
                recognition_status=recognition_status,
            )

    async def record_transcript(
        interaction_id: str,
        text: str,
        started_at_ms: int,
        ended_at_ms: int,
    ) -> None:
        async with AsyncSessionLocal() as session:
            await InteractionService(session).add_transcript(
                interaction_id=interaction_id,
                data=TranscriptCreate(
                    text=text,
                    speaker_label=None,
                    confidence=None,
                    started_at_ms=started_at_ms,
                    ended_at_ms=ended_at_ms,
                ),
            )
            if settings.openai_api_key:
                extraction_provider = OpenAIExtractionProvider(
                    api_key=settings.openai_api_key,
                    model=settings.openai_text_model,
                )
                embedding_provider = OpenAIEmbeddingProvider(
                    api_key=settings.openai_api_key,
                    model=settings.openai_embedding_model,
                    dimensions=settings.openai_embedding_dimensions,
                )
                extraction = await extraction_provider.extract_memory(text)
                await InteractionService(
                    session,
                    embedding_provider=embedding_provider,
                ).create_claims_from_extraction(
                    patient_id=patient.id,
                    interaction_id=interaction_id,
                    extraction=extraction,
                )

    orchestrator = LiveSessionOrchestrator(
        session_id=session_id,
        compreface=get_compreface_client(settings) if settings.compreface_api_key else None,
        subject_resolver=resolve_subject,
        audio_transcriber=audio_transcriber,
        speech_detector=WebRtcSpeechDetector(mode=settings.live_audio_vad_mode),
        detector_config=InteractionDetectorConfig(
            candidate_score=settings.live_interaction_candidate_score,
            active_score=settings.live_interaction_active_score,
            min_candidate_ms=settings.live_interaction_min_candidate_ms,
            end_silence_ms=settings.live_interaction_end_silence_ms,
        ),
        frame_sample_interval_ms=settings.live_frame_sample_interval_ms,
        audio_sample_rate_hz=settings.live_audio_sample_rate_hz,
        audio_utterance_max_ms=settings.live_audio_utterance_max_ms,
        interaction_starter=start_interaction,
        interaction_closer=close_interaction,
        transcript_recorder=record_transcript,
        participant_recorder=record_participant,
    )
    await manager.send(session_id, orchestrator.ready_message())
    try:
        while True:
            message = await websocket.receive_json()
            try:
                response = await orchestrator.handle_message(message)
            except Exception as exc:
                response = {
                    "type": "session.error",
                    "payload": {"message": str(exc)},
                }
            await _send_orchestrator_response(session_id, response)
            if message.get("type") == "session.stop":
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(session_id)


async def _send_orchestrator_response(
    session_id: str,
    response: dict | list[dict] | None,
) -> None:
    if response is None:
        return
    if isinstance(response, list):
        for event in response:
            await manager.send(session_id, event)
        return
    await manager.send(session_id, response)
