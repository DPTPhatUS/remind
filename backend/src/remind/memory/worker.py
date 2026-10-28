import asyncio
import contextlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from remind.audio.processing import process_audio
from remind.audio.providers import Providers
from remind.audio.speaker import UserVoiceVerifier
from remind.config import Settings
from remind.database import Record
from remind.memory.capture import CaptureStore, milliseconds
from remind.memory.learning import learn_conversation
from remind.memory.store import MemoryStore
from remind.vision.models import ModelRegistry

logger = logging.getLogger(__name__)


class MemoryWorker:
    def __init__(
        self,
        store: MemoryStore,
        settings: Settings,
        registry: ModelRegistry,
        verifier: UserVoiceVerifier | None = None,
        pool: ThreadPoolExecutor | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.captures = CaptureStore(store, settings.attribution_wait_seconds)
        self.providers = Providers(settings) if settings.openai_api_key else None
        self.verifier = verifier or UserVoiceVerifier(settings, registry)
        self.speaker_status = "User voice setup required"
        self.pool = pool or ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory")
        self.owns_pool = pool is None

    async def run_once(self) -> bool:
        if self.providers is None:
            self.speaker_status = "Conversation processing needs API key"
            return False
        job = await self.captures.claim_job("memory")
        if job is None:
            return False
        renewal = asyncio.create_task(self._renew_lease(job))
        try:
            await self._process_job(job, self.providers)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.captures.fail_job(
                job["id"],
                job["lease_token"],
                type(exc).__name__ + ": " + str(exc)[:160],
                milliseconds(),
            )
        finally:
            renewal.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renewal
        return True

    async def _renew_lease(self, job: Record) -> None:
        while True:
            await asyncio.sleep(30)
            if not await self.captures.renew_lease(job["id"], job["lease_token"], milliseconds()):
                return

    async def _process_job(self, job: Record, providers: Providers) -> None:
        started = time.perf_counter()
        clip = job["clip"]
        if job["kind"] == "audio":
            profile = await self.store.voice_profile()
            if profile is not None and profile["version"] != clip["voice_version"]:
                profile = None
            audio = await process_audio(
                clip["path"], job["id"], providers, self.verifier, profile, self.pool
            )
            self.speaker_status = audio["status"]
            audio["metrics"]["processing_ms"] = round((time.perf_counter() - started) * 1000, 2)
            await self.captures.finish_audio(job, audio)
            return
        segments = await self.captures.learning_segments(job)
        payload = job["payload"]
        result = await learn_conversation(
            self.store,
            providers,
            self.settings,
            job["encounter_id"],
            payload["visitor_id"],
            segments,
            payload["start_ms"],
            can_learn=bool(clip["voice_ready"] or clip["input_kind"] == "conversation"),
        )
        result["metrics"]["processing_ms"] = round((time.perf_counter() - started) * 1000, 2)
        result["metrics"]["attribution_wait_ms"] = max(
            0, clip["attribution_finalized_ms"] - clip["audio_completed_ms"]
        )
        result["metrics"]["receipt_to_audio_ms"] = max(
            0, clip["audio_completed_ms"] - clip["received_ms"]
        )
        await self.captures.finish_learning(job, result)

    async def cleanup(self) -> None:
        await self.captures.expire()
        root = (self.settings.data_dir / "spool").resolve()
        for pending in await self.store.pending_cleanup():
            path = Path(pending).resolve()
            if path.is_relative_to(root):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove recording %s", path.name)
                    continue
            await self.store.complete_cleanup(pending)
        if root.exists():
            # Clean abandoned uploads as well as recordings with committed clip rows.
            for path in root.iterdir():
                try:
                    if path.is_file() and time.time() - path.stat().st_mtime > 86400:
                        path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove expired recording %s", path.name)

    async def close(self) -> None:
        try:
            if self.providers:
                await self.providers.close()
        finally:
            if self.owns_pool:
                self.pool.shutdown(wait=True)
