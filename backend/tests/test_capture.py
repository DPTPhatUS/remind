import asyncio
import json

import pytest

from remind.database import Database, rows
from remind.memory.capture import CaptureStore, milliseconds
from remind.memory.store import MemoryStore


def points(eid=None, pid=None, start=0, end=2000, reason="direct_confirmation", version=1):
    return [
        {
            "ms": t,
            "eligible": bool(eid),
            "encounter_id": eid,
            "visitor_id": pid,
            "person_version": version,
            "reason": reason,
        }
        for t in range(start, end + 1, 100)
    ]


def audio(*turns):
    return {
        "segments": [
            {
                "id": str(i),
                "start_ms": start,
                "end_ms": end,
                "text": text,
                "role": "visitor",
                "voice_score": 0.1,
            }
            for i, (start, end, text) in enumerate(turns)
        ],
        "voice_ready": True,
        "metrics": {"transcription_ms": 10},
    }


async def setup_clip(store, timeline, key="clip", end=2000):
    captures = CaptureStore(store)
    voice = await store.voice_status()
    receipt = await captures.receive_clip("s", key, 0, end, "clip.wav", timeline, voice["version"])
    job = await captures.claim_job("test")
    return captures, receipt, job


async def test_upload_deduplicates_concurrently_without_an_identity(store):
    captures = CaptureStore(store)
    results = await asyncio.gather(
        *(captures.receive_clip("s", "same", 0, 2000, None, [], 0) for _ in range(10))
    )
    assert len({r["clip_id"] for r in results}) == 1
    assert len(await captures.pending_jobs()) == 1
    assert results[0]["status"] == "transcribing"


async def test_no_face_transcript_survives_with_original_voice_role(store):
    captures, receipt, job = await setup_clip(store, points(reason="no_visitor"))
    assert await captures.finish_audio(job, audio((100, 900, "Hello before any face.")))
    assert (await captures.receipt(receipt["clip_id"]))["status"] == "completed_without_attribution"
    async with store.db.transaction() as db:
        turn = json.loads((await rows(db, "SELECT data FROM transcripts"))[0]["data"])
    assert turn["role"] == "visitor"
    assert turn["association"]["status"] == "unattributed"
    assert await captures.pending_jobs() == []


async def test_pending_introduction_resolves_then_cannot_be_reassigned(store):
    person = await store.create_person()
    eid = await store.start_encounter("s", person["id"], 0)
    captures, receipt, job = await setup_clip(store, points(reason="initial_candidate"))
    await captures.finish_audio(job, audio((100, 900, "I am James.")))
    assert (await captures.receipt(receipt["clip_id"]))["status"] == "waiting_for_attribution"
    resolved = points(eid, person["id"], reason="initial_candidate_backfill")
    await captures.update_timeline("s", resolved)
    learned = await captures.claim_job("test")
    assert learned["kind"] == "learning"
    assert learned["payload"]["visitor_id"] == person["id"]
    await captures.update_timeline("s", points(reason="multiple_faces"))
    assert (await captures.learning_segments(learned))[0]["association"]["visitor_id"] == person[
        "id"
    ]


async def test_one_clip_schedules_clear_turns_for_two_encounters(store):
    a, b = await store.create_person(), await store.create_person()
    first = await store.start_encounter("s", a["id"], 0)
    second = await store.start_encounter("s", b["id"], 1000)
    timeline = points(first, a["id"], end=900) + points(second, b["id"], start=1000)
    captures, receipt, job = await setup_clip(store, timeline)
    await captures.finish_audio(
        job,
        audio((100, 800, "James here."), (900, 1100, "A transition."), (1200, 1800, "Sarah here.")),
    )
    async with store.db.transaction() as db:
        jobs = await rows(db, "SELECT encounter_id FROM jobs WHERE kind='learning'")
        turns = [
            json.loads(r["data"])
            for r in await rows(db, "SELECT data FROM transcripts ORDER BY start_ms")
        ]
    assert {r["encounter_id"] for r in jobs} == {first, second}
    assert turns[1]["association"]["status"] == "unattributed"
    assert (await captures.receipt(receipt["clip_id"]))["status"] == "learning"


