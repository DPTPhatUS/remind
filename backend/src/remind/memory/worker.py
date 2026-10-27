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
from remind.memory.learning import learn_conversation
from remind.memory.store import MemoryStore
from remind.vision.models import ModelRegistry

logger = logging.getLogger(__name__)


def visitor_supported(
    segment: Record,
    timeline: list[Record],
    clip_start_ms: float,
    visitor_id: str | None,
) -> bool:
    """Require a fresh, eligible capture-time visitor throughout a speech turn."""
    if not visitor_id:
        return False
    start = clip_start_ms + segment["start_ms"]
    end = clip_start_ms + segment["end_ms"]
    points = sorted(timeline, key=lambda entry: entry["ms"])
    before = [i for i, entry in enumerate(points) if entry["ms"] <= start]
    if not before or end <= start:
        return False
    index = before[-1]
    cursor = start
    while cursor < end:
        entry = points[index]
        if (
            not entry.get("eligible")
            or entry.get("visitor_id") != visitor_id
            or cursor - entry["ms"] > 500
        ):
            return False
        next_ms = points[index + 1]["ms"] if index + 1 < len(points) else end
        covered_until = min(end, next_ms)
        if covered_until - entry["ms"] > 500:
            return False
        cursor = covered_until
        if cursor < end:
            index += 1
    return True


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
        self.providers = Providers(settings) if settings.openai_api_key else None
        self.verifier = verifier or UserVoiceVerifier(settings, registry)
        self.speaker_status = "User voice setup required"
        self.pool = pool or ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory")
        self.owns_pool = pool is None

    async def run_once(self) -> bool:
        if self.providers is None:
            self.speaker_status = "Conversation processing needs API key"
            return False
        job = await self.store.claim_job("memory", int(time.time() * 1000))
        if job is None:
            return False
        renewal = asyncio.create_task(self._renew_lease(job))
        try:
            result = await self._process_job(job, self.providers)
            await self.store.finish_job(job["id"], job["lease_token"], result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.store.fail_job(
                job["id"],
                job["lease_token"],
                type(exc).__name__ + ": " + str(exc)[:160],
                int(time.time() * 1000),
            )
        finally:
            renewal.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renewal
        return True

    async def _renew_lease(self, job: Record) -> None:
        while True:
            await asyncio.sleep(30)
            if not await self.store.renew_lease(
                job["id"], job["lease_token"], int(time.time() * 1000)
            ):
                return

    async def _process_job(self, job: Record, providers: Providers) -> Record:
        started = time.perf_counter()
        payload = job["payload"]
        profile = await self.store.voice_profile()
        if profile is not None and profile["version"] != payload.get("voice_version"):
            profile = None
        audio = await process_audio(
            payload["clip_path"], job["id"], providers, self.verifier, profile, self.pool
        )
        metrics = audio["metrics"]
        if not audio["has_speech"]:
            metrics["processing_ms"] = round((time.perf_counter() - started) * 1000, 2)
            return {"facts": [], "segments": [], "metrics": metrics}
        self.speaker_status = audio["status"]
        segments = audio["segments"]
        for segment in segments:
            if not visitor_supported(
                segment, payload["timeline"], payload["start_ms"], payload.get("visitor_id")
            ):
                segment["role"] = "uncertain"
            segment["start_ms"] += payload["start_ms"]
            segment["end_ms"] += payload["start_ms"]
        result = await learn_conversation(
            self.store,
            providers,
            self.settings,
            payload["encounter"],
            payload.get("visitor_id"),
            segments,
            payload["start_ms"],
            can_learn=audio["voice_ready"],
        )
        metrics.update(result["metrics"])
        metrics["processing_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return {**result, "metrics": metrics}

    async def cleanup(self) -> None:
        root = (self.settings.data_dir / "spool").resolve()
        for pending in await self.store.pending_cleanup():
            path = Path(pending).resolve()
            if path.is_relative_to(root):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove forgotten recording %s", path.name)
                    continue
            await self.store.complete_cleanup(pending)
        if not root.exists():
            return
        for path in root.iterdir():
            try:
                if (
                    path.is_file()
                    and time.time() - path.stat().st_mtime > self.settings.media_retention_seconds
                ):
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
