"""Injected providers/voice, with real SQLite and capture-time visitor timelines."""

import numpy as np
import pytest

from remind.audio.processing import transcript_segments
from remind.config import Settings
from remind.database import Database, rows
from remind.live.session import LiveSession
from remind.memory.association import associate_turn
from remind.memory.capture import CaptureStore
from remind.memory.learning import bounded_dialogue
from remind.memory.store import MemoryStore
from remind.memory.worker import MemoryWorker


class Verifier:
    def classify(self, pcm, segments, profile):
        return [{**segment, "role": "visitor"} for segment in segments]


class Provider:
    def __init__(self, segments, claims=None, on_extract=None):
        self.segments = segments
        self.transcription_calls = 0
        self.claims = claims
        self.on_extract = on_extract
        self.received = []
        self.encounter_time = None
        self.previous_summary = None

    async def transcribe(self, pcm):
        self.transcription_calls += 1
        return self.segments

    async def extract(
        self,
        dialogue,
        previous_summary,
        existing_facts,
        encounter_time,
        current_ids,
    ):
        self.received = dialogue
        self.encounter_time = encounter_time
        self.previous_summary = previous_summary
        if self.on_extract:
            await self.on_extract()
        current = [s for s in dialogue if s["id"] in current_ids]
        claims = self.claims(dialogue, current) if self.claims else []
        return {"summary": "Anna visited and discussed work and gardening.", "facts": claims}

    async def verify(self, facts, dialogue, existing_facts):
        return {
            "assessments": [
                {
                    "fact_index": i,
                    "supported": True,
                    "affirmative": True,
                    "reason": "Fixture semantic verification",
                }
                for i in range(len(facts))
            ]
        }

    async def close(self):
        pass


def claim(segment, predicate="name", value="Anna", category="identity", evidence=None):
    return {
        "subject": "visitor",
        "category": category,
        "predicate": predicate,
        "value": value,
        "polarity": "affirmative",
        "temporal_status": "current",
        "valid_from": None,
        "valid_to": None,
        "operation": "add",
        "target_fact_id": None,
        "evidence": evidence or [{"segment_id": segment["id"], "quote": segment["text"]}],
    }


def transcript(text="Everyone calls me Anna.", speaker="A"):
    return [{"id": "s", "speaker": speaker, "text": text, "start_ms": 200, "end_ms": 1200}]


async def make_store(tmp_path, voice=True):
    settings = Settings(data_dir=tmp_path, openai_api_key="")
    db = Database(str(tmp_path / "memory.db"))
    await db.create_schema()
    store = MemoryStore(db)
    if voice:
        await store.set_voice_profile([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]], "fixture-voice")
    return settings, db, store


async def queue(store, pid, key="intro", start=0, encounter=None, eligible=True):
    encounter = encounter or await store.start_encounter("first", pid, start)
    voice = await store.voice_status()
    timeline = [
        {
            "ms": stamp,
            "visitor_id": pid,
            "encounter_id": encounter,
            "person_version": (await store.get_person(pid))["version"],
            "eligible": eligible,
            "face_count": 1 if eligible else 2,
            "reason": "direct_confirmation" if eligible else "multiple_faces",
        }
        for stamp in range(start, start + 2001, 100)
    ]
    captures = CaptureStore(store)
    receipt = await captures.receive_clip(
        "first", key, start, start + 2000, "injected.webm", timeline, voice["version"]
    )
    return receipt["jobs"][0]["id"], {"encounter": encounter, "clip_id": receipt["clip_id"]}


async def process(worker):
    first = await worker.run_once()
    for _ in range(10):
        if not await worker.run_once():
            break
    return first


async def read_metrics(store):
    async with store.db.transaction() as db:
        found = await rows(db, "SELECT job_id,data FROM job_metrics ORDER BY rowid")
    import json

    result = {}
    for record in found:
        result.update(json.loads(record["data"]))
    return [{"job_id": found[0]["job_id"], **result}]


def inject_audio(monkeypatch, continuous=True):
    monkeypatch.setattr(
        "remind.audio.processing.decode_audio",
        lambda _: {
            "pcm": np.ones(32000, dtype=np.int16),
            "continuous": continuous,
        },
    )
    monkeypatch.setattr("remind.audio.processing.has_speech", lambda pcm: True)


