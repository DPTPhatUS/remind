import pytest

from remind.database import Database
from remind.memory.store import MemoryStore


async def test_person_and_new_encounters_survive_store_reload(store):
    person = await store.create_person(name="Anna", relationship="daughter")
    first = await store.start_encounter("generation-1")
    await store.add_participant(first, person["id"], "track-1", 0)
    await store.close_encounter(first, "Talked about Sunday's lunch")
    second = await store.start_encounter("generation-2")
    await store.add_participant(second, person["id"], "track-2", 0)
    reloaded = MemoryStore(store.db)
    memory = await reloaded.person_memory(person["id"], exclude_encounter_id=second)
    assert memory["name"] == "Anna"
    assert memory["last_encounter"]["id"] == first
    assert memory["last_encounter"]["summary"] == "Talked about Sunday's lunch"


async def test_same_job_key_creates_only_one_job(store):
    encounter = await store.start_encounter("generation-1")
    a = await store.enqueue_job(encounter, "window-1", {"audio_path": "one.wav"})
    b = await store.enqueue_job(encounter, "window-1", {"audio_path": "one.wav"})
    assert a == b
    assert len(await store.pending_jobs()) == 1


async def test_single_patient_is_reused(store):
    assert (await store.ensure_patient())["id"] == 1
    assert (await store.ensure_patient())["id"] == 1


async def test_correction_and_forget_invalidate_old_jobs(store):
    person = await store.create_person(name="Anna")
    corrected = await store.correct_person(person["id"], {"name": "Anne"}, version=1)
    assert corrected["version"] == 2
    with pytest.raises(ValueError, match="changed"):
        await store.correct_person(person["id"], {"name": "Wrong"}, version=1)
    await store.forget_person(person["id"])
    assert await store.get_person(person["id"]) is None
    assert await store.list_people() == []


async def test_actual_database_reopen(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'persistent.db'}"
    db = Database(url)
    await db.create_schema()
    store = MemoryStore(db)
    p = await store.create_person(name="Anna")
    encounter = await store.start_encounter("old")
    await store.add_participant(encounter, p["id"], "a", 0)
    await store.close_encounter(encounter, "Sunday lunch")
    await db.close()
    db = Database(url)
    await db.create_schema()
    memory = await MemoryStore(db).person_memory(p["id"])
    assert memory["last_encounter"]["summary"] == "Sunday lunch"
    await db.close()


async def test_leases_and_forgetting_reject_delayed_work(store):
    p = await store.create_person(name="Anna")
    encounter = await store.start_encounter("one")
    await store.add_participant(encounter, p["id"], "a", 0)
    job_id = await store.enqueue_job(encounter, "window", {"versions": {p["id"]: 1}})
    job = await store.claim_job("worker", 1000)
    assert job["id"] == job_id
    assert await store.claim_job("other", 1001) is None
    recovered = await store.claim_job("other", 1000000)
    assert recovered["lease_token"] != job["lease_token"]
    assert not await store.finish_job(job_id, job["lease_token"], {"summary": "stale", "facts": []})
    await store.forget_person(p["id"])
    assert not await store.finish_job(
        job_id, recovered["lease_token"], {"summary": "Anna visited", "facts": []}
    )
    assert await store.get_person(p["id"]) is None


async def test_concurrent_job_deduplication(store):
    import asyncio

    encounter = await store.start_encounter("one")
    ids = await asyncio.gather(*(store.enqueue_job(encounter, "same", {}) for _ in range(10)))
    assert len(set(ids)) == 1


async def test_correction_prevents_delayed_fact_overwrite(store):
    p = await store.create_person(name="Anna")
    encounter = await store.start_encounter("one")
    await store.add_participant(encounter, p["id"], "a", 0)
    ident = await store.enqueue_job(encounter, "window", {"versions": {p["id"]: 1}})
    job = await store.claim_job("worker", 1000)
    await store.correct_person(p["id"], {"name": "Anne"}, 1)
    assert not await store.finish_job(ident, job["lease_token"], {"summary": "old", "facts": []})
    assert (await store.get_person(p["id"]))["name"] == "Anne"


async def test_exhausted_crashed_lease_becomes_failed(store):
    e = await store.start_encounter("one")
    await store.enqueue_job(e, "a", {})
    for time in (0, 200000, 400000):
        assert await store.claim_job("worker", time)
    assert await store.claim_job("worker", 600000) is None
    assert (await store.pending_jobs())[0]["status"] == "failed"


async def test_forget_rejects_late_shared_encounter_upload(store):

    first = await store.create_person()
    other = await store.create_person()
    encounter = await store.start_encounter("s")
    await store.add_participant(encounter, first["id"], "a", 0)
    await store.add_participant(encounter, other["id"], "b", 0)
    await store.forget_person(first["id"])
    with pytest.raises(ValueError, match="forgotten"):
        await store.enqueue_job(encounter, "late", {"versions": {other["id"]: 1}})


async def test_failed_job_can_be_retried_but_cancelled_cannot(store):
    e = await store.start_encounter("s")
    ident = await store.enqueue_job(e, "window", {"versions": {}})
    for stamp in (0, 10000, 20000):
        job = await store.claim_job("w", stamp)
        await store.fail_job(ident, job["lease_token"], "temporary", stamp)
    assert await store.retry_job(ident)
    assert (await store.claim_job("w", 30000))["id"] == ident
    assert not await store.retry_job(ident)


async def test_forgetting_removes_shared_derived_profile_text(store):
    first, other = await store.create_person(), await store.create_person()
    e = await store.start_encounter("s")
    for p in (first, other):
        await store.add_participant(e, p["id"], p["id"], 0)
    ident = await store.enqueue_job(e, "window", {"versions": {first["id"]: 1, other["id"]: 1}})
    job = await store.claim_job("w", 0)
    await store.finish_job(
        ident,
        job["lease_token"],
        {
            "facts": [
                {
                    "person_id": other["id"],
                    "predicate": "notes",
                    "value": "I visit Anna.",
                    "evidence": {},
                }
            ]
        },
    )
    await store.forget_person(first["id"])
    assert (await store.get_person(other["id"]))["notes"] is None


async def test_only_current_worker_can_renew_lease(store):
    e = await store.start_encounter("s")
    ident = await store.enqueue_job(e, "window", {})
    old = await store.claim_job("one", 0)
    current = await store.claim_job("two", 200000)
    assert not await store.renew_lease(ident, old["lease_token"], 210000)
    assert await store.renew_lease(ident, current["lease_token"], 210000)
    assert await store.claim_job("three", 380001) is None
