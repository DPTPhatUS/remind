import asyncio
import contextlib
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from remind.audio.media import decode_audio
from remind.audio.providers import Providers
from remind.audio.speaker import UserVoiceVerifier
from remind.audio.windows import AudioWindowBuffer
from remind.memory.extraction import validate_extraction
from remind.memory.store import rows


def visitor_supported(segment, timeline, clip_start_ms, visitor_id):
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
    def __init__(self, store, settings, registry, verifier=None, pool=None):
        self.store, self.settings, self.registry = store, settings, registry
        self.providers = Providers(settings) if settings.openai_api_key else None
        self.verifier = verifier or UserVoiceVerifier(settings, registry)
        self.speaker_status = "User voice setup required"
        self.pool = pool or ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory")
        self.owns_pool = pool is None

    async def run_once(self):
        if self.providers is None:
            self.speaker_status = "Conversation processing needs API key"
            return False
        job = await self.store.claim_job("memory", int(time.time() * 1000))
        if not job:
            return False
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        metrics = {}

        async def renew():
            while True:
                await asyncio.sleep(30)
                if not await self.store.renew_lease(
                    job["id"], job["lease_token"], int(time.time() * 1000)
                ):
                    return

        renewal = asyncio.create_task(renew())
        try:
            payload = job["payload"]
            phase = time.perf_counter()
            media = await loop.run_in_executor(self.pool, decode_audio, payload["clip_path"])
            metrics["decode_ms"] = round((time.perf_counter() - phase) * 1000, 2)
            vad = AudioWindowBuffer()
            speech = vad.accept(media["pcm"].tobytes(), 0, 16000)
            if vad.flush():
                speech.append(True)
            if not speech:
                metrics["processing_ms"] = round((time.perf_counter() - started) * 1000, 2)
                await self.store.finish_job(
                    job["id"], job["lease_token"],
                    {"facts": [], "segments": [], "metrics": metrics},
                )
                return True
            phase = time.perf_counter()
            raw = await self.providers.transcribe(media["pcm"])
            metrics["transcription_ms"] = round((time.perf_counter() - phase) * 1000, 2)
            duration_ms = len(media["pcm"]) / 16
            segments = []
            for i, source in enumerate(raw):
                start, end = float(source["start_ms"]), float(source["end_ms"])
                if not (math.isfinite(start) and math.isfinite(end)):
                    continue
                if start < 0 or end <= start or end > duration_ms + 50:
                    continue
                segments.append({**source, "id": f"{job['id']}:{i}:{source['id']}",
                                 "start_ms": start, "end_ms": min(end, duration_ms),
                                 "role": "uncertain"})
            profile = await self.store.voice_profile()
            voice_ready = (
                profile is not None
                and profile["version"] == payload.get("voice_version")
                and media.get("continuous", False)
            )
            phase = time.perf_counter()
            if voice_ready:
                try:
                    segments = await loop.run_in_executor(
                        self.pool, self.verifier.classify, media["pcm"], segments, profile
                    )
                    self.speaker_status = "User voice verification available; uncalibrated"
                except (ImportError, FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
                    self.speaker_status = f"User voice unavailable: {str(exc)[:120]}"
                    segments = [{**s, "role": "uncertain"} for s in segments]
            else:
                self.speaker_status = "User voice setup required or capture reference changed"
            metrics["voice_ms"] = round((time.perf_counter() - phase) * 1000, 2)
            for segment in segments:
                if not visitor_supported(
                    segment, payload["timeline"], payload["start_ms"], payload.get("visitor_id")
                ):
                    segment["role"] = "uncertain"
                segment["start_ms"] += payload["start_ms"]
                segment["end_ms"] += payload["start_ms"]
            async with self.store.db.transaction() as db:
                encounters = await rows(
                    db, "SELECT summary,started_at,summary_order FROM encounters WHERE id=?",
                    (payload["encounter"],),
                )
            encounter = encounters[0] if encounters else {}
            encounter_time = encounter.get("started_at") or ""
            if encounter_time:
                stamp = datetime.fromisoformat(encounter_time)
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=UTC)
                local_zone = ZoneInfo(self.settings.memory_timezone)
                encounter_time = stamp.astimezone(local_zone).isoformat()
            context = await self.store.recent_context(
                payload["encounter"], limit=40, before_ms=payload["start_ms"]
            )
            # Bound input size even if a provider emits unusually large turns.
            dialogue = []
            chars = 0
            for segment in reversed(context + segments):
                size = len(segment.get("text", ""))
                if dialogue and chars + size > 24000:
                    break
                if size > 24000:
                    continue
                dialogue.append(segment)
                chars += size
            dialogue.reverse()
            current_ids = {s["id"] for s in segments}
            facts = (
                await self.store.facts_for_person(payload["visitor_id"])
                if payload.get("visitor_id") else []
            )
            # Include the most recent memories; references may target only this set.
            facts = facts[:120]
            previous_summary = (
                encounter.get("summary") or ""
                if encounter.get("summary_order", -1) <= payload["start_ms"] else ""
            )
            phase = time.perf_counter()
            result = await self.providers.extract(
                dialogue, previous_summary, facts,
                encounter_time, current_ids,
            )
            metrics["extraction_ms"] = round((time.perf_counter() - phase) * 1000, 2)
            phase = time.perf_counter()
            has_visitor = any(s.get("role") == "visitor" for s in segments)
            verification = (
                await self.providers.verify(result.get("facts", []), dialogue, facts)
                if has_visitor and voice_ready else {"assessments": []}
            )
            validated = validate_extraction(
                result, dialogue, verification, facts, current_ids=current_ids
            )
            metrics["verification_ms"] = round((time.perf_counter() - phase) * 1000, 2)
            metrics.update({
                "proposed_facts": len(result.get("facts", [])),
                "verified_facts": len(validated["facts"]),
                "visitor_segments": sum(s.get("role") == "visitor" for s in segments),
                "uncertain_segments": sum(s.get("role") == "uncertain" for s in segments),
                "processing_ms": round((time.perf_counter() - started) * 1000, 2),
            })
            validated.update(segments=segments, metrics=metrics)
            await self.store.finish_job(job["id"], job["lease_token"], validated)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.store.fail_job(
                job["id"], job["lease_token"],
                type(exc).__name__ + ": " + str(exc)[:160], int(time.time() * 1000),
            )
        finally:
            renewal.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renewal
        return True

    async def cleanup(self):
        root = (self.settings.data_dir / "spool").resolve()
        async with self.store.db.transaction() as db:
            pending = await rows(db, "SELECT path FROM cleanup")
            for entry in pending:
                path = Path(entry["path"]).resolve()
                if path.is_relative_to(root):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        continue
                await db.execute("DELETE FROM cleanup WHERE path=?", (entry["path"],))
        if root.exists():
            for path in root.iterdir():
                if (
                    path.is_file()
                    and time.time() - path.stat().st_mtime > self.settings.media_retention_seconds
                ):
                    path.unlink(missing_ok=True)

    async def close(self):
        if self.providers:
            await self.providers.close()
        if self.owns_pool:
            self.pool.shutdown(wait=True)
