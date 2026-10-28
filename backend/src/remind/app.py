import asyncio
import base64
import binascii
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from remind.audio.media import decode_audio
from remind.audio.speaker import UserVoiceVerifier
from remind.config import Settings
from remind.live.session import LiveSession
from remind.live.stream import serve_vision
from remind.runtime import Runtime


class Correction(BaseModel):
    version: int
    fields: dict[str, str | None]


class ClipMetadata(BaseModel):
    window_id: str = Field(min_length=1, max_length=100)
    start_ms: float = Field(ge=0, allow_inf_nan=False)
    end_ms: float = Field(ge=0, allow_inf_nan=False)


class VoiceEnrollment(BaseModel):
    samples: list[str] = Field(min_length=3, max_length=5)


class FactCorrection(BaseModel):
    version: int
    value: str = Field(min_length=1, max_length=500)


class FactRemoval(BaseModel):
    version: int


def create_app(
    settings: Settings | None = None, voice_verifier: UserVoiceVerifier | None = None
) -> FastAPI:
    settings = settings or Settings()
    runtime = Runtime(settings, voice_verifier)
    store = runtime.store
    app = FastAPI(title="Remind", lifespan=runtime.lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def origin_guard(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in settings.origins:
            return Response("Origin not allowed", status_code=403)
        return await call_next(request)

    def active(generation: str, allow_stopped: bool = False) -> LiveSession:
        session = runtime.session
        if not session or session.generation != generation:
            raise HTTPException(409, "Live session expired; start again")
        if session.forgotten:
            raise HTTPException(409, "This capture session was forgotten; start again")
        if session.stopped and (
            not allow_stopped or time.monotonic() - session.last_heartbeat > 120
        ):
            raise HTTPException(
                409, "Live session expired; download the retained clip before restarting"
            )
        if not session.stopped:
            session.last_heartbeat = time.monotonic()
        return session

    @app.get("/api/health")
    async def health():
        voice = await runtime.voice_status()
        return {
            "vision": {"available": runtime.vision is not None, "error": runtime.vision_error},
            "memory": {
                "available": bool(settings.openai_api_key),
                "speaker": runtime.worker.speaker_status,
                "profile_learning_available": bool(settings.openai_api_key) and voice["ready"],
            },
            "voice": voice,
            "thresholds_calibrated": False,
        }

    @app.get("/api/user/voice")
    async def get_voice():
        return await runtime.voice_status()

    @app.post("/api/user/voice")
    async def enroll_voice(request: Request):
        # Bound the request before JSON/base64 allocation. No enrollment media is written to disk.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16 * 1024 * 1024:
                raise HTTPException(413, "Voice samples exceed 16 MiB")
        try:
            enrollment = VoiceEnrollment.model_validate_json(bytes(body))
            samples = [base64.b64decode(sample, validate=True) for sample in enrollment.samples]
        except (ValidationError, ValueError, binascii.Error) as exc:
            raise HTTPException(
                422, "Provide three to five base64-encoded voice recordings"
            ) from exc
        if any(not sample or len(sample) > 4 * 1024 * 1024 for sample in samples):
            raise HTTPException(422, "Each voice recording must be between 1 byte and 4 MiB")
        worker = runtime.worker

        def prepare():
            decoded = [decode_audio(sample, max_seconds=20) for sample in samples]
            if any(not media["continuous"] for media in decoded):
                raise ValueError("Voice samples contain interrupted audio; please record again")
            return runtime.verifier.enroll([media["pcm"] for media in decoded])

        try:
            profile = await asyncio.get_running_loop().run_in_executor(worker.pool, prepare)
        except (ImportError, FileNotFoundError, RuntimeError) as exc:
            raise HTTPException(503, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
        await store.set_voice_profile(profile["embeddings"], profile["model"])
        return await runtime.voice_status()

    @app.delete("/api/user/voice")
    async def delete_voice():
        await store.delete_voice_profile()
        return await runtime.voice_status()

    @app.get("/api/people")
    async def people():
        return await store.list_people()

    @app.get("/api/people/{ident}")
    async def person(ident: str):
        result = await store.person_memory(ident)
        if result is None:
            raise HTTPException(404, "Person not found")
        return result

    @app.get("/api/people/{ident}/thumbnail")
    async def thumbnail(ident: str):
        data = await store.thumbnail(ident)
        if not data:
            raise HTTPException(404, "No thumbnail")
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.patch("/api/people/{ident}")
    async def correct(ident: str, correction: Correction):
        if any(value and len(value) > 500 for value in correction.fields.values()):
            raise HTTPException(422, "Field too long")
        try:
            return await store.correct_person(ident, correction.fields, correction.version)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.delete("/api/people/{ident}")
    async def forget(ident: str):
        session = runtime.session
        if session:
            await session.stop(forgetting=True)
            async with session.lock:
                await store.forget_person(ident)
                session.timeline.clear()
        else:
            await store.forget_person(ident)
        return {"forgotten": True}

    @app.patch("/api/people/{ident}/facts/{fact_id}")
    async def correct_fact(ident: str, fact_id: str, correction: FactCorrection):
        try:
            await store.correct_fact(ident, fact_id, correction.value, correction.version)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return await store.person_memory(ident)

    @app.delete("/api/people/{ident}/facts/{fact_id}")
    async def dismiss_fact(ident: str, fact_id: str, removal: FactRemoval):
        try:
            await store.dismiss_fact(ident, fact_id, removal.version)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return await store.person_memory(ident)

    @app.get("/api/jobs")
    async def jobs():
        return await runtime.captures.pending_jobs()

    @app.post("/api/jobs/{ident}/retry")
    async def retry_job(ident: str):
        if not await runtime.captures.retry_job(ident):
            raise HTTPException(409, "Only failed, retained jobs can be retried")
        return {"status": "pending"}

    @app.post("/api/session")
    async def start():
        if runtime.vision is None:
            raise HTTPException(503, runtime.vision_error)
        if runtime.session and not runtime.session.stopped:
            raise HTTPException(409, "Another tab is using the camera session. Stop it first.")
        generation = str(uuid4())
        await store.start_session(generation)
        runtime.session = LiveSession(generation, store, settings)
        voice = await runtime.voice_status()
        return {
            "generation": generation,
            "memory_available": bool(settings.openai_api_key),
            "voice_ready": voice["ready"],
            "profile_learning_available": bool(settings.openai_api_key) and voice["ready"],
        }

    @app.post("/api/session/{generation}/stop")
    async def stop(generation: str):
        if runtime.session and runtime.session.generation == generation:
            await runtime.session.stop()
        return {"pending_jobs": len(await runtime.captures.pending_jobs())}

    @app.post("/api/live/{generation}/clips")
    async def clip(generation: str, request: Request):
        session = active(generation, allow_stopped=True)
        if not settings.openai_api_key:
            raise HTTPException(503, "Configure REMIND_OPENAI_API_KEY to save conversations")
        try:
            metadata = ClipMetadata.model_validate_json(request.query_params.get("metadata", "{}"))
        except ValidationError as exc:
            raise HTTPException(422, "Invalid clip metadata") from exc
        if not 0 < metadata.end_ms - metadata.start_ms <= 10000:
            raise HTTPException(422, "Invalid clip duration")
        snapshot = await session.snapshot(metadata.start_ms, metadata.end_ms)
        spool = settings.data_dir / "spool"
        spool.mkdir(parents=True, exist_ok=True)
        used = sum(p.stat().st_size for p in spool.glob("*") if p.is_file())
        if used >= settings.spool_limit_bytes:
            raise HTTPException(507, "Memory storage is full; recording paused")
        path = spool / (str(uuid4()) + ".webm")
        total = 0
        try:
            with path.open("wb") as f:
                async for chunk in request.stream():
                    total += len(chunk)
                    if used + total > settings.spool_limit_bytes:
                        raise HTTPException(507, "Memory storage is full; recording paused")
                    if total > 16 * 1024 * 1024:
                        raise HTTPException(413, "Clip exceeds 16 MiB")
                    f.write(chunk)
            if total == 0:
                raise HTTPException(422, "Clip is empty")
            receipt = await runtime.captures.receive_clip(
                generation,
                metadata.window_id,
                metadata.start_ms,
                metadata.end_ms,
                str(path.resolve()),
                snapshot["timeline"],
                snapshot["voice_version"],
            )
            if session.stopped:
                await runtime.captures.update_timeline(generation, session.timeline, final=True)
        except ValueError as exc:
            path.unlink(missing_ok=True)
            raise HTTPException(409, str(exc)) from exc
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return receipt

    @app.websocket("/api/live/{generation}/vision")
    async def vision(socket: WebSocket, generation: str):
        if socket.headers.get("origin") not in settings.origins:
            await socket.close(code=1008)
            return
        try:
            session = active(generation)
        except HTTPException:
            await socket.close(code=1008)
            return
        engine = runtime.vision
        if engine is None:
            await socket.close(code=1011)
            return
        await socket.accept()
        await serve_vision(socket, session, engine, runtime.vision_pool)

    return app


app = create_app()
