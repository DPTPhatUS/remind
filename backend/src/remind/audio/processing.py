"""Decode, transcribe, and classify speech without face-association policy."""

import asyncio
import math
import time
from concurrent.futures import Executor
from pathlib import Path

from remind.audio.media import decode_audio, has_speech
from remind.audio.providers import Providers
from remind.audio.speaker import UserVoiceVerifier
from remind.database import Record
from remind.memory.contracts import AudioResult, Metrics, RawTranscriptTurn, TranscriptTurn


def transcript_segments(
    raw: list[RawTranscriptTurn], job_id: str, duration_ms: float
) -> list[TranscriptTurn]:
    segments: list[TranscriptTurn] = []
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


async def process_audio(
    path: str | Path,
    source_id: str,
    providers: Providers,
    verifier: UserVoiceVerifier,
    profile: Record | None,
    pool: Executor | None = None,
) -> AudioResult:
    loop = asyncio.get_running_loop()
    started = time.perf_counter()
    media = await loop.run_in_executor(pool, decode_audio, path)
    metrics: Metrics = {"decode_ms": round((time.perf_counter() - started) * 1000, 2)}
    voice_ready = profile is not None and media["continuous"]
    status = "User voice setup required or capture reference changed"
    if not has_speech(media["pcm"]):
        return {
            "segments": [],
            "metrics": metrics,
            "has_speech": False,
            "voice_ready": voice_ready,
            "status": status,
        }
    phase = time.perf_counter()
    raw = await providers.transcribe(media["pcm"])
    metrics["transcription_ms"] = round((time.perf_counter() - phase) * 1000, 2)
    segments = transcript_segments(raw, source_id, len(media["pcm"]) / 16)
    phase = time.perf_counter()
    if voice_ready:
        try:
            segments = await loop.run_in_executor(
                pool, verifier.classify, media["pcm"], segments, profile
            )
            status = "User voice verification available; uncalibrated"
        except (ImportError, FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
            status = f"User voice unavailable: {str(exc)[:120]}"
            segments = [{**s, "role": "uncertain"} for s in segments]
    metrics["voice_ms"] = round((time.perf_counter() - phase) * 1000, 2)
    return {
        "segments": segments,
        "metrics": metrics,
        "has_speech": True,
        "voice_ready": voice_ready,
        "status": status,
    }
