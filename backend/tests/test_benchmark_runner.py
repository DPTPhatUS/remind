import json
import sqlite3

import pytest

from remind.benchmark import runner
from remind.benchmark.backend import snapshot
from remind.config import Settings
from remind.database import Database


def text_manifest(tmp_path):
    path = tmp_path / "input.json"
    path.write_text(
        json.dumps(
            {
                "title": "Text",
                "annotation_notes": "Fixture",
                "cases": [
                    {
                        "id": "case",
                        "encounters": [
                            {
                                "id": "meeting",
                                "started_at": "2026-10-27T00:00:00+00:00",
                                "batches": [
                                    {
                                        "id": "first",
                                        "start_ms": 0,
                                        "end_ms": 1000,
                                        "turns": [
                                            {
                                                "id": "t",
                                                "start_ms": 0,
                                                "end_ms": 1000,
                                                "role": "visitor",
                                                "text": "Hello",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    )
    return path


@pytest.mark.parametrize("cloud,key", [(False, "present"), (True, "")])
def test_cloud_guard_precedes_output_or_provider_calls(tmp_path, cloud, key):
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="cloud|API_KEY"):
        runner.run(
            "conversation",
            text_manifest(tmp_path),
            output,
            cloud,
            Settings(data_dir=tmp_path / "active", openai_api_key=key),
        )
    assert not output.exists()


def test_existing_output_is_never_overwritten(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "keep.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        runner.run(
            "conversation",
            text_manifest(tmp_path),
            output,
            True,
            Settings(data_dir=tmp_path / "active", openai_api_key="fixture"),
        )
    assert (output / "keep.txt").read_text() == "keep"


def test_runner_has_no_minimum_pilot_size_or_source_archive(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "active", openai_api_key="secret-fixture")
    settings.data_dir.mkdir()
    active = settings.data_dir / "remind.sqlite3"
    active.write_bytes(b"active memories")

    async def run_case(case, output, settings):
        return {"id": case.id, "status": "complete", "outcomes": [], "errors": []}

    monkeypatch.setattr(runner.conversation, "run_case", run_case)
    output = tmp_path / "report"
    result = runner.run("conversation", text_manifest(tmp_path), output, True, settings)
    assert result["status"] == "complete"
    assert len(result["cases"]) == 1
    assert not (output / "source").exists()
    assert "secret-fixture" not in (output / "report.json").read_text()
    assert active.read_bytes() == b"active memories"
    assert result["model_files"] == {}


async def test_snapshots_omit_face_and_voice_representations(tmp_path):
    path = tmp_path / "memory.sqlite3"
    database = Database(path)
    await database.create_schema()
    await database.close()
    value = snapshot(path)
    assert set(value) == {"jobs", "transcripts", "job_metrics"}
    with pytest.raises(sqlite3.OperationalError):
        snapshot(tmp_path / "missing.sqlite3")
    assert not (tmp_path / "missing.sqlite3").exists()


def test_readable_video_report_explains_unmeasured_processing(tmp_path):
    from remind.benchmark.report import write_report

    result = {
        "kind": "video",
        "title": "Recording",
        "status": "complete",
        "annotation_notes": "Provisional labels",
        "limitations": [],
        "cases": [
            {
                "id": "case",
                "status": "complete",
                "errors": [],
                "outcomes": [
                    {
                        "id": "meeting",
                        "scores": {},
                        "unassociated_clips": 1,
                        "transport": {
                            "frames_sent": 10,
                            "frames_skipped_late": 0,
                            "uploads": [{"receipt": {"status": "no_participants"}}],
                        },
                    }
                ],
            }
        ],
    }
    write_report(result, tmp_path)
    summary = (tmp_path / "report.md").read_text()
    assert "Queued audio jobs | 0" in summary
    assert "extraction correctness were not measured" in summary
    assert "Execution status describes completion, not model accuracy" in summary
