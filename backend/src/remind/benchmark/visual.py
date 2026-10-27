"""Face-only and full video evaluation share the same real-time backend transport."""

import asyncio
from pathlib import Path

from remind.benchmark.backend import enroll_voice, isolated_backend, snapshot
from remind.benchmark.inputs import FaceCase, VideoCase, VideoEncounter
from remind.benchmark.media import AudioClip, inspect_video, prepare_enrollment, prepare_media
from remind.benchmark.report import write_json
from remind.benchmark.scoring import (
    percentiles,
    score_identity,
    score_latency,
    score_memory,
    score_roles,
    word_error_rate,
)
from remind.benchmark.transport import replay_encounter
from remind.config import Settings


def run_case(
    case: FaceCase | VideoCase, output: Path, settings: Settings, *, include_audio: bool
) -> dict:
    prepared: list[tuple[Path, list[AudioClip]]] = []
    for index, encounter in enumerate(case.encounters):
        directory = output / f"encounter-{index + 1}"
        directory.mkdir()
        clips: list[AudioClip] = []
        if include_audio:
            media = prepare_media(encounter, directory / "audio", require_video=True)
            clips = media["clips"]
            metadata: dict = dict(media["metadata"])
        else:
            metadata = inspect_video(encounter)
        write_json(metadata, directory / "media.json")
        prepared.append((directory, clips))
    samples = getattr(case, "enrollment", [])
    paths = [output / f"enrollment-{i + 1}.wav" for i in range(len(samples))]
    for sample, path in zip(samples, paths, strict=True):
        prepare_enrollment(sample, path)
    result: dict = {"id": case.id, "status": "complete", "outcomes": [], "errors": []}
    mapping: dict[str, str] = {}
    with isolated_backend(settings, output, cloud=include_audio) as (url, database_path, health):
        result["health"] = health
        if paths:
            enrollment = enroll_voice(url, paths)
            result["enrollment"] = enrollment
            if enrollment["status"] != 200 or not enrollment["response"].get("ready"):
                result["errors"].append(
                    "Voice enrollment rejected; subsequent clips run without a reference"
                )
                result["status"] = "failed"
        for encounter, (directory, clips) in zip(case.encounters, prepared, strict=True):
            actual = asyncio.run(
                replay_encounter(
                    url,
                    encounter.path,
                    clips,
                    encounter.duration_ms,
                    directory,
                    include_audio=include_audio,
                )
            )
            database = snapshot(database_path)
            write_json(database, directory / "database.json")
            identity = score_identity(
                [v.model_dump() for v in encounter.visible],
                actual["faces"],
                mapping,
                aligned=actual["alignment_valid"],
            )
            mapping.update(identity["identity_map"])
            scores: dict = {"identity": identity}
            outcome: dict = {"id": encounter.id, "scores": scores, "transport": actual}
            if include_audio:
                assert isinstance(encounter, VideoEncounter)
                job_ids = {u.get("receipt", {}).get("job_id") for u in actual["uploads"]}
                segments = [
                    {**row["data"], "current_encounter": row["job_id"] in job_ids}
                    for row in database["transcripts"]
                ]
                current = [s for s in segments if s["current_encounter"]]
                pid = mapping.get(encounter.visitor_id)
                all_facts = [f for person in actual["people"] for f in person["facts"]]
                facts = [f for f in all_facts if pid and f["person_id"] == pid]
                expected = (
                    [t.model_dump() for t in encounter.turns] if actual["alignment_valid"] else []
                )
                scores.update(
                    {
                        "roles": score_roles(
                            expected, current if actual["alignment_valid"] else []
                        ),
                        "transcription": word_error_rate(
                            " ".join(t["text"] for t in expected),
                            " ".join(s["text"] for s in current)
                            if actual["alignment_valid"]
                            else "",
                        ),
                        "memory": score_memory(
                            [f.model_dump() for f in encounter.facts], facts, segments
                        ),
                        "latency": score_latency(facts, actual, segments),
                    }
                )
                outcome.update(
                    segments=current,
                    facts=facts,
                    facts_on_other_or_unmapped_profiles=[f for f in all_facts if f not in facts],
                    processing_stages_ms={
                        key: percentiles(
                            [
                                r["data"][key]
                                for r in database["job_metrics"]
                                if r["job_id"] in job_ids and key in r["data"]
                            ]
                        )
                        for key in (
                            "decode_ms",
                            "transcription_ms",
                            "voice_ms",
                            "extraction_ms",
                            "verification_ms",
                            "processing_ms",
                        )
                    },
                )
            failures = [u for u in actual["uploads"] if u.get("error")]
            if actual.get("error") or failures or actual["remaining_jobs"]:
                result["status"] = "failed"
                result["errors"].append(
                    f"{encounter.id}: replay error, failed uploads, or unfinished/failed jobs; "
                    "inspect transport.json"
                )
            outcome["unassociated_clips"] = sum(
                u.get("receipt", {}).get("status") == "no_participants" for u in actual["uploads"]
            )
            result["outcomes"].append(outcome)
            write_json(outcome, directory / "observed.json")
    return result
