import asyncio
import base64
import binascii
import contextlib
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from remind.config import Settings
from remind.database import Database
from remind.live.protocol import decode_packet
from remind.live.queues import LatestQueue
from remind.live.session import LiveSession
from remind.memory.store import MemoryStore
from remind.vision.engine import OpenCVVision
from remind.vision.models import ModelRegistry


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


def create_app(settings=None, voice_verifier=None):
    settings = settings or Settings()
    db = Database(str(settings.data_dir / "remind.sqlite3"))
    store = MemoryStore(db)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vision")
    state = {
        "vision": None, "vision_error": "Not started", "session": None,
        "worker": None, "verifier": None,
    }

    @asynccontextmanager
    async def lifespan(app):
        await db.create_schema()
        await store.recover_encounters()
        registry = ModelRegistry(settings.data_dir / "models")
        try:
            state["vision"] = await asyncio.get_running_loop().run_in_executor(
                pool, OpenCVVision, registry, settings.vision_threads
            )
            state["vision_error"] = None
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            state["vision_error"] = str(exc)
        from remind.audio.speaker import UserVoiceVerifier
        from remind.memory.worker import MemoryWorker

        state["verifier"] = voice_verifier or UserVoiceVerifier(settings, registry)
        worker = MemoryWorker(store, settings, registry, verifier=state["verifier"])
        state["worker"] = worker

        async def watchdog():
            while True:
                session = state["session"]
                if (
                    session
                    and not session.stopped
                    and time.monotonic() - session.last_heartbeat > 10
                ):
                    await session.stop()
                await asyncio.sleep(0.25)

        async def maintenance():
            while True:
                await worker.run_once()
                await worker.cleanup()
                await asyncio.sleep(0.25)

        task = asyncio.create_task(maintenance())
        guard = asyncio.create_task(watchdog())
        yield
        if state["session"]:
            await state["session"].stop()
        guard.cancel()
        await asyncio.gather(guard, return_exceptions=True)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await worker.close()
        pool.shutdown(wait=True)
        await db.close()

    app = FastAPI(title="Remind", lifespan=lifespan)
    app.state.store = store
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

    def active(generation, allow_stopped=False):
        session = state["session"]
        if not session or session.generation != generation:
            raise HTTPException(409, "Live session expired; start again")
        if session.stopped and (
            not allow_stopped or time.monotonic() - session.last_heartbeat > 120
        ):
            raise HTTPException(
                409, "Live session expired; download the retained clip before restarting"
            )
        if not session.stopped:
            session.last_heartbeat = time.monotonic()
        return session

    async def voice_state():
        status = await store.voice_status()
        verifier = state["verifier"]
        readiness = (
            verifier.readiness() if verifier and hasattr(verifier, "readiness")
            else {"available": verifier is not None, "error": None}
        )
        return {
            **status,
            "reference_saved": status["ready"],
            "ready": status["ready"] and readiness["available"],
            "model_available": readiness["available"],
            "error": readiness.get("error"),
        }

    @app.get("/api/health")
    async def health():
        voice = await voice_state()
        return {
            "vision": {"available": state["vision"] is not None, "error": state["vision_error"]},
            "memory": {
                "available": bool(settings.openai_api_key),
                "speaker": state["worker"].speaker_status if state["worker"] else "starting",
                "profile_learning_available": bool(settings.openai_api_key) and voice["ready"],
            },
            "voice": voice,
            "thresholds_calibrated": False,
        }

    @app.get("/api/user/voice")
    async def get_voice():
        return await voice_state()

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
        worker = state["worker"]
        if worker is None:
            raise HTTPException(503, "Voice processing is starting")

        def prepare():
            from remind.audio.media import decode_audio

            decoded = [decode_audio(sample, max_seconds=20) for sample in samples]
            if any(not media["continuous"] for media in decoded):
                raise ValueError("Voice samples contain interrupted audio; please record again")
            return state["verifier"].enroll([media["pcm"] for media in decoded])

        try:
            profile = await asyncio.get_running_loop().run_in_executor(worker.pool, prepare)
        except (ImportError, FileNotFoundError, RuntimeError) as exc:
            raise HTTPException(503, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
        await store.set_voice_profile(profile["embeddings"], profile["model"])
        return await voice_state()

    @app.delete("/api/user/voice")
    async def delete_voice():
        await store.delete_voice_profile()
        return await voice_state()

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
        session = state["session"]
        if session:
            await session.stop()
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
        return await store.pending_jobs()

    @app.post("/api/jobs/{ident}/retry")
    async def retry_job(ident: str):
        if not await store.retry_job(ident):
            raise HTTPException(409, "Only failed, retained jobs can be retried")
        return {"status": "pending"}

    @app.post("/api/session")
    async def start():
        if state["vision"] is None:
            raise HTTPException(503, state["vision_error"])
        if state["session"] and not state["session"].stopped:
            raise HTTPException(409, "Another tab is using the camera session. Stop it first.")
        generation = str(uuid4())
        state["session"] = LiveSession(generation, store, settings)
        voice = await voice_state()
        return {
            "generation": generation,
            "memory_available": bool(settings.openai_api_key),
            "voice_ready": voice["ready"],
            "profile_learning_available": bool(settings.openai_api_key) and voice["ready"],
        }

    @app.post("/api/session/{generation}/stop")
    async def stop(generation: str):
        if state["session"] and state["session"].generation == generation:
            await state["session"].stop()
        return {"pending_jobs": len(await store.pending_jobs())}

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
        if not snapshot or not snapshot["versions"]:
            return {"status": "no_participants"}
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
            job = await store.enqueue_job(
                snapshot["encounter"],
                metadata.window_id,
                {**snapshot, "clip_path": str(path.resolve())},
            )
        except ValueError as exc:
            path.unlink(missing_ok=True)
            raise HTTPException(409, str(exc)) from exc
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return {"status": "queued", "job_id": job}

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
        await socket.accept()
        queue = LatestQueue()

        async def receive():
            sequence = -1
            while True:
                header, data = decode_packet(await socket.receive_bytes())
                active(generation)
                if header["generation"] != generation or header["sequence"] <= sequence:
                    continue
                sequence = header["sequence"]
                queue.put((header, data))

        async def process():
            processed = 0
            started = time.monotonic()
            while True:
                header, data = await queue.get()
                before = time.perf_counter()
                try:
                    observations = await asyncio.get_running_loop().run_in_executor(
                        pool, state["vision"].detect, data
                    )
                    tracks = await session.observe(observations, header["capture_ms"])
                    processed += 1
                    await socket.send_json(
                        {
                            "type": "vision",
                            "generation": generation,
                            "sequence": header["sequence"],
                            "capture_ms": header["capture_ms"],
                            "tracks": tracks,
                            "processing_ms": (time.perf_counter() - before) * 1000,
                            "processed_fps": processed / max(0.001, time.monotonic() - started),
                            "dropped": queue.dropped,
                        }
                    )
                except ValueError as exc:
                    await socket.send_json({"type": "error", "message": str(exc)})

        tasks = [asyncio.create_task(receive()), asyncio.create_task(process())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, RuntimeError, ValueError, HTTPException):
            pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with contextlib.suppress(RuntimeError):
                await socket.close()

    return app


app = create_app()
