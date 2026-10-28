"""Trusted role-labelled dialogue through production learning and claim persistence."""

import time
from pathlib import Path

from remind.audio.providers import Providers
from remind.benchmark.inputs import ConversationCase
from remind.benchmark.scoring import score_memory
from remind.config import Settings
from remind.database import Database
from remind.memory.capture import CaptureStore
from remind.memory.learning import learn_conversation
from remind.memory.store import MemoryStore


async def run_case(case: ConversationCase, output: Path, settings: Settings) -> dict:
    database = Database(output / "data.sqlite3")
    await database.create_schema()
    store = MemoryStore(database)
    captures = CaptureStore(store)
    providers = Providers(settings)
    result: dict = {"id": case.id, "status": "complete", "outcomes": [], "errors": []}
    person_id: str | None = None
    current_job_id: str | None = None
    all_segments = []
    batches = []
    try:
        person = await store.create_person()
        person_id = person["id"]
        for encounter in case.encounters:
            eid = await store.start_encounter("text-benchmark", person["id"], 0)
            async with database.transaction() as connection:
                await connection.execute(
                    "UPDATE encounters SET started_at=? WHERE id=?",
                    (encounter.started_at.isoformat(), eid),
                )
            for batch in encounter.batches:
                job = await captures.receive_transcript_batch(
                    eid,
                    batch.id,
                    batch.start_ms,
                    batch.end_ms,
                    [{**t.model_dump(), "speaker": t.role} for t in batch.turns],
                )
                job_id = job["id"]
                current_job_id = job_id
                segments = await captures.learning_segments(job)
                started = time.perf_counter()
                learned = await learn_conversation(
                    store,
                    providers,
                    settings,
                    eid,
                    person["id"],
                    segments,
                    batch.start_ms,
                    can_learn=True,
                )
                phase = time.perf_counter()
                if not await captures.finish_learning(job, learned):
                    raise RuntimeError("Transcript batch was invalidated before commit")
                current_job_id = None
                learned["metrics"]["commit_ms"] = (time.perf_counter() - phase) * 1000
                learned["metrics"]["processing_ms"] = (time.perf_counter() - started) * 1000
                all_segments.extend(segments)
                batches.append({"encounter_id": encounter.id, "batch_id": batch.id, **learned})
            await store.close_encounter(eid, encounter.batches[-1].end_ms)
    except Exception as exc:
        result["status"] = "failed"
        result["errors"].append(str(exc))
        if current_job_id is not None:
            async with database.transaction() as connection:
                await connection.execute(
                    "UPDATE jobs SET status='failed',lease_token=NULL,error=? WHERE id=?",
                    (str(exc), current_job_id),
                )
    finally:
        try:
            facts = await store.facts_for_person(person_id) if person_id else []
            result["outcomes"].append(
                {
                    "id": case.id,
                    "person_id": person_id,
                    "batches": batches,
                    "facts": facts,
                    "segments": all_segments,
                    "scores": {
                        "memory": score_memory(
                            [f.model_dump() for f in case.facts], facts, all_segments
                        )
                    },
                }
            )
        finally:
            await providers.close()
            await database.close()
    return result
