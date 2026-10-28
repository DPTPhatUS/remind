from contextlib import contextmanager

import pytest

from remind.benchmark import visual
from remind.benchmark.inputs import FaceCase, VideoCase
from remind.config import Settings


def encounter(ident="first", visitor="visitor"):
    return {
        "id": ident,
        "path": "source.mp4",
        "sha256": "0" * 64,
        "source_id": "source",
        "source_start_ms": 0,
        "source_end_ms": 8000,
        "visitor_id": visitor,
        "visible": [{"start_ms": 0, "end_ms": 8000, "face_count": 1, "visitor_id": visitor}],
    }


def setup_backend(monkeypatch, *, profiles=None, pending=False, upload_failure=False):
    calls = []

    @contextmanager
    def backend(settings, output, *, cloud):
        calls.append(("backend", cloud, output))
        yield "http://backend", output / "data.sqlite3", {"vision": {"available": True}}

    monkeypatch.setattr(visual, "isolated_backend", backend)
    monkeypatch.setattr(visual, "inspect_video", lambda _: {"video_frames": 1})
    monkeypatch.setattr(
        visual,
        "prepare_media",
        lambda *a, **kw: {
            "metadata": {},
            "clips": [{"path": "clip.wav", "start_ms": 0, "end_ms": 8000}],
        },
    )
    monkeypatch.setattr(visual, "prepare_enrollment", lambda *a: {})
    monkeypatch.setattr(
        visual, "snapshot", lambda _: {"jobs": [], "transcripts": [], "job_metrics": []}
    )

    async def replay(url, path, clips, duration, output, *, include_audio):
        calls.append(("replay", include_audio, list(clips)))
        index = len([c for c in calls if c[0] == "replay"]) - 1
        person = profiles[index] if profiles else "profile"
        return {
            "faces": [
                {
                    "source_ms": 100,
                    "detections": [{}],
                    "candidate": {**{"person_id": person}, "confirmed": True},
                }
            ],
            "uploads": [{"error": "HTTP 503"}]
            if upload_failure
            else (
                [{"receipt": {"status": "transcribing", "clip_id": "clip"}}]
                if include_audio
                else []
            ),
            "people": [],
            "remaining_jobs": [{"id": "pending", "status": "running"}] if pending else [],
            "alignment_valid": True,
            "clock_samples": [
                {"source_ms": 0, "performance_ms": 0},
                {"source_ms": 8000, "performance_ms": 8000},
            ],
            "fact_observations": [],
            "prior_fact_ids": [],
        }

    monkeypatch.setattr(visual, "replay_encounter", replay)
    return calls


def test_face_path_uses_video_only_and_preserves_return_mapping(tmp_path, monkeypatch):
    calls = setup_backend(monkeypatch)
    case = FaceCase.model_validate({"id": "face", "encounters": [encounter(), encounter("return")]})
    result = visual.run_case(case, tmp_path, Settings(data_dir=tmp_path), include_audio=False)
    assert result["status"] == "complete"
    assert calls[0][1] is False
    assert all(not call[1] and call[2] == [] for call in calls if call[0] == "replay")
    assert result["outcomes"][1]["scores"]["identity"]["frame_accuracy"]["rate"] == 1
    assert "enrollment" not in result
    assert all("memory" not in o["scores"] for o in result["outcomes"])


def test_returning_face_cannot_silently_change_profile(tmp_path, monkeypatch):
    setup_backend(monkeypatch, profiles=["first-profile", "duplicate-profile"])
    case = FaceCase.model_validate({"id": "face", "encounters": [encounter(), encounter("return")]})
    result = visual.run_case(case, tmp_path, Settings(data_dir=tmp_path), include_audio=False)
    scores = result["outcomes"][1]["scores"]["identity"]
    assert scores["frame_accuracy"]["rate"] == 0
    assert scores["wrong_associations"] == 1


def test_video_with_no_face_still_counts_the_missed_fact(tmp_path, monkeypatch):
    setup_backend(monkeypatch, profiles=[None])
    value = encounter()
    value["facts"] = [
        {"id": "work", "subject": "visitor", "predicate": "occupation", "value": "teacher"}
    ]
    value["turns"] = [
        {"id": "speech", "start_ms": 100, "end_ms": 1000, "role": "visitor", "text": "I teach"}
    ]
    case = VideoCase.model_validate({"id": "video", "encounters": [value]})
    result = visual.run_case(case, tmp_path, Settings(data_dir=tmp_path), include_audio=True)
    outcome = result["outcomes"][0]
    assert outcome["scores"]["memory"]["fact_coverage"]["rate"] == 0
    assert outcome["scores"]["roles"]["missed_ms"] == 900
    assert outcome["scores"]["latency"]["speech_to_saved"]["count"] == 0
    assert outcome["unattributed_turns"] == 0
    assert outcome["segments"] == []


@pytest.mark.parametrize("failure", ["pending", "upload", "enrollment"])
def test_visual_failures_remain_explicit(tmp_path, monkeypatch, failure):
    setup_backend(monkeypatch, pending=failure == "pending", upload_failure=failure == "upload")
    value = {"id": "video", "encounters": [encounter()]}
    if failure == "enrollment":
        value["enrollment"] = [
            {
                **encounter(f"sample-{i}"),
                "source_start_ms": i * 8000,
                "source_end_ms": (i + 1) * 8000,
            }
            for i in range(3)
        ]
        for sample in value["enrollment"]:
            sample.pop("visitor_id")
            sample.pop("visible")
        monkeypatch.setattr(
            visual, "enroll_voice", lambda *a: {"status": 422, "response": {"ready": False}}
        )
    case = VideoCase.model_validate(value)
    result = visual.run_case(case, tmp_path, Settings(data_dir=tmp_path), include_audio=True)
    assert result["status"] == "failed"
    assert result["errors"]
    assert len(result["outcomes"]) == 1