async def test_introduction_worker_restart_and_automatic_recall(tmp_path, monkeypatch):
    settings, db, store = await make_store(tmp_path)
    vector = np.eye(128, dtype=np.float32)[0]
    person = await store.enroll_person(None, [vector])
    job, payload = await queue(store, person["id"])
    inject_audio(monkeypatch)
    worker = MemoryWorker(store, settings, None, verifier=Verifier())
    worker.providers = Provider(transcript(), lambda _, current: [claim(current[0])])
    assert await process(worker)
    assert (await store.get_person(person["id"]))["name"] == "Anna"
    assert (await store.recent_context(payload["encounter"]))[0]["id"].startswith(job + ":")
    metric = (await read_metrics(store))[0]
    assert metric["proposed_facts"] == metric["verified_facts"] == 1
    assert metric["visitor_segments"] == 1
    assert all(
        metric[field] >= 0
        for field in (
            "decode_ms",
            "transcription_ms",
            "voice_ms",
            "extraction_ms",
            "verification_ms",
            "processing_ms",
        )
    )
    assert not await process(worker)
    await worker.close()
    await store.close_encounter(payload["encounter"], 2000)
    await db.close()

    reopened = Database(str(tmp_path / "memory.db"))
    await reopened.create_schema()
    returning = LiveSession("return", MemoryStore(reopened), settings)
    observation = {
        "box": [0.3, 0.2, 0.3, 0.4],
        "embedding": vector,
        "quality": True,
        "thumbnail": b"x",
    }
    for stamp in (0, 100, 200):
        tracks = await returning.observe([observation], stamp)
    memory = tracks["encounter"]["memory"]
    assert memory["name"] == "Anna"
    assert memory["last_encounter"]["summary"].startswith("Anna visited")
    assert memory["last_encounter"]["id"] == payload["encounter"]
    await returning.stop()
    await reopened.close()


@pytest.mark.parametrize("reason", ["no_voice", "multiple_faces", "discontinuous_audio"])
async def test_unreliable_roles_save_neutral_memory_without_profile_facts(
    tmp_path,
    monkeypatch,
    reason,
):
    settings, db, store = await make_store(tmp_path, voice=reason != "no_voice")
    person = await store.create_person()
    _, payload = await queue(store, person["id"], eligible=reason != "multiple_faces")
    inject_audio(monkeypatch, continuous=reason != "discontinuous_audio")
    worker = MemoryWorker(store, settings, None, verifier=Verifier())
    worker.providers = Provider(transcript(), lambda _, current: [claim(current[0])])
    await process(worker)
    assert await store.facts_for_person(person["id"]) == []
    context = await store.recent_context(payload["encounter"])
    if reason == "multiple_faces":
        assert context == []
        async with db.transaction() as connection:
            import json

            raw = json.loads((await rows(connection, "SELECT data FROM transcripts"))[0]["data"])
        assert raw["role"] == "visitor"
        assert raw["association"]["status"] == "unattributed"
    else:
        assert context[0]["role"] == "uncertain"
        assert (await store.get_encounter(payload["encounter"]))["summary"]
    await worker.close()
    await db.close()


async def test_question_context_survives_clips_with_changing_speaker_labels(tmp_path, monkeypatch):
    settings, db, store = await make_store(tmp_path)
    person = await store.create_person()
    _, payload = await queue(store, person["id"], "question")
    inject_audio(monkeypatch)
    worker = MemoryWorker(store, settings, None, verifier=Verifier())

    class UserVerifier:
        def classify(self, pcm, segments, profile):
            return [{**s, "role": "user"} for s in segments]

    worker.verifier = UserVerifier()
    worker.providers = Provider(transcript("Where do you work?", "A"))
    await process(worker)
    await queue(store, person["id"], "answer", start=2000, encounter=payload["encounter"])
    worker.verifier = Verifier()

    def contextual(dialogue, current):
        question, answer = dialogue[0], current[0]
        assert question["role"] == "user" and answer["role"] == "visitor"
        assert question["speaker"] == answer["speaker"] == "A"  # labels have no global identity
        assert question["id"] != answer["id"]
        return [
            claim(
                answer,
                "workplace",
                "primary school",
                "work",
                evidence=[
                    {"segment_id": question["id"], "quote": question["text"]},
                    {"segment_id": answer["id"], "quote": answer["text"]},
                ],
            )
        ]

    worker.providers = Provider(transcript("At the primary school.", "A"), contextual)
    await process(worker)
    facts = await store.facts_for_person(person["id"])
    assert len(facts) == 1 and facts[0]["value"] == "primary school"
    assert len(facts[0]["evidence"]) == 2
    await worker.close()
    await db.close()


