"""One entry point for audio, conversation, face, and video benchmarks."""

import asyncio
import hashlib
import platform
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from remind.benchmark import audio, conversation, visual
from remind.benchmark.backend import ROOT
from remind.benchmark.inputs import (
    AudioCase,
    ConversationCase,
    FaceCase,
    Kind,
    VideoCase,
    load_manifest,
)
from remind.benchmark.report import BenchmarkReport, write_json, write_report
from remind.config import Settings
from remind.vision.models import ModelRegistry


def run(
    kind: Kind, manifest_path: Path, output: Path, cloud: bool, settings: Settings | None = None
) -> BenchmarkReport:
    manifest = load_manifest(kind, manifest_path)
    settings = settings or Settings()
    if kind != "face" and not cloud:
        raise ValueError("Pass --cloud to enable configured transcription or extraction providers")
    if kind != "face" and not settings.openai_api_key:
        raise ValueError("Configure REMIND_OPENAI_API_KEY before running cloud benchmarks")
    output = output.resolve()
    if output == settings.data_dir.resolve() or settings.data_dir.resolve().is_relative_to(output):
        raise ValueError(
            "Benchmark output must be separate from the application's active data directory"
        )
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(manifest_path, output / "manifest.json")
    write_json(manifest.model_dump(mode="json"), output / "resolved-manifest.json")
    result: BenchmarkReport = {
        "kind": kind,
        "title": manifest.title,
        "annotation_notes": manifest.annotation_notes,
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "cloud": kind != "face",
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "settings": settings.model_dump(mode="json", exclude={"openai_api_key"}),
        "hardware": platform.platform(),
        "python": platform.python_version(),
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "code_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "backend/src/remind").rglob("*.py"))
        },
        "model_files": ModelRegistry(settings.data_dir / "models").models
        if kind != "conversation"
        else {},
        "limitations": [*manifest.limitations],
        "cases": [],
    }
    if kind in {"face", "video"}:
        result["limitations"].append(
            "Direct backend replay excludes browser recording, UI rendering, "
            "and physical capture quality."
        )
    if kind == "audio":
        result["limitations"].append(
            "Role assignment is evaluated without capture-time face gating or fact extraction."
        )
    if kind == "conversation":
        result["limitations"].append(
            "Transcript text and roles are supplied inputs; "
            "audio and face accuracy are not measured."
        )
    write_report(result, output)
    for index, case in enumerate(manifest.cases):
        directory = output / f"case-{index + 1}"
        directory.mkdir()
        try:
            if kind == "audio":
                assert isinstance(case, AudioCase)
                outcome = asyncio.run(audio.run_case(case, directory, settings))
            elif kind == "conversation":
                assert isinstance(case, ConversationCase)
                outcome = asyncio.run(conversation.run_case(case, directory, settings))
            else:
                assert isinstance(case, (FaceCase, VideoCase))
                outcome = visual.run_case(case, directory, settings, include_audio=kind == "video")
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if settings.openai_api_key:
                message = message.replace(settings.openai_api_key, "[redacted]")
            outcome = {"id": case.id, "status": "failed", "errors": [message], "outcomes": []}
        write_json(outcome, directory / "result.json")
        result["cases"].append(outcome)
        write_report(result, output)
    result["status"] = (
        "complete" if all(c["status"] == "complete" for c in result["cases"]) else "failed"
    )
    result["finished_at"] = datetime.now(UTC).isoformat()
    write_report(result, output)
    return result
