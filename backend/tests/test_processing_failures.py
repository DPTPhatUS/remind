"""Automatic attempts, terminal failures, and late intake through real persistence."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from remind.config import Settings
from remind.database import Database, rows
from remind.memory.capture import CaptureStore
from remind.memory.jobs import JobQueue
from remind.memory.learning import learn_conversation
from remind.memory.store import MemoryStore
from remind.memory.worker import MemoryWorker


@pytest.fixture
async def scenario(store, captures, monkeypatch):
    clock = SimpleNamespace(now=1_000_000)
    monkeypatch.setattr("remind.memory.capture.milliseconds", lambda: clock.now)
    await store.set_voice_profile([[1, 0]], "fixture")
    person = await store.create_person()
    encounter = await store.start_encounter("session", person["id"], 0)

    async def receive(start):
        clock.now += 1000
        timeline = [
            {
                "ms": stamp,
                "eligible": True,
                "reason": "direct_confirmation",
                "encounter_id": encounter,
                "visitor_id": person["id"],
                "person_version": 1,
            }
            for stamp in range(start, start + 1001, 100)
        ]
        return await captures.receive_clip(
            "session", str(start), start, start + 1000, f"{start}.wav", timeline, 1
        )

    return SimpleNamespace(
        store=store,
        captures=captures,
        jobs=captures.jobs,
        person=person,
        encounter=encounter,
        clock=clock,
        receive=receive,
    )


def audio(text="I enjoy gardening."):
    return {
        "segments": [
            {"id": "turn", "start_ms": 100, "end_ms": 900, "role": "visitor", "text": text}
        ],
        "voice_ready": True,
        "metrics": {},
    }


async def fail_audio(scenario, start=0):
    receipt = await scenario.receive(start)
    job = await scenario.jobs.claim("test", scenario.clock.now)
    await exhaust_attempts(scenario, job)
    return receipt, job


async def exhaust_attempts(scenario, job):
    ident = job["id"]
    for attempt in range(3):
        assert job["id"] == ident
        await scenario.jobs.fail(
            job["id"], job["lease_token"], "Provider unavailable", scenario.clock.now
        )
        if attempt < 2:
            scenario.clock.now += 5000
            job = await scenario.jobs.claim("test", scenario.clock.now)


async def ready_audio(scenario, start, text="I enjoy gardening.", role="visitor"):
    receipt = await scenario.receive(start)
    job = await scenario.jobs.claim("test", scenario.clock.now)
    assert job["kind"] == "audio" and job["clip_id"] == receipt["clip_id"]
    result = audio(text)
    result["segments"][0]["role"] = role
    result["segments"][0]["id"] = job["id"] + ":turn"
    assert await scenario.captures.finish_audio(job, result)
    return receipt


async def saved_interest(scenario, job, value="gardening"):
    turn = (await scenario.captures.learning_segments(job))[0]
    result = {
        "summary": f"Discussed {value}.",
        "metrics": {},
        "facts": [
            {
                "subject": "visitor",
                "category": "interests",
                "predicate": "interest",
                "value": value,
                "operation": "add",
                "temporal_status": "current",
                "valid_from": None,
                "valid_to": None,
                "target_fact_id": None,
                "evidence": [{"segment_id": turn["id"], "quote": turn["text"]}],
            }
        ],
    }
    return await scenario.captures.finish_learning(job, result)


@pytest.mark.parametrize("kind", ["audio", "learning"])
async def test_exhausted_attempts_release_later_learning_without_expiry(scenario, kind):
    if kind == "audio":
        first, failed = await fail_audio(scenario)
    else:
        first = await ready_audio(scenario, 0)
        failed = await scenario.jobs.claim("test", scenario.clock.now)
        await exhaust_attempts(scenario, failed)
    second = await ready_audio(scenario, 1000)
    learning = await scenario.jobs.claim("test", scenario.clock.now)
    assert learning["kind"] == "learning" and learning["clip_id"] == second["clip_id"]
    assert await saved_interest(scenario, learning)
    assert [f["value"] for f in await scenario.store.facts_for_person(scenario.person["id"])] == [
        "gardening"
    ]
    assert (await scenario.captures.receipt(first["clip_id"]))["status"] == "failed"
    async with scenario.store.db.transaction() as db:
        clip = (
            await rows(
                db, "SELECT audio_done,cancelled,path FROM clips WHERE id=?", (first["clip_id"],)
            )
        )[0]
        job = (
            await rows(db, "SELECT status,attempts,error FROM jobs WHERE id=?", (failed["id"],))
        )[0]
    assert clip == {"audio_done": int(kind == "learning"), "cancelled": 0, "path": "0.wav"}
    assert job == {"status": "failed", "attempts": 3, "error": "Provider unavailable"}
    if kind == "audio":
        assert not await scenario.captures.finish_audio(failed, audio())
    else:
        assert not await saved_interest(scenario, failed, "cooking")


async def test_transient_failure_still_blocks_learning_but_not_later_audio(scenario):
    await scenario.receive(0)
    first = await scenario.jobs.claim("test", scenario.clock.now)
    second = await ready_audio(scenario, 1000)
    await scenario.jobs.fail(
        first["id"], first["lease_token"], "Temporary failure", scenario.clock.now
    )
    assert await scenario.jobs.claim("test", scenario.clock.now) is None
    scenario.clock.now += 5000
    retried = await scenario.jobs.claim("test", scenario.clock.now)
    assert retried["id"] == first["id"]
    assert await scenario.captures.finish_audio(
        retried, {"segments": [], "metrics": {}, "voice_ready": True}
    )
    learning = await scenario.jobs.claim("test", scenario.clock.now)
    assert learning["clip_id"] == second["clip_id"]


async def test_successful_audio_still_waits_for_pending_attribution(scenario):
    await scenario.receive(0)
    first = await scenario.jobs.claim("test", scenario.clock.now)
    async with scenario.store.db.transaction() as db:
        await db.execute(
            "UPDATE clips SET timeline=? WHERE id=?",
            (
                json.dumps(
                    [
                        {"ms": t, "eligible": False, "reason": "initial_candidate"}
                        for t in range(0, 1001, 100)
                    ]
                ),
                first["clip_id"],
            ),
        )
    await scenario.captures.finish_audio(first, audio("Hello."))
    await ready_audio(scenario, 1000)
    assert await scenario.jobs.claim("test", scenario.clock.now) is None
    await scenario.captures.update_timeline("session", [], final=True)
    assert (await scenario.jobs.claim("test", scenario.clock.now))["kind"] == "learning"


@pytest.mark.parametrize("failed", [False, True])
async def test_expired_pending_or_failed_audio_releases_later_learning(scenario, failed):
    if failed:
        first, _ = await fail_audio(scenario)
    else:
        first = await scenario.receive(0)
        await scenario.jobs.claim("test", scenario.clock.now)
    second = await ready_audio(scenario, 1000)
    async with scenario.store.db.transaction() as db:
        await db.execute(
            "UPDATE clips SET expires_ms=? WHERE id=?", (scenario.clock.now, first["clip_id"])
        )
    await scenario.captures.expire(scenario.clock.now)
    receipt = await scenario.captures.receipt(first["clip_id"])
    assert receipt["status"] == ("failed" if failed else "cancelled")
    assert receipt["jobs"][0]["error"] == ("Provider unavailable" if failed else "Media expired")
    learning = await scenario.jobs.claim("test", scenario.clock.now)
    assert learning["clip_id"] == second["clip_id"]
    assert await saved_interest(scenario, learning)
    assert "0.wav" in await scenario.store.pending_cleanup()


@pytest.mark.parametrize("kind", ["audio", "learning"])
async def test_expired_final_attempt_lease_does_not_block_learning(scenario, kind):
    if kind == "audio":
        _, first = await fail_audio(scenario)
    else:
        await ready_audio(scenario, 0)
        first = await scenario.jobs.claim("test", scenario.clock.now)
        await exhaust_attempts(scenario, first)
    # Crash during the final attempt rather than receiving a provider exception.
    async with scenario.store.db.transaction() as db:
        await db.execute(
            "UPDATE jobs SET status='running',lease_token='old',lease_until=? WHERE id=?",
            (scenario.clock.now - 1, first["id"]),
        )
    second = await ready_audio(scenario, 1000)
    assert (await scenario.jobs.claim("test", scenario.clock.now))["clip_id"] == second["clip_id"]


async def test_extraction_retry_keeps_transcript_and_blocks_only_dependent_learning(scenario):
    first = await ready_audio(scenario, 0, "I enjoy cooking.")
    learning = await scenario.jobs.claim("test", scenario.clock.now)
    await scenario.jobs.fail(
        learning["id"], learning["lease_token"], "Temporary failure", scenario.clock.now
    )
    second = await ready_audio(scenario, 1000)
    assert await scenario.jobs.claim("test", scenario.clock.now) is None
    scenario.clock.now += 5000
    retried = await scenario.jobs.claim("test", scenario.clock.now)
    assert retried["id"] == learning["id"]
    assert await saved_interest(scenario, retried, "cooking")
    assert not await saved_interest(scenario, learning, "stale")
    assert not await saved_interest(scenario, retried, "duplicate")
    later = await scenario.jobs.claim("test", scenario.clock.now)
    assert later["clip_id"] == second["clip_id"]
    async with scenario.store.db.transaction() as db:
        audio_job = (
            await rows(
                db,
                "SELECT status,attempts FROM jobs WHERE clip_id=? AND kind='audio'",
                (first["clip_id"],),
            )
        )[0]
        evidence = await rows(db, "SELECT * FROM fact_evidence")
    assert audio_job == {"status": "done", "attempts": 1}
    assert len(evidence) == 1
    assert await scenario.store.latest_audio_gap(scenario.encounter, 2000) is None


@pytest.mark.parametrize("state", ["running", "pending", "failed", "done"])
async def test_late_upload_is_skipped_after_learning_starts(scenario, state):
    await ready_audio(scenario, 1000)
    learning = await scenario.jobs.claim("test", scenario.clock.now)
    if state == "pending":
        await scenario.jobs.fail(
            learning["id"], learning["lease_token"], "Temporary failure", scenario.clock.now
        )
    elif state == "failed":
        await exhaust_attempts(scenario, learning)
    elif state == "done":
        assert await saved_interest(scenario, learning)
    before = await scenario.store.get_encounter(scenario.encounter)
    receipt = await scenario.receive(0)
    assert receipt["status"] == "skipped"
    assert receipt["jobs"][0]["status"] == "skipped"
    assert receipt["jobs"][0]["error"] == "Recording arrived after newer learning started"
    assert "0.wav" in await scenario.store.pending_cleanup()
    assert await scenario.jobs.claim("test", scenario.clock.now) is None
    async with scenario.store.db.transaction() as db:
        clip = (
            await rows(
                db, "SELECT path,timeline,audio_done FROM clips WHERE id=?", (receipt["clip_id"],)
            )
        )[0]
        transcripts = await rows(
            db, "SELECT * FROM transcripts WHERE clip_id=?", (receipt["clip_id"],)
        )
    assert clip == {"path": None, "timeline": "[]", "audio_done": 0}
    assert transcripts == []
    assert await scenario.store.get_encounter(scenario.encounter) == before
    assert await scenario.store.latest_audio_gap(scenario.encounter, 2000) is None
    assert any(j["status"] == "skipped" for j in await scenario.jobs.pending())


async def test_skipped_upload_never_calls_processing_and_duplicate_stays_skipped(
    scenario, tmp_path
):
    await ready_audio(scenario, 1000)
    learning = await scenario.jobs.claim("test", scenario.clock.now)
    assert await saved_interest(scenario, learning)
    recording = tmp_path / "spool" / "late.webm"
    recording.parent.mkdir()
    recording.write_bytes(b"uploaded recording")
    first = await scenario.captures.receive_clip("session", "0", 0, 1000, str(recording), [], 1)
    duplicate = await scenario.receive(0)
    assert duplicate == first
    worker = MemoryWorker(
        scenario.store,
        Settings(data_dir=tmp_path, openai_api_key=""),
        None,
        scenario.captures,
        verifier=object(),
    )

    class UnusedProvider:
        async def transcribe(self, *args):
            pytest.fail("Skipped uploads must not reach providers")

        async def extract(self, *args):
            pytest.fail("Skipped uploads must not reach providers")

        async def close(self):
            pass

    worker.providers = UnusedProvider()
    try:
        assert not await worker.run_once()
        await worker.cleanup()
        assert not recording.exists()
    finally:
        await worker.close()
    async with scenario.store.db.transaction() as db:
        assert len(await rows(db, "SELECT id FROM clips")) == 2
        assert len(await rows(db, "SELECT id FROM jobs WHERE kind='audio'")) == 2


async def test_duplicate_of_failed_upload_cannot_reopen_it(scenario):
    first, _ = await fail_audio(scenario)
    await ready_audio(scenario, 1000)
    await scenario.jobs.claim("test", scenario.clock.now)
    duplicate = await scenario.receive(0)
    assert duplicate == await scenario.captures.receipt(first["clip_id"])
    assert duplicate["status"] == "failed"
    assert duplicate["jobs"][0]["error"] == "Provider unavailable"


async def test_arrival_before_later_claim_preserves_capture_order(scenario):
    later = await ready_audio(scenario, 1000)
    first = await scenario.receive(0)
    assert first["status"] == "transcribing"
    job = await scenario.jobs.claim("test", scenario.clock.now)
    assert job["kind"] == "audio" and job["clip_id"] == first["clip_id"]
    result = audio()
    result["segments"][0]["id"] = job["id"] + ":turn"
    assert await scenario.captures.finish_audio(job, result)
    first_learning = await scenario.jobs.claim("test", scenario.clock.now)
    assert first_learning["clip_id"] == first["clip_id"]
    assert await saved_interest(scenario, first_learning)
    assert (await scenario.jobs.claim("test", scenario.clock.now))["clip_id"] == later["clip_id"]


async def test_intake_racing_learning_claim_has_one_consistent_order(scenario):
    later = await ready_audio(scenario, 1000)
    receipt, claimed = await asyncio.gather(
        scenario.receive(0), scenario.jobs.claim("test", scenario.clock.now)
    )
    if receipt["status"] == "skipped":
        assert claimed["kind"] == "learning" and claimed["clip_id"] == later["clip_id"]
    else:
        assert receipt["status"] == "transcribing"
        assert claimed is None or (
            claimed["kind"] == "audio" and claimed["clip_id"] == receipt["clip_id"]
        )


async def test_new_capture_generation_is_not_late(scenario):
    await ready_audio(scenario, 1000)
    await scenario.jobs.claim("test", scenario.clock.now)
    receipt = await scenario.captures.receive_clip("new-session", "0", 0, 1000, "new.wav", [], 1)
    job = await scenario.jobs.claim("test", scenario.clock.now)
    assert receipt["status"] == "transcribing"
    assert job["kind"] == "audio" and job["clip_id"] == receipt["clip_id"]


async def test_trusted_transcript_encounters_can_restart_their_clock(scenario):
    await ready_audio(scenario, 1000)
    assert await saved_interest(scenario, await scenario.jobs.claim("test", scenario.clock.now))
    eid = await scenario.store.start_encounter("session", scenario.person["id"], 0)
    job = await scenario.captures.receive_transcript_batch(
        eid, "trusted", 0, 1000, audio()["segments"]
    )
    assert job["kind"] == "learning" and job["encounter_id"] == eid
    assert await saved_interest(scenario, job)


@pytest.mark.parametrize("kind", ["audio", "learning"])
async def test_restart_preserves_failure_attempts_and_releases_later_work(scenario, kind):
    if kind == "audio":
        first, failed = await fail_audio(scenario)
    else:
        first = await ready_audio(scenario, 0)
        failed = await scenario.jobs.claim("test", scenario.clock.now)
        await exhaust_attempts(scenario, failed)
    second = await ready_audio(scenario, 1000)
    path = scenario.store.db.path
    await scenario.store.db.close()
    reopened = Database(path)
    await reopened.create_schema()
    try:
        captures = CaptureStore(MemoryStore(reopened), JobQueue(reopened))
        await captures.recover()
        job = await captures.jobs.claim("new-process", scenario.clock.now)
        assert job["kind"] == "learning" and job["clip_id"] == second["clip_id"]
        receipt = await captures.receipt(first["clip_id"])
        assert receipt["status"] == "failed"
        failure = next(j for j in receipt["jobs"] if j["kind"] == kind)
        assert failure["error"] == "Provider unavailable"
        persisted = next(j for j in await captures.jobs.pending() if j["id"] == failed["id"])
        assert persisted["attempts"] == 3
        assert await captures.memory.latest_audio_gap(scenario.encounter, 2000) == (
            1000 if kind == "audio" else None
        )
    finally:
        await reopened.close()


async def test_restart_keeps_skipped_upload_terminal_and_attempts_monotonic(scenario):
    await ready_audio(scenario, 1000)
    running = await scenario.jobs.claim("old-process", scenario.clock.now)
    skipped = await scenario.receive(0)
    await scenario.captures.recover()
    resumed = await scenario.jobs.claim("new-process", scenario.clock.now)
    assert resumed["id"] == running["id"] and resumed["attempts"] == 1
    assert resumed["lease_token"] != running["lease_token"]
    assert not await saved_interest(scenario, running)
    assert await saved_interest(scenario, resumed)
    assert await scenario.captures.receipt(skipped["clip_id"]) == skipped
    assert await scenario.jobs.claim("test", scenario.clock.now) is None


async def test_context_and_summary_do_not_cross_missing_audio(scenario):
    await ready_audio(scenario, 0, "Do you live in London?", role="user")
    question = await scenario.jobs.claim("test", scenario.clock.now)
    assert await scenario.captures.finish_learning(
        question,
        {
            "facts": [],
            "metrics": {},
            "summary": "The user asked whether the visitor lives in London.",
        },
    )
    await fail_audio(scenario, 1000)
    await ready_audio(scenario, 2000, "Yes.")
    answer = await scenario.jobs.claim("test", scenario.clock.now)
    segments = await scenario.captures.learning_segments(answer)

    class Provider:
        received = []
        previous_summary = None

        async def extract(self, dialogue, previous_summary, facts, encounter_time, current_ids):
            self.received = dialogue
            self.previous_summary = previous_summary
            return {"facts": [], "summary": "A short answer was heard."}

        async def verify(self, facts, dialogue, existing):
            return {"assessments": []}

    provider = Provider()
    await learn_conversation(
        scenario.store,
        provider,
        Settings(),
        scenario.encounter,
        scenario.person["id"],
        segments,
        2100,
        can_learn=True,
    )
    assert [turn["text"] for turn in provider.received] == ["Yes."]
    assert provider.previous_summary == ""
    assert await scenario.store.facts_for_person(scenario.person["id"]) == []
    assert await scenario.captures.finish_learning(
        answer, {"facts": [], "metrics": {}, "summary": "A short answer was heard."}
    )
    await ready_audio(scenario, 3000, "I live in Manchester.")
    following = await scenario.jobs.claim("test", scenario.clock.now)
    await learn_conversation(
        scenario.store,
        provider,
        Settings(),
        scenario.encounter,
        scenario.person["id"],
        await scenario.captures.learning_segments(following),
        3100,
        can_learn=True,
    )
    assert [turn["text"] for turn in provider.received] == ["Yes.", "I live in Manchester."]
    assert provider.previous_summary == "A short answer was heard."