async def test_late_old_clip_cannot_use_future_utterance_as_confirmation(tmp_path, monkeypatch):
    settings, db, store = await make_store(tmp_path)
    person = await store.create_person()
    _, future = await queue(store, person["id"], "future-question", start=2000)
    inject_audio(monkeypatch)

    class UserVerifier:
        def classify(self, pcm, segments, profile):
            return [{**s, "role": "user"} for s in segments]

    worker = MemoryWorker(store, settings, None, verifier=UserVerifier())
    worker.providers = Provider(transcript("Do you live in Da Nang?"))
    await process(worker)
    future_question = (await store.recent_context(future["encounter"]))[0]
    assert future_question["start_ms"] == 2200

    # The earlier upload arrives after the later question has already been saved.
    await queue(store, person["id"], "late-answer", start=0, encounter=future["encounter"])

    def contextual(dialogue, current):
        questions = [s for s in dialogue if s["text"] == "Do you live in Da Nang?"]
        if not questions:
            return []
        return [
            claim(
                current[0],
                "residence",
                "Da Nang",
                "residence",
                evidence=[
                    {"segment_id": questions[0]["id"], "quote": questions[0]["text"]},
                    {"segment_id": current[0]["id"], "quote": current[0]["text"]},
                ],
            )
        ]

    worker.verifier = Verifier()
    provider = Provider(transcript("Yes."), contextual)
    worker.providers = provider
    await process(worker)
    assert future_question["id"] not in {s["id"] for s in provider.received}
    assert provider.previous_summary == ""
    assert await store.facts_for_person(person["id"]) == []
    await worker.close()
    await db.close()


@pytest.mark.parametrize("action", ["forget", "correct", "replace_voice"])
async def test_pending_extraction_cannot_undo_concurrent_mutation(tmp_path, monkeypatch, action):
    settings, db, store = await make_store(tmp_path)
    person = await store.create_person()
    await queue(store, person["id"])
    inject_audio(monkeypatch)

    async def mutation():
        if action == "forget":
            await store.forget_person(person["id"])
        elif action == "correct":
            await store.correct_person(person["id"], {"name": "Grace"}, person["version"])
        else:
            await store.set_voice_profile([[0.0, 1.0, 0.0]], "replacement")

    worker = MemoryWorker(store, settings, None, verifier=Verifier())
    worker.providers = Provider(transcript(), lambda _, current: [claim(current[0])], mutation)
    await process(worker)
    current = await store.get_person(person["id"])
    if action == "forget":
        assert current is None
        assert await store.facts_for_person(person["id"]) == []
    elif action == "correct":
        assert current["name"] == "Grace"
    else:
        assert current["name"] is None
    await worker.close()
    await db.close()


def test_capture_time_association_requires_whole_turn_and_fresh_history():
    turn = {"start_ms": 200, "end_ms": 900}
    timeline = [
        {
            "ms": ms,
            "eligible": True,
            "visitor_id": "anna",
            "encounter_id": "e",
            "person_version": 1,
            "reason": "direct_confirmation",
        }
        for ms in (0, 200, 400, 600, 800)
    ]
    assert associate_turn(turn, timeline, final=True)["visitor_id"] == "anna"
    assert associate_turn(turn, timeline[:1], final=True)["status"] == "unattributed"
    changed = [{**t, "visitor_id": "bob" if t["ms"] >= 600 else "anna"} for t in timeline]
    assert associate_turn(turn, changed, final=True)["reason"] == "encounter_boundary"


