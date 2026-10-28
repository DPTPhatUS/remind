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
    assert set(value) == {"clips", "jobs", "transcripts", "job_metrics"}
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
                        "unattributed_turns": 0,
                        "transport": {
                            "frames_sent": 10,
                            "frames_skipped_late": 0,
                            "uploads": [{"error": "HTTP 503"}],
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


def test_video_report_distinguishes_skipped_failed_and_unfinished_work(tmp_path):
    from remind.benchmark.report import write_report

    upload = {"receipt": {"clip_id": "late", "status": "skipped"}}
    outcome = {
        "id": "encounter", "scores": {},
        "transport": {"uploads": [upload, upload]},
        "processing_jobs": [
            {"status": "skipped"}, {"status": "failed"}, {"status": "pending"},
        ],
    }
    write_report({
        "kind": "video", "title": "Failures", "status": "failed",
        "annotation_notes": "Fixture", "limitations": [],
        "cases": [{"id": "case", "status": "failed", "errors": [], "outcomes": [outcome]}],
    }, tmp_path)
    summary = (tmp_path / "report.md").read_text()
    assert "Queued audio jobs | 0" in summary
    assert "Skipped recordings | 1" in summary
    assert "Failed processing jobs | 1" in summary
    assert "Unfinished processing jobs | 1" in summary
    assert "extraction correctness were not measured" in summary
    assert json.loads((tmp_path / "report.json").read_text())["cases"][0]["outcomes"][0] == outcome


@pytest.mark.parametrize("kind", ["audio", "conversation", "face", "video"])
def test_report_artifacts_preserve_each_paths_measurements(tmp_path, kind):
    from remind.benchmark.report import write_report

    def ratio(numerator, denominator):
        return {
            "numerator": numerator,
            "denominator": denominator,
            "rate": numerator / denominator if denominator else None,
        }

    scores = {}
    rows = []
    if kind in {"audio", "video"}:
        scores["roles"] = {
            "role_accuracy": ratio(2, 4),
            "decision_coverage": ratio(3, 4),
            "wrong_role_ms": 1,
            "uncertain_ms": 0.5,
            "missed_ms": 0.5,
        }
        rows += [
            "| Role correctness (labelled duration) | 2.0/4.0 (50.0%) |",
            "| Decisive role coverage | 3.0/4.0 (75.0%) |",
            "| Confident role errors | 1.0 ms |",
            "| Uncertain speech | 0.5 ms |",
            "| Missed speech | 0.5 ms |",
        ]
    if kind in {"face", "video"}:
        scores["identity"] = {
            "face_count_accuracy": ratio(3, 4),
            "frame_accuracy": ratio(2, 4),
            "missed_associations": 1,
        }
        rows += [
            "| Face count | 3.0/4.0 (75.0%) |",
            "| Face association | 2.0/4.0 (50.0%) |",
            "| Missed face associations | 1 |",
        ]
    if kind in {"conversation", "video"}:
        scores["memory"] = {
            "fact_coverage": ratio(1, 2),
            "raw_exact_precision": ratio(1, 3),
            "required_absence": ratio(1, 1),
            "historical_state_coverage": ratio(0, 0),
            "wrong_subject_additions": [{"id": "wrong-subject"}],
            "unmatched_additions_require_review": [{"id": "review"}],
            "missing_expected": [
                {"subject": "visitor", "predicate": "occupation", "value": "teacher"}
            ],
        }
        rows += [
            "| Useful fact coverage | 1.0/2.0 (50.0%) |",
            "| Raw exact matching | 1.0/3.0 (33.3%) |",
            "| Required absence checks | 1.0/1.0 (100.0%) |",
            "| Historical state coverage | Not measured |",
            "| Wrong subjects | 1 |",
            "| Unmatched additions needing review | 1 |",
        ]
    outcome = {"id": "meeting", "scores": scores}
    if kind == "video":
        scores["latency"] = {"speech_to_saved": {"count": 1, "p50_ms": 1200, "p95_ms": 1200}}
        outcome.update(
            segments=[{"id": "saved"}, {"id": "unattributed"}],
            unattributed_turns=1,
            association={"direct_confirmation": 1, "multiple_faces": 1},
        )
        rows.append("| Speech to saved fact (1 measurements) | p50 1200.0 ms; p95 1200.0 ms |")
    if kind in {"face", "video"}:
        outcome["transport"] = {
            "frames_sent": 10,
            "frames_skipped_late": 1,
            "uploads": [{"receipt": {"clip_id": "clip", "status": "transcribing"}}]
            if kind == "video" else [],
        }
        rows += ["| Frames sent | 10 |", "| Frames skipped late | 1 |"]
    if kind == "video":
        rows += [
            "| Queued audio jobs | 1 |",
            "| Unattributed turns | 1 |",
            "| Transcribed turns | 2 |",
            "| Association: direct_confirmation | 1 |",
            "| Association: multiple_faces | 1 |",
        ]
    if kind in {"conversation", "video"}:
        rows += ["", "- Missed expected fact: visitor / occupation / teacher"]
    result = {
        "kind": kind,
        "title": "Frozen fixture",
        "status": "complete",
        "annotation_notes": "Reviewed fixture labels",
        "limitations": ["Fixture execution does not establish model accuracy."],
        "cases": [{"id": "case", "status": "complete", "errors": [], "outcomes": [outcome]}],
    }

    write_report(result, tmp_path)

    assert json.loads((tmp_path / "report.json").read_text()) == result
    expected = f"""# Remind {kind} benchmark

Execution: complete

Frozen fixture

Execution status describes completion, not model accuracy.

## case

Execution: complete


### meeting

| Measurement | Result |
| --- | --- |
"""
    expected += "\n".join(rows)
    expected += """

## Interpretation

Reviewed fixture labels

- Fixture execution does not establish model accuracy.
- Unmatched paraphrases require evidence review; exact wording is not a semantic judge.
- Empty output and small fixture runs cannot establish real-world accuracy.
- Full raw observations and per-stage timings are in report.json and case artifacts.
"""
    assert (tmp_path / "report.md").read_text() == expected
