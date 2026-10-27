"""Opt-in recorded-audio evaluation using the production conversation worker."""

import argparse
import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from remind.audio.media import SAMPLE_RATE, decode_audio
from remind.audio.providers import Providers
from remind.audio.speaker import MODEL, UserVoiceVerifier
from remind.benchmark.conversation_metrics import score_facts, score_roles, word_error_rate
from remind.benchmark.report import write_json
from remind.config import Settings
from remind.database import Database, rows
from remind.memory.store import MemoryStore
from remind.memory.worker import MemoryWorker
from remind.vision.models import ModelRegistry


class AudioFile(BaseModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class LabelledTurn(BaseModel):
    start_ms: float = Field(ge=0, allow_inf_nan=False)
    end_ms: float = Field(gt=0, allow_inf_nan=False)
    role: Literal["user", "visitor", "uncertain"]
    text: str
    expected_abstention: bool = False

    @model_validator(mode="after")
    def check_interval(self) -> "LabelledTurn":
        if self.end_ms <= self.start_ms or self.end_ms > 8100:
            raise ValueError("Turn must fit inside its eight-second clip")
        return self


class AudioClip(AudioFile):
    turns: list[LabelledTurn]


class ExpectedFact(BaseModel):
    subject: str
    predicate: str
    value: str
    temporal_status: Literal["current", "past", "planned"] = "current"
    present: bool = True


class AudioScenario(BaseModel):
    id: str = Field(min_length=1)
    clips: list[AudioClip] = Field(min_length=1)
    expected_facts: list[ExpectedFact]
    limitations: list[str] = Field(default_factory=list)
    note: str = ""


class AudioManifest(BaseModel):
    source_kind: Literal["synthetic", "human_recording"]
    source_description: str
    enrollment: list[AudioFile] = Field(min_length=3, max_length=5)
    scenarios: list[AudioScenario] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)