async def test_worker_failure_can_retry_without_duplicate_facts(tmp_path, monkeypatch):
    settings, db, store = await make_store(tmp_path)
    person = await store.create_person()
    job, _ = await queue(store, person["id"])
    inject_audio(monkeypatch)
    worker = MemoryWorker(store, settings, None, verifier=Verifier())

    class Broken(Provider):
        async def verify(self, *args):
            raise TimeoutError("temporary provider issue")

    worker.providers = Broken(transcript(), lambda _, current: [claim(current[0])])
    await process(worker)
    assert await store.facts_for_person(person["id"]) == []
    async with db.transaction() as conn:
        await conn.execute("UPDATE jobs SET next_at=0 WHERE status='pending'", ())
    worker.providers = Provider(transcript(), lambda _, current: [claim(current[0])])
    await process(worker)
    assert worker.providers.transcription_calls == 0
    assert len(await store.facts_for_person(person["id"])) == 1
    async with db.transaction() as conn:
        result = await rows(conn, "SELECT status,attempts FROM jobs WHERE kind='learning'", ())
    assert result[0] == {"status": "done", "attempts": 2}
    await worker.close()
    await db.close()


async def test_relative_date_context_uses_deployment_timezone_not_host(tmp_path, monkeypatch):
    settings, db, store = await make_store(tmp_path)
    person = await store.create_person()
    _, payload = await queue(store, person["id"])
    async with db.transaction() as conn:
        await conn.execute(
            "UPDATE encounters SET started_at=? WHERE id=?",
            ("2026-10-26T19:00:00+00:00", payload["encounter"]),
        )
    inject_audio(monkeypatch)
    worker = MemoryWorker(store, settings, None, verifier=Verifier())
    provider = Provider(transcript("I will visit tomorrow."))
    worker.providers = provider
    await process(worker)
    assert provider.encounter_time == "2026-10-27T02:00:00+07:00"
    await worker.close()
    await db.close()


async def test_silence_finishes_without_sending_audio_to_provider(tmp_path, monkeypatch):
    settings, db, store = await make_store(tmp_path)
    person = await store.create_person()
    job_id, payload = await queue(store, person["id"])
    inject_audio(monkeypatch)
    monkeypatch.setattr("remind.audio.processing.has_speech", lambda pcm: False)

    class UnusedProvider(Provider):
        async def transcribe(self, pcm):
            pytest.fail("Silent audio must stay local")

    worker = MemoryWorker(store, settings, None, verifier=Verifier())
    worker.providers = UnusedProvider([])
    try:
        assert await process(worker)
        assert await worker.captures.pending_jobs() == []
        assert await store.recent_context(payload["encounter"]) == []
        assert await store.facts_for_person(person["id"]) == []
        metrics = await read_metrics(store)
        assert metrics[0]["job_id"] == job_id
        assert "transcription_ms" not in metrics[0]
    finally:
        await worker.close()
        await db.close()


async def test_unavailable_voice_model_keeps_summary_without_learning_facts(tmp_path, monkeypatch):
    settings, db, store = await make_store(tmp_path)
    person = await store.create_person()
    _, payload = await queue(store, person["id"])
    inject_audio(monkeypatch)

    class UnavailableVerifier:
        def classify(self, pcm, segments, profile):
            raise RuntimeError("Model unavailable")

    worker = MemoryWorker(store, settings, None, verifier=UnavailableVerifier())
    worker.providers = Provider(transcript(), lambda _, current: [claim(current[0])])
    try:
        assert await process(worker)
        assert await worker.captures.pending_jobs() == []
        assert await store.facts_for_person(person["id"]) == []
        assert (await store.recent_context(payload["encounter"]))[0]["role"] == "uncertain"
        assert (await store.get_encounter(payload["encounter"]))["summary"]
        assert "unavailable" in worker.speaker_status
    finally:
        await worker.close()
        await db.close()


