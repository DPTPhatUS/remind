import asyncio
import contextlib
import logging
import time
from concurrent.futures import Executor
from pathlib import Path
from typing import cast

from remind.audio.processing import process_audio
from remind.audio.providers import Providers
from remind.audio.speaker import UserVoiceVerifier
from remind.config import Settings
from remind.memory.capture import CaptureStore, milliseconds
from remind.memory.contracts import ClaimedJob
from remind.memory.learning import learn_conversation
from remind.memory.store import MemoryStore

logger = logging.getLogger(__name__)


class MemoryWorker:
    """Run durable jobs with dependencies owned by the caller."""

    def __init__(
        self,
        store: MemoryStore,
        settings: Settings,
        captures: CaptureStore,
        *,
        providers: Providers | None,
        verifier: UserVoiceVerifier,
        pool: Executor,
    ) -> None:
        self.store = store
        self.settings = settings
        self.captures = captures
        self.jobs = captures.jobs
        self.providers = providers
        self.verifier = verifier
        self.speaker_status = "User voice setup required"
        self.pool = pool

    async def run_once(self) -> bool:
        if self.providers is None:
            self.speaker_status = "Conversation processing needs API key"
            return False
        job = await self.jobs.claim("memory")
        if job is None:
            return False
        renewal = asyncio.create_task(self._renew_lease(job))
        try:
            await self._process_job(job, self.providers)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.jobs.fail(
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

    async def _renew_lease(self, job: ClaimedJob) -> None:
        while True:
            await asyncio.sleep(30)
            if not await self.jobs.renew(job["id"], job["lease_token"], milliseconds()):
                return

    async def _process_job(self, job: ClaimedJob, providers: Providers) -> None:
        started = time.perf_counter()
        if job["kind"] == "audio":
            clip = job["clip"]
            profile = await self.store.voice_profile()
            if profile is not None and profile["version"] != clip["voice_version"]:
                profile = None
            audio = await process_audio(
                # Media jobs retain a path until expiration cancels their lease.
                # Trusted transcript audio jobs are finished by their caller.
                cast(str, clip["path"]),
                job["id"],
                providers,
                self.verifier,
                profile,
                self.pool,
            )
            self.speaker_status = audio["status"]
            audio["metrics"]["processing_ms"] = round((time.perf_counter() - started) * 1000, 2)
            await self.captures.finish_audio(job, audio)
            return
        segments = await self.captures.learning_segments(job)
        learning_clip = job["clip"]
        payload = job["payload"]
        result = await learn_conversation(
            self.store,
            providers,
            self.settings,
            job["encounter_id"],
            payload["visitor_id"],
            segments,
            payload["start_ms"],
            can_learn=bool(
                learning_clip["voice_ready"] or learning_clip["input_kind"] == "conversation"
            ),
        )
        result["metrics"]["processing_ms"] = round((time.perf_counter() - started) * 1000, 2)
        result["metrics"]["attribution_wait_ms"] = max(
            0, learning_clip["attribution_finalized_ms"] - learning_clip["audio_completed_ms"]
        )
        result["metrics"]["receipt_to_audio_ms"] = max(
            0, learning_clip["audio_completed_ms"] - learning_clip["received_ms"]
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