class TracedProviders(Providers):
    """Record real model proposals and assessments for error investigation."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.calls: list[dict[str, Any]] = []

    async def extract(self, *args, **kwargs) -> dict[str, Any]:
        result = await super().extract(*args, **kwargs)
        self.calls.append({"stage": "extraction", "result": result})
        return result

    async def verify(self, *args, **kwargs) -> dict[str, Any]:
        result = await super().verify(*args, **kwargs)
        self.calls.append({"stage": "verification", "result": result})
        return result


def verified_path(root: Path, recording: AudioFile) -> Path:
    path = (root / recording.path).resolve()
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != recording.sha256:
        raise ValueError(f"Audio checksum mismatch: {recording.path}")
    return path


def capture_payload(
    person: dict[str, Any], encounter: str, voice_version: int, clip: Path, start_ms: int
) -> dict[str, Any]:
    # Face association alone is supplied by the fixture. Speech roles and facts
    # must still be produced by the real models and production worker.
    return {
        "encounter": encounter,
        "visitor_id": person["id"],
        "versions": {person["id"]: person["version"]},
        "voice_version": voice_version,
        "clip_path": str(clip),
        "start_ms": start_ms,
        "end_ms": start_ms + 8000,
        "timeline": [
            {"ms": stamp, "visitor_id": person["id"], "eligible": True, "face_count": 1}
            for stamp in range(start_ms, start_ms + 8001, 100)
        ],
    }


async def run_scenario(
    scenario: AudioScenario,
    root: Path,
    settings: Settings,
    registry: ModelRegistry,
    verifier: UserVoiceVerifier,
    reference: dict[str, Any],
    max_attempts: int = 3,
) -> dict[str, Any]:
    # A temporary store prevents evaluation from modifying the person's real
    # memories and keeps scenarios independent from one another.
    with TemporaryDirectory(prefix="remind-audio-") as temporary:
        database_path = Path(temporary) / "evaluation.sqlite3"
        database = Database(database_path)
        worker = MemoryWorker(MemoryStore(database), settings, registry, verifier=verifier)
        if worker.providers is not None:
            await worker.providers.close()
        traced = TracedProviders(settings)
        worker.providers = traced
        store = worker.store
        jobs: list[dict[str, Any]] = []
        expected_turns: list[dict[str, Any]] = []
        try:
            await database.create_schema()
            await store.set_voice_profile(reference["embeddings"], reference["model"])
            voice = await store.voice_status()
            person = await store.create_person()
            encounter = await store.start_encounter("audio-evaluation")
            await store.add_participant(encounter, person["id"], "fixture-visitor", 0)
            for index, clip in enumerate(scenario.clips):
                start_ms = index * 8000
                expected_turns.extend(
                    {
                        **turn.model_dump(),
                        "start_ms": start_ms + turn.start_ms,
                        "end_ms": start_ms + turn.end_ms,
                    }
                    for turn in clip.turns
                )
                path = verified_path(root, clip)
                decoded = decode_audio(path, max_seconds=8.1)
                duration_ms = len(decoded["pcm"]) * 1000 / SAMPLE_RATE
                if not decoded["continuous"] or not 7900 <= duration_ms <= 8100:
                    raise ValueError(f"Expected continuous eight-second clip: {clip.path}")
                if any(turn.end_ms > duration_ms for turn in clip.turns):
                    raise ValueError(f"Turn extends past audio: {clip.path}")
                payload = capture_payload(person, encounter, voice["version"], path, start_ms)
                job_id = await store.enqueue_job(encounter, f"clip-{index}", payload)
                started = time.perf_counter()
                attempts = []
                for _ in range(max_attempts):
                    attempt_started = time.perf_counter()
                    await worker.run_once()
                    async with database.transaction() as connection:
                        job = (
                            await rows(
                                connection,
                                "SELECT status,error,attempts,next_at FROM jobs WHERE id=?",
                                (job_id,),
                            )
                        )[0]
                    attempts.append(
                        {
                            "status": job["status"],
                            "error": job["error"],
                            "processing_ms": (time.perf_counter() - attempt_started) * 1000,
                        }
                    )
                    if job["status"] != "pending" or len(attempts) >= max_attempts:
                        break
                    await asyncio.sleep(max(0, job["next_at"] / 1000 - time.time()))
                elapsed = (time.perf_counter() - started) * 1000
                jobs.append(
                    {
                        "clip": clip.path,
                        **job,
                        "attempt_results": attempts,
                        "attempt_ms": sum(attempt["processing_ms"] for attempt in attempts),
                        "clip_complete_to_commit_ms": elapsed if job["status"] == "done" else None,
                    }
                )
                if job["status"] != "done":
                    # Keep subsequent labels in coverage denominators even if a
                    # failed earlier clip prevents further processing.
                    for later_index, later_clip in enumerate(
                        scenario.clips[index + 1 :], index + 1
                    ):
                        expected_turns.extend(
                            {
                                **turn.model_dump(),
                                "start_ms": later_index * 8000 + turn.start_ms,
                                "end_ms": later_index * 8000 + turn.end_ms,
                            }
                            for turn in later_clip.turns
                        )
                    break
            await store.close_encounter(encounter)
            profile = await store.person_memory(person["id"])
            assert profile is not None
            async with database.transaction() as connection:
                transcript_rows = await rows(
                    connection,
                    "SELECT data FROM transcripts WHERE encounter_id=? ORDER BY start_ms,rowid",
                    (encounter,),
                )
            segments = [json.loads(row["data"]) for row in transcript_rows]
            metrics = await store.processing_metrics()
        finally:
            try:
                await worker.close()
            finally:
                await database.close()

        reopened = Database(database_path)
        try:
            await reopened.create_schema()
            recalled = await MemoryStore(reopened).person_memory(person["id"])
        finally:
            await reopened.close()
        reference_text = " ".join(turn["text"] for turn in expected_turns)
        actual_text = " ".join(segment["text"] for segment in segments)
        return {
            "id": scenario.id,
            "limitations": scenario.limitations,
            "note": scenario.note,
            "processing_complete": len(jobs) == len(scenario.clips)
            and all(job["status"] == "done" for job in jobs),
            "restart_recall_matches": recalled == profile,
            "facts": score_facts(
                [fact.model_dump() for fact in scenario.expected_facts], profile["facts"]
            ),
            "roles": score_roles(expected_turns, segments),
            "transcription": word_error_rate(reference_text, actual_text),
            "jobs": jobs,
            "stage_metrics": metrics,
            "model_calls": traced.calls,
            "transcript": segments,
            "expected_turns": expected_turns,
            "saved_profile": profile,
        }


async def evaluate_conversations(manifest_path: Path, settings: Settings) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise ValueError("Configure REMIND_OPENAI_API_KEY for real audio evaluation")
    manifest_bytes = manifest_path.read_bytes()
    manifest = AudioManifest.model_validate_json(manifest_bytes)
    package = Path(__file__).resolve().parents[1]
    code_hashes = {
        name: hashlib.sha256((package / name).read_bytes()).hexdigest()
        for name in (
            "audio/media.py",
            "audio/speaker.py",
            "audio/providers.py",
            "memory/extraction.py",
            "memory/worker.py",
            "memory/facts.py",
            "memory/store.py",
        )
    }
    root = manifest_path.resolve().parent
    # Check every input before making any paid transcription/extraction calls.
    for recording in manifest.enrollment:
        verified_path(root, recording)
    for scenario in manifest.scenarios:
        for clip in scenario.clips:
            verified_path(root, clip)
    registry = ModelRegistry(settings.data_dir / "models")
    verifier = UserVoiceVerifier(settings, registry)
    started = time.perf_counter()
    samples = [
        decode_audio(verified_path(root, sample), max_seconds=20) for sample in manifest.enrollment
    ]
    if any(not sample["continuous"] for sample in samples):
        raise ValueError("Enrollment audio is interrupted")
    reference = verifier.enroll([sample["pcm"] for sample in samples])
    enrollment_ms = (time.perf_counter() - started) * 1000
    scenarios = []
    for scenario in manifest.scenarios:
        result = await run_scenario(scenario, root, settings, registry, verifier, reference)
        scenarios.append(result)
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest_labels": manifest.model_dump(),
        "code_sha256": code_hashes,
        "source_kind": manifest.source_kind,
        "source_description": manifest.source_description,
        "models": {
            "voice": MODEL,
            "transcription": settings.openai_transcribe_model,
            "extraction_and_verification": settings.openai_text_model,
        },
        "voice_thresholds": {
            "user": settings.voice_user_threshold,
            "visitor": settings.voice_visitor_threshold,
        },
        "enrollment_ms": enrollment_ms,
        "scenarios": scenarios,
        "limitations": [
            *manifest.limitations,
            "Face identity and capture-time presence are fixture inputs; vision is not evaluated.",
            "File replay excludes microphone capture, browser recording, and upload latency.",
            "Labels and expected facts are not supplied to transcription or extraction models.",
            "Exact fact matching requires manual review of unmatched equivalent paraphrases.",
            "Synthetic audio results do not establish accuracy on natural human conversations.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cloud", action="store_true", help="Send audio/text to configured providers"
    )
    args = parser.parse_args()
    if not args.cloud:
        parser.error("Pass --cloud to explicitly enable paid transcription and extraction requests")
    report = asyncio.run(evaluate_conversations(args.manifest, Settings()))
    write_json(report, args.output)
    for scenario in report["scenarios"]:
        print(
            json.dumps(
                {
                    "id": scenario["id"],
                    "processing_complete": scenario["processing_complete"],
                    "restart_recall_matches": scenario["restart_recall_matches"],
                    "fact_precision": scenario["facts"]["fact_precision"],
                    "fact_coverage": scenario["facts"]["fact_coverage"],
                    "role_accuracy": scenario["roles"]["role_accuracy"],
                    "transcription": scenario["transcription"],
                }
            )
        )
    print(f"Full report: {args.output}")
    if not all(scenario["processing_complete"] for scenario in report["scenarios"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