async def test_forgetting_removes_recordings_and_retries_filesystem_failures(tmp_path, monkeypatch):
    settings, db, store = await make_store(tmp_path)
    person = await store.create_person()
    _, payload = await queue(store, person["id"])
    spool = tmp_path / "spool"
    spool.mkdir()
    recording = spool / "forgotten.webm"
    recording.write_bytes(b"private recording")
    async with db.transaction() as connection:
        await connection.execute(
            "UPDATE clips SET path=? WHERE id=?",
            (str(recording), payload["clip_id"]),
        )
    await store.forget_person(person["id"])
    worker = MemoryWorker(store, settings, None, verifier=Verifier())
    original_unlink = type(recording).unlink

    def fail_unlink(path, *args, **kwargs):
        if path == recording:
            raise PermissionError("Temporary file lock")
        return original_unlink(path, *args, **kwargs)

    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(type(recording), "unlink", fail_unlink)
            await worker.cleanup()
        assert recording.exists()
        assert await store.pending_cleanup() == [str(recording)]
        await worker.cleanup()
        assert not recording.exists()
        assert await store.pending_cleanup() == []
    finally:
        await worker.close()
        await db.close()


def test_transcription_tolerance_cannot_create_turns_past_the_recording_end():
    turns = [
        {"id": "normal", "start_ms": 0, "end_ms": 900, "text": "Hello"},
        {"id": "tail", "start_ms": 900, "end_ms": 1030, "text": "Goodbye"},
        {"id": "outside", "start_ms": 1010, "end_ms": 1040, "text": "Invalid"},
        {"id": "negative", "start_ms": -10, "end_ms": 100, "text": "Invalid"},
        {"id": "nan", "start_ms": float("nan"), "end_ms": 100, "text": "Invalid"},
    ]
    saved = transcript_segments(turns, "clip", duration_ms=1000)
    assert [turn["text"] for turn in saved] == ["Hello", "Goodbye"]
    assert saved[1]["end_ms"] == 1000
    assert len({turn["id"] for turn in saved}) == 2


def test_dialogue_budget_does_not_join_answers_to_questions_across_a_removed_turn():
    question = {"id": "old", "text": "Do you live in Da Nang?"}
    long_turn = {"id": "middle", "text": "x" * 25000}
    answer = {"id": "new", "text": "Yes."}
    assert bounded_dialogue([question, long_turn, answer]) == [answer]
    assert bounded_dialogue([long_turn]) == []


async def test_worker_transcribes_without_any_face_or_encounter(tmp_path, monkeypatch):
    import json

    settings, db, store = await make_store(tmp_path)
    inject_audio(monkeypatch)
    captures = CaptureStore(store)
    voice = await store.voice_status()
    receipt = await captures.receive_clip(
        "no-face", "clip", 0, 2000, "injected.wav", [], voice["version"]
    )
    worker = MemoryWorker(store, settings, None, verifier=Verifier())
    provider = Provider(transcript("I am James."))
    worker.providers = provider
    try:
        await process(worker)
        assert provider.transcription_calls == 1
        assert provider.received == []
        assert (await captures.receipt(receipt["clip_id"]))[
            "status"
        ] == "completed_without_attribution"
        async with db.transaction() as connection:
            turn = json.loads((await rows(connection, "SELECT data FROM transcripts"))[0]["data"])
        assert turn["text"] == "I am James."
        assert turn["role"] == "visitor"
        assert turn["association"]["status"] == "unattributed"
        assert await store.list_people() == []
    finally:
        await worker.close()
        await db.close()


async def test_attribution_wait_does_not_include_audio_or_learning_queue_time(
    tmp_path, monkeypatch
):
    settings, db, store = await make_store(tmp_path)
    person = await store.create_person()
    clock = [1000]
    monkeypatch.setattr("remind.memory.capture.milliseconds", lambda: clock[0])
    await queue(store, person["id"])
    inject_audio(monkeypatch)
    worker = MemoryWorker(store, settings, None, verifier=Verifier())
    worker.providers = Provider(transcript())
    try:
        clock[0] = 4000
        assert await worker.run_once()  # Audio completes after three seconds.
        clock[0] = 15000
        assert await worker.run_once()  # Learning is claimed much later.
        measured = (await read_metrics(store))[0]
        assert measured["attribution_wait_ms"] == 0
        assert measured["receipt_to_audio_ms"] == 3000
        assert measured["commit_ms"] >= 0
    finally:
        await worker.close()
        await db.close()