@pytest.mark.parametrize("status", ["failed", "skipped", "pending"])
def test_video_reports_terminal_outcomes_separately_from_unfinished_work(
    tmp_path, monkeypatch, status
):
    setup_backend(monkeypatch)
    replay = visual.replay_encounter
    job = {"id": "job", "clip_id": "clip", "kind": "audio", "status": status}

    async def observed(*args, **kwargs):
        result = await replay(*args, **kwargs)
        result["remaining_jobs"] = [job]
        if status == "skipped":
            result["uploads"][0]["receipt"]["status"] = "skipped"
        return result

    monkeypatch.setattr(visual, "replay_encounter", observed)
    monkeypatch.setattr(visual, "snapshot", lambda _: {
        "jobs": [job], "transcripts": [], "job_metrics": [],
    })
    value = encounter()
    value["facts"] = [
        {"id": "work", "subject": "visitor", "predicate": "occupation", "value": "teacher"}
    ]
    result = visual.run_case(
        VideoCase.model_validate({"id": "video", "encounters": [value]}),
        tmp_path, Settings(data_dir=tmp_path), include_audio=True,
    )
    assert result["status"] == "failed"
    outcome = result["outcomes"][0]
    assert outcome["processing_jobs"] == [job]
    assert outcome["segments"] == []
    assert outcome["scores"]["memory"]["fact_coverage"] == {
        "numerator": 0, "denominator": 1, "rate": 0,
    }


def test_video_results_keep_roles_associations_evidence_and_stage_scope_separate(
    tmp_path, monkeypatch
):
    setup_backend(monkeypatch)
    replay = visual.replay_encounter
    fact = {
        "id": "name",
        "person_id": "profile",
        "subject": "visitor",
        "predicate": "name",
        "value": "Anna",
        "evidence": [{"segment_id": "current", "quote": "Anna"}],
    }
    other_fact = {
        "id": "other-name",
        "person_id": "other-profile",
        "subject": "visitor",
        "predicate": "name",
        "value": "Bob",
        "evidence": [],
    }

    async def observed(*args, **kwargs):
        result = await replay(*args, **kwargs)
        result["people"] = [{"facts": [fact]}, {"facts": [other_fact]}]
        result["fact_observations"] = [
            {"fact_id": "name", "performance_ms": 1500, "poll_interval_ms": 500}
        ]
        return result

    monkeypatch.setattr(visual, "replay_encounter", observed)
    monkeypatch.setattr(
        visual,
        "snapshot",
        lambda _: {
            "jobs": [{"id": "job", "clip_id": "clip", "kind": "learning", "status": "done"}],
            "transcripts": [
                {
                    "clip_id": "old-clip",
                    "data": {
                        "id": "earlier",
                        "role": "user",
                        "text": "Who are you?",
                        "start_ms": 0,
                        "end_ms": 100,
                    },
                },
                {
                    "clip_id": "clip",
                    "data": {
                        "id": "current",
                        "role": "visitor",
                        "text": "Anna",
                        "start_ms": 100,
                        "end_ms": 1000,
                        "association": {"status": "attributed", "reason": "absence_allowance"},
                    },
                },
                {
                    "clip_id": "clip",
                    "data": {
                        "id": "unattributed",
                        "role": "visitor",
                        "text": "Hello",
                        "start_ms": 1000,
                        "end_ms": 2000,
                        "association": {"status": "unattributed", "reason": "multiple_faces"},
                    },
                },
            ],
            "job_metrics": [
                {"job_id": "job", "data": {"decode_ms": 12, "attribution_wait_ms": 30}},
                {"job_id": "unrelated", "data": {"decode_ms": 999}},
            ],
        },
    )
    value = encounter()
    value["turns"] = [
        {"id": "said", "role": "visitor", "text": "Anna", "start_ms": 100, "end_ms": 1000}
    ]
    value["facts"] = [
        {"id": "expected-name", "subject": "visitor", "predicate": "name", "value": "Anna"}
    ]
    case = VideoCase.model_validate({"id": "video", "encounters": [value]})

    result = visual.run_case(case, tmp_path, Settings(data_dir=tmp_path), include_audio=True)

    outcome = result["outcomes"][0]
    assert result["status"] == "complete"
    assert outcome["facts"] == [fact]
    assert outcome["facts_on_other_or_unmapped_profiles"] == [other_fact]
    assert [s["id"] for s in outcome["segments"]] == ["current", "unattributed"]
    assert [s["role"] for s in outcome["segments"]] == ["visitor", "visitor"]
    assert outcome["association"] == {"absence_allowance": 1, "multiple_faces": 1}
    assert outcome["unattributed_turns"] == 1
    scores = outcome["scores"]
    assert scores["roles"]["role_accuracy"] == {"numerator": 900, "denominator": 900, "rate": 1}
    assert scores["transcription"] == {
        "errors": 1,
        "reference_words": 1,
        "hypothesis_words": 2,
        "rate": 1,
    }
    assert scores["memory"]["evidence"]["resolvable_quotes"]["rate"] == 1
    assert scores["latency"]["measurements"] == [
        {"fact_id": "name", "speech_end_ms": 1000, "latency_ms": 500, "poll_uncertainty_ms": 500}
    ]
    assert outcome["processing_stages_ms"]["decode_ms"] == {
        "count": 1,
        "p50_ms": 12,
        "p95_ms": 12,
        "p99_ms": 12,
        "max_ms": 12,
    }
    assert outcome["processing_stages_ms"]["attribution_wait_ms"]["p50_ms"] == 30
    assert outcome["processing_stages_ms"]["commit_ms"]["count"] == 0
