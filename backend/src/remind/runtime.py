import asyncio
import logging
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI

from remind.audio.providers import Providers
from remind.audio.speaker import UserVoiceVerifier
from remind.config import Settings
from remind.database import Database
from remind.live.session import LiveSession
from remind.memory.capture import CaptureStore
from remind.memory.jobs import JobQueue
from remind.memory.store import MemoryStore
from remind.memory.worker import MemoryWorker
from remind.vision.engine import OpenCVVision
from remind.vision.models import ModelRegistry

logger = logging.getLogger(__name__)


def report_task_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and (error := task.exception()) is not None:
        logger.error("Background task %s stopped", task.get_name(), exc_info=error)


class Runtime:
    """Own shared processing resources, storage, capture session and background tasks."""

    def __init__(self, settings: Settings, verifier: UserVoiceVerifier | None = None):
        self.settings = settings
        self.database = Database(settings.data_dir / "remind.sqlite3")
        self.store = MemoryStore(self.database, template_threshold=settings.match_threshold)
        self.jobs = JobQueue(self.database)
        self.captures = CaptureStore(self.store, self.jobs, settings.attribution_wait_seconds)
        self.registry = ModelRegistry(settings.data_dir / "models")
        self.verifier = verifier or UserVoiceVerifier(settings, self.registry)
        self.providers = Providers(settings) if settings.openai_api_key else None
        self.memory_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory")
        self.worker = MemoryWorker(
            self.store,
            settings,
            self.captures,
            providers=self.providers,
            verifier=self.verifier,
            pool=self.memory_pool,
        )
        self.vision_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vision")
        self.vision: OpenCVVision | None = None
        self.vision_error: str | None = "Not started"
        self.session: LiveSession | None = None

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        tasks: list[asyncio.Task] = []
        try:
            await self.database.create_schema()
            await self.captures.recover()
            try:
                self.vision = await asyncio.get_running_loop().run_in_executor(
                    self.vision_pool, OpenCVVision, self.registry, self.settings.vision_threads
                )
                self.vision_error = None
            except (FileNotFoundError, ValueError, RuntimeError) as exc:
                self.vision_error = str(exc)

            tasks = [
                asyncio.create_task(self.maintain_memory(), name="memory-worker"),
                asyncio.create_task(self.watch_session(), name="session-watchdog"),
            ]
            for task in tasks:
                task.add_done_callback(report_task_failure)
            yield
        finally:
            if self.session:
                await self.session.stop()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                if self.providers:
                    await self.providers.close()
            finally:
                self.memory_pool.shutdown(wait=True)
            self.vision_pool.shutdown(wait=True)
            await self.database.close()

    async def watch_session(self) -> None:
        while True:
            session = self.session
            if session and not session.stopped and time.monotonic() - session.last_heartbeat > 10:
                await session.stop()
            elif session and not session.stopped:
                await session.maintain()
            await asyncio.sleep(0.25)

    async def maintain_memory(self) -> None:
        while True:
            await self.worker.run_once()
            await self.worker.cleanup()
            await asyncio.sleep(0.25)

    async def voice_status(self) -> dict:
        status = await self.store.voice_status()
        readiness = self.verifier.readiness()
        return {
            **status,
            "reference_saved": status["ready"],
            "ready": status["ready"] and readiness["available"],
            "model_available": readiness["available"],
            "error": readiness["error"],
        }