@pytest.mark.parametrize("action", ["correct", "replace_voice", "delete_voice", "forget"])
async def test_pending_learning_cannot_commit_after_mutation(store, action):
    await store.set_voice_profile([[1, 0]], "fixture")
    person = await store.create_person()
    eid = await store.start_encounter("s", person["id"], 0)
    captures, _, job = await setup_clip(store, points(eid, person["id"]))
    await captures.finish_audio(job, audio((100, 900, "I am James.")))
    learning = await captures.claim_job("test")
    if action == "correct":
        await store.correct_person(person["id"], {"name": "Manual"}, 1)
    elif action == "replace_voice":
        await store.set_voice_profile([[0, 1]], "replacement")
    elif action == "delete_voice":
        await store.delete_voice_profile()
    else:
        await store.forget_person(person["id"])
    assert not await captures.finish_learning(
        learning, {"facts": [], "metrics": {}, "summary": "stale"}
    )


async def test_leases_retries_and_old_worker_cannot_finish(store):
    captures, _, job = await setup_clip(store, [])
    later = milliseconds() + 200000
    current = await captures.claim_job("replacement", later)
    assert current["id"] == job["id"]
    assert not await captures.renew_lease(job["id"], job["lease_token"], later)
    assert await captures.renew_lease(current["id"], current["lease_token"], later)
    assert not await captures.finish_audio(job, audio())
    await captures.fail_job(current["id"], current["lease_token"], "failure", later)
    last = await captures.claim_job("last", later + 6000)
    await captures.fail_job(last["id"], last["lease_token"], "failure", later + 6000)
    assert (await captures.pending_jobs())[0]["status"] == "failed"
    assert await captures.retry_job(last["id"])


async def test_attribution_deadline_and_24_hour_retention(store):
    captures, receipt, job = await setup_clip(store, points(reason="initial_candidate"))
    await captures.finish_audio(job, audio((100, 900, "Unresolved.")))
    await captures.expire(milliseconds() + 31000)
    assert (await captures.receipt(receipt["clip_id"]))["status"] == "completed_without_attribution"
    async with store.db.transaction() as db:
        assert len(await rows(db, "SELECT * FROM transcripts")) == 1
    await captures.expire(milliseconds() + 86401000)
    async with store.db.transaction() as db:
        assert await rows(db, "SELECT * FROM transcripts") == []
    assert "clip.wav" in await store.pending_cleanup()


async def test_restart_retains_audio_and_finalizes_unknown_identity(tmp_path):
    path = tmp_path / "memory.db"
    db = Database(path)
    await db.create_schema()
    store = MemoryStore(db)
    captures, _, job = await setup_clip(store, points(reason="initial_candidate"))
    await captures.finish_audio(job, audio((100, 900, "A saved transcript.")))
    await db.close()
    reopened = Database(path)
    await reopened.create_schema()
    try:
        capture = CaptureStore(MemoryStore(reopened))
        await capture.recover()
        assert await capture.pending_jobs() == []
        async with reopened.transaction() as connection:
            turn = json.loads((await rows(connection, "SELECT data FROM transcripts"))[0]["data"])
        assert turn["text"] == "A saved transcript."
        assert turn["association"]["status"] == "unattributed"
    finally:
        await reopened.close()


def result_for(turn, value="gardening"):
    return {
        "facts": [
            {
                "subject": "visitor",
                "category": "interests",
                "predicate": "interest",
                "value": value,
                "temporal_status": "current",
                "operation": "add",
                "valid_from": None,
                "valid_to": None,
                "target_fact_id": None,
                "evidence": [{"segment_id": turn["id"], "quote": turn["text"]}],
            }
        ],
        "metrics": {},
    }


async def test_forget_shared_recording_preserves_other_persons_committed_text(store):
    await store.set_voice_profile([[1, 0]], "fixture")
    a, b = await store.create_person(), await store.create_person()
    first = await store.start_encounter("s", a["id"], 0)
    second = await store.start_encounter("s", b["id"], 1000)
    captures, receipt, job = await setup_clip(
        store, points(first, a["id"], end=900) + points(second, b["id"], start=1000)
    )
    await captures.finish_audio(
        job, audio((100, 800, "I enjoy gardening."), (1200, 1800, "I enjoy cooking."))
    )
    for value in ("gardening", "cooking"):
        learning = await captures.claim_job("test")
        source = (await captures.learning_segments(learning))[0]
        assert await captures.finish_learning(learning, result_for(source, value))
    await store.forget_person(a["id"])
    assert await store.facts_for_person(a["id"]) == []
    assert [f["value"] for f in await store.facts_for_person(b["id"])] == ["cooking"]
    assert [t["text"] for t in await store.recent_context(second)] == ["I enjoy cooking."]
    assert "clip.wav" in await store.pending_cleanup()
    async with store.db.transaction() as db:
        clip = (
            await rows(
                db, "SELECT path,cancelled,timeline FROM clips WHERE id=?", (receipt["clip_id"],)
            )
        )[0]
    assert clip == {"path": None, "cancelled": 1, "timeline": "[]"}


