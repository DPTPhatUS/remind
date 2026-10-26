import asyncio
import contextlib
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from remind.audio.media import DecodedAudio, decode_audio, has_speech
from remind.audio.providers import Providers
from remind.audio.speaker import UserVoiceVerifier
from remind.config import Settings
from remind.database import Record
from remind.memory.extraction import validate_extraction
from remind.memory.store import MemoryStore
from remind.vision.models import ModelRegistry

logger = logging.getLogger(__name__)
MAX_DIALOGUE_CHARS = 24000


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


def bounded_dialogue(segments: list[Record]) -> list[Record]:
    """Keep the newest complete turns within the extraction input budget."""
    dialogue = []
    chars = 0
    for segment in reversed(segments):
        size = len(segment.get("text", ""))
        if chars + size > MAX_DIALOGUE_CHARS:
            break
        dialogue.append(segment)
        chars += size
    dialogue.reverse()
    return dialogue


def transcript_segments(raw: list[Record], job_id: str, duration_ms: float) -> list[Record]:
    segments = []
    for index, source in enumerate(raw):
        start, end = float(source["start_ms"]), float(source["end_ms"])
        if not (math.isfinite(start) and math.isfinite(end)):
            continue
        if start < 0 or start >= duration_ms or end <= start or end > duration_ms + 50:
            continue
        segments.append(
            {
                **source,
                "id": f"{job_id}:{index}:{source['id']}",
                "start_ms": start,
                "end_ms": min(end, duration_ms),
                "role": "uncertain",
            }
        )
    return segments


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

    async def _assign_roles(
        self,
        media: DecodedAudio,
        segments: list[Record],
        payload: Record,
    ) -> tuple[list[Record], bool]:
        profile = await self.store.voice_profile()
        voice_ready = (
            profile is not None
            and profile["version"] == payload.get("voice_version")
            and media["continuous"]
        )
        if voice_ready:
            try:
                segments = await asyncio.get_running_loop().run_in_executor(
                    self.pool, self.verifier.classify, media["pcm"], segments, profile
                )
                self.speaker_status = "User voice verification available; uncalibrated"
            except (ImportError, FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
                self.speaker_status = f"User voice unavailable: {str(exc)[:120]}"
                segments = [{**segment, "role": "uncertain"} for segment in segments]
        else:
            self.speaker_status = "User voice setup required or capture reference changed"
        for segment in segments:
            if not visitor_supported(
                segment, payload["timeline"], payload["start_ms"], payload.get("visitor_id")
            ):
                segment["role"] = "uncertain"
            segment["start_ms"] += payload["start_ms"]
            segment["end_ms"] += payload["start_ms"]
        return segments, voice_ready

    async def _process_job(self, job: Record, providers: Providers) -> Record:
        started = time.perf_counter()
        payload = job["payload"]
        phase = time.perf_counter()
        media = await asyncio.get_running_loop().run_in_executor(
            self.pool, decode_audio, payload["clip_path"]
        )
        metrics = {"decode_ms": round((time.perf_counter() - phase) * 1000, 2)}
        if not has_speech(media["pcm"]):
            metrics["processing_ms"] = round((time.perf_counter() - started) * 1000, 2)
            return {"facts": [], "segments": [], "metrics": metrics}

        phase = time.perf_counter()
        raw = await providers.transcribe(media["pcm"])
        metrics["transcription_ms"] = round((time.perf_counter() - phase) * 1000, 2)
        segments = transcript_segments(raw, job["id"], len(media["pcm"]) / 16)
        phase = time.perf_counter()
        segments, voice_ready = await self._assign_roles(media, segments, payload)
        metrics["voice_ms"] = round((time.perf_counter() - phase) * 1000, 2)

        encounter = await self.store.get_encounter(payload["encounter"]) or {}
        encounter_time = encounter.get("started_at") or ""
        if encounter_time:
            stamp = datetime.fromisoformat(encounter_time)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            encounter_time = stamp.astimezone(ZoneInfo(self.settings.memory_timezone)).isoformat()
        context = await self.store.recent_context(
            payload["encounter"], limit=40, before_ms=payload["start_ms"]
        )
        dialogue = bounded_dialogue(context + segments)
        current_ids = {segment["id"] for segment in segments}
        facts = (
            await self.store.facts_for_person(payload["visitor_id"])
            if payload.get("visitor_id")
            else []
        )[:120]
        # A delayed old clip must not use a later summary as its context.
        previous_summary = ""
        if encounter.get("summary_order", -1) <= payload["start_ms"]:
            previous_summary = encounter.get("summary") or ""

        phase = time.perf_counter()
        result = await providers.extract(
            dialogue,
            previous_summary,
            facts,
            encounter_time,
            current_ids,
        )
        metrics["extraction_ms"] = round((time.perf_counter() - phase) * 1000, 2)
        phase = time.perf_counter()
        verification: Record = {"assessments": []}
        if voice_ready and any(segment.get("role") == "visitor" for segment in segments):
            verification = await providers.verify(result.get("facts", []), dialogue, facts)
        validated = validate_extraction(
            result,
            dialogue,
            verification,
            facts,
            current_ids=current_ids,
        )
        metrics["verification_ms"] = round((time.perf_counter() - phase) * 1000, 2)
        metrics.update(
            {
                "proposed_facts": len(result.get("facts", [])),
                "verified_facts": len(validated["facts"]),
                "visitor_segments": sum(segment.get("role") == "visitor" for segment in segments),
                "uncertain_segments": sum(
                    segment.get("role") == "uncertain" for segment in segments
                ),
                "processing_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )
        return {**validated, "segments": segments, "metrics": metrics}

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
