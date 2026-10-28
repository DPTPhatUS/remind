"""Conversation audio through real diarization and local user-voice assignment."""

import asyncio
import time
from pathlib import Path

from remind.audio.media import decode_audio
from remind.audio.processing import process_audio
from remind.audio.providers import Providers
from remind.audio.speaker import UserVoiceVerifier
from remind.benchmark.inputs import AudioCase
from remind.benchmark.media import prepare_enrollment, prepare_media
from remind.benchmark.report import CaseResult, write_json
from remind.benchmark.scoring import score_transcript
from remind.config import Settings
from remind.vision.models import ModelRegistry


async def run_case(case: AudioCase, output: Path, settings: Settings) -> CaseResult:
    prepared = [
        prepare_media(recording, output / f"recording-{index + 1}", require_video=False)
        for index, recording in enumerate(case.recordings)
    ]
    paths = [output / f"enrollment-{i + 1}.wav" for i in range(len(case.enrollment))]
    timings = [
        prepare_enrollment(sample, path)
        for sample, path in zip(case.enrollment, paths, strict=True)
    ]
    verifier = UserVoiceVerifier(settings, ModelRegistry(settings.data_dir / "models"))
    result: CaseResult = {
        "id": case.id,
        "status": "complete",
        "outcomes": [],
        "errors": [],
        "enrollment": {"supplied": len(paths), "ready": False, "media": timings},
    }
    profile = None
    if paths:
        started = time.perf_counter()
        try:
            samples = [decode_audio(path, max_seconds=20)["pcm"] for path in paths]
            profile = await asyncio.to_thread(verifier.enroll, samples)
            result["enrollment"]["ready"] = True
        except (ValueError, RuntimeError, ImportError, OSError) as exc:
            result["errors"].append(f"Enrollment rejected: {exc}")
            result["status"] = "failed"
        result["enrollment"]["processing_ms"] = (time.perf_counter() - started) * 1000
    providers = Providers(settings)
    try:
        for recording_index, (recording, media) in enumerate(
            zip(case.recordings, prepared, strict=True)
        ):
            segments = []
            clips = []
            for index, clip in enumerate(media["clips"]):
                started = time.perf_counter()
                try:
                    actual = await process_audio(
                        clip["path"], f"{recording.id}:{index}", providers, verifier, profile
                    )
                    for turn in actual["segments"]:
                        turn["start_ms"] += clip["start_ms"]
                        turn["end_ms"] += clip["start_ms"]
                    segments.extend(actual["segments"])
                    clips.append(
                        {
                            "start_ms": clip["start_ms"],
                            "end_ms": clip["end_ms"],
                            **actual,
                            "processing_ms": (time.perf_counter() - started) * 1000,
                        }
                    )
                except Exception as exc:
                    clips.append(
                        {"start_ms": clip["start_ms"], "end_ms": clip["end_ms"], "error": str(exc)}
                    )
                    result["errors"].append(f"{recording.id} clip {index}: {exc}")
                    result["status"] = "failed"
            expected = [turn.model_dump() for turn in recording.turns]
            outcome = {
                "id": recording.id,
                "segments": segments,
                "clips": clips,
                "media": media["metadata"],
                "scores": score_transcript(expected, segments),
            }
            result["outcomes"].append(outcome)
            write_json(outcome, output / f"recording-{recording_index + 1}" / "observed.json")
    finally:
        await providers.close()
    return result