async def test_transaction_rejects_an_evidence_quote_with_wrong_association(store):
    await store.set_voice_profile([[1, 0]], "fixture")
    person = await store.create_person()
    eid = await store.start_encounter("s", person["id"], 0)
    captures, _, job = await setup_clip(store, points(eid, person["id"]))
    await captures.finish_audio(job, audio((100, 900, "I enjoy gardening.")))
    learning = await captures.claim_job("test")
    source = (await captures.learning_segments(learning))[0]
    # Simulate an untrusted model proposing a genuine quote from an ineligible turn.
    source["association"]["status"] = "unattributed"
    async with store.db.transaction() as db:
        await db.execute(
            "UPDATE transcripts SET data=? WHERE id=?", (json.dumps(source), source["id"])
        )
    assert await captures.finish_learning(learning, result_for(source))
    assert await store.facts_for_person(person["id"]) == []


async def test_correction_before_initial_identity_resolution_prevents_learning(store):
    person = await store.create_person()
    eid = await store.start_encounter("s", person["id"], 0)
    captures, receipt, job = await setup_clip(store, points(reason="initial_candidate"))
    await captures.finish_audio(job, audio((100, 900, "I am James.")))
    await store.correct_person(person["id"], {"name": "Manual"}, 1)
    await captures.update_timeline("s", points(eid, person["id"], version=1))
    assert (await captures.receipt(receipt["clip_id"]))["status"] == "completed_without_attribution"
    assert await captures.pending_jobs() == []


async def test_restart_after_audio_preserves_transcript_and_resumes_learning(store):
    person = await store.create_person()
    eid = await store.start_encounter("s", person["id"], 0)
    captures, _, job = await setup_clip(store, points(eid, person["id"]))
    await captures.finish_audio(job, audio((100, 900, "I enjoy gardening.")))
    claimed = await captures.claim_job("old-process")
    await CaptureStore(store).recover()
    resumed = await captures.claim_job("new-process")
    assert resumed["id"] == claimed["id"]
    assert resumed["lease_token"] != claimed["lease_token"]
    assert [t["text"] for t in await captures.learning_segments(resumed)] == ["I enjoy gardening."]
    assert not await captures.finish_learning(claimed, {"facts": [], "metrics": {}})


async def test_media_expiry_preserves_learning_that_only_needs_saved_text(store):
    await store.set_voice_profile([[1, 0]], "fixture")
    person = await store.create_person()
    eid = await store.start_encounter("s", person["id"], 0)
    captures, _, job = await setup_clip(store, points(eid, person["id"]))
    await captures.finish_audio(job, audio((100, 900, "I enjoy gardening.")))
    await captures.expire(milliseconds() + 86401000)
    learning = await captures.claim_job("after-media-expiry")
    assert learning is not None and learning["kind"] == "learning"
    source = (await captures.learning_segments(learning))[0]
    assert await captures.finish_learning(learning, result_for(source))
    assert [f["value"] for f in await store.facts_for_person(person["id"])] == ["gardening"]


async def test_missing_reference_allows_neutral_summary_but_never_profile_facts(store):
    person = await store.create_person()
    eid = await store.start_encounter("s", person["id"], 0)
    captures, _, job = await setup_clip(store, points(eid, person["id"]))
    # Even erroneous decisive roles cannot bypass the final reference guard.
    await captures.finish_audio(job, audio((100, 900, "I enjoy gardening.")))
    learning = await captures.claim_job("test")
    source = (await captures.learning_segments(learning))[0]
    result = {**result_for(source), "summary": "Gardening was discussed."}
    assert await captures.finish_learning(learning, result)
    assert await store.facts_for_person(person["id"]) == []
    assert (await store.get_encounter(eid))["summary"] == "Gardening was discussed."
