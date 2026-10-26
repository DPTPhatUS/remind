import pytest

from remind.database import Database, rows
from remind.memory.store import MemoryStore, uid


def claim(value, predicate="interest", category="interests", **fields):
    return {
        "subject": "visitor",
        "category": category,
        "predicate": predicate,
        "value": value,
        "temporal_status": "current",
        "operation": "add",
        "valid_from": None,
        "valid_to": None,
        "target_fact_id": None,
        **fields,
    }


async def commit_claims(store, person, encounter, claims, capture_start=None):
    if await store.voice_profile() is None:
        await store.set_voice_profile([[1, 0], [0.99, 0.01]], "test-voice")
    current = await store.get_person(person["id"])
    voice = await store.voice_status()
    if capture_start is None:
        context = await store.recent_context(encounter)
        capture_start = max((s.get("end_ms", 0) for s in context), default=-1000) + 1000
    job_id = await store.enqueue_job(
        encounter,
        uid(),
        {
            "visitor_id": person["id"],
            "versions": {person["id"]: current["version"]},
            "voice_version": voice["version"],
            "start_ms": capture_start,
            "end_ms": capture_start + max(1, len(claims)) * 1000,
        },
    )
    job = await store.claim_job("worker", 0)
    assert job["id"] == job_id
    segments = []
    for index, fact in enumerate(claims):
        segment_id = f"{job_id}:{index}"
        text = f"I said {fact['value']}."
        segments.append(
            {
                "id": segment_id,
                "text": text,
                "role": "visitor",
                "start_ms": capture_start + index * 1000,
                "end_ms": capture_start + index * 1000 + 900,
            }
        )
        fact["evidence"] = [{"segment_id": segment_id, "quote": text}]
    assert await store.finish_job(
        job_id, job["lease_token"], {"facts": claims, "segments": segments}
    )
    return await store.facts_for_person(person["id"])


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
    a = await store.enqueue_job(encounter, "window-1", {"clip_path": "one.wav"})
    b = await store.enqueue_job(encounter, "window-1", {"clip_path": "one.wav"})
    assert a == b
    assert len(await store.pending_jobs()) == 1


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
    path = tmp_path / "persistent.db"
    db = Database(path)
    await db.create_schema()
    store = MemoryStore(db)
    p = await store.create_person(name="Anna")
    encounter = await store.start_encounter("old")
    await store.add_participant(encounter, p["id"], "a", 0)
    await store.close_encounter(encounter, "Sunday lunch")
    await db.close()
    db = Database(path)
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
    await commit_claims(store, other, e, [claim("visits Anna", "routine", "routines")])
    assert "visits Anna" in (await store.get_person(other["id"]))["profile_summary"]
    await store.forget_person(first["id"])
    assert (await store.get_person(other["id"]))["profile_summary"] == ""
    assert await store.facts_for_person(other["id"]) == []
    assert await store.recent_context(e) == []


async def test_only_current_worker_can_renew_lease(store):
    e = await store.start_encounter("s")
    ident = await store.enqueue_job(e, "window", {})
    old = await store.claim_job("one", 0)
    current = await store.claim_job("two", 200000)
    assert not await store.renew_lease(ident, old["lease_token"], 210000)
    assert await store.renew_lease(ident, current["lease_token"], 210000)
    assert await store.claim_job("three", 380001) is None


async def test_facts_accumulate_and_repeat_sources_without_duplicate_claims(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    await commit_claims(store, p, e, [claim("gardening"), claim("cooking")])
    facts = await commit_claims(store, p, e, [claim("Gardening")])
    assert len(facts) == 2
    gardening = next(f for f in facts if f["value"] == "gardening")
    assert len(gardening["evidence"]) == 2
    person = await store.get_person(p["id"])
    assert len(person["highlights"]) == 2
    assert "gardening" in person["profile_summary"]


async def test_explicit_changes_preserve_history_and_contradictions_remain_unresolved(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    original = (await commit_claims(store, p, e, [claim("teacher", "occupation", "work")]))[0]
    facts = await commit_claims(store, p, e, [claim("nurse", "occupation", "work")])
    assert next(f for f in facts if f["value"] == "nurse")["status"] == "conflict"
    facts = await commit_claims(
        store,
        p,
        e,
        [
            claim(
                "doctor",
                "occupation",
                "work",
                operation="change",
                target_fact_id=original["id"],
                valid_from="2026-10-01",
            )
        ],
    )
    old = next(f for f in facts if f["value"] == "teacher")
    assert (old["status"], old["temporal_status"], old["valid_to"]) == (
        "superseded",
        "past",
        "2026-10-01",
    )
    person = await store.get_person(p["id"])
    assert "doctor" in person["profile_summary"]
    assert "teacher" not in person["profile_summary"]
    assert "nurse" not in person["profile_summary"]


async def test_explicit_correction_can_resolve_an_existing_conflict(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    original = (await commit_claims(store, p, e, [claim("teacher", "occupation", "work")]))[0]
    await commit_claims(store, p, e, [claim("nurse", "occupation", "work")])
    facts = await commit_claims(
        store,
        p,
        e,
        [
            claim(
                "nurse",
                "occupation",
                "work",
                operation="correct",
                target_fact_id=original["id"],
            )
        ],
    )
    assert len(facts) == 2
    assert next(f for f in facts if f["value"] == "teacher")["status"] == "superseded"
    nurse = next(f for f in facts if f["value"] == "nurse")
    assert nurse["status"] == "accepted" and len(nurse["evidence"]) == 2


async def test_manually_correcting_conflict_replaces_current_single_value(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    await commit_claims(store, p, e, [claim("teacher", "occupation", "work")])
    facts = await commit_claims(store, p, e, [claim("nurse", "occupation", "work")])
    conflict = next(f for f in facts if f["status"] == "conflict")
    memory = await store.correct_fact(p["id"], conflict["id"], "doctor", 1)
    assert [f["value"] for f in memory["facts"] if f["status"] == "accepted"] == ["doctor"]


async def test_dismissing_old_identity_does_not_clear_new_manual_name(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    original = (await commit_claims(store, p, e, [claim("Anna", "name", "identity")]))[0]
    await store.correct_person(p["id"], {"name": "Anne"}, 1)
    await store.dismiss_fact(p["id"], original["id"], 2)
    assert (await store.get_person(p["id"]))["name"] == "Anne"


async def test_related_people_past_and_planned_facts_are_not_current_visitor_highlights(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    facts = await commit_claims(
        store,
        p,
        e,
        [
            claim("teacher", "occupation", "work", subject="brother"),
            claim("banker", "occupation", "work", temporal_status="past"),
            claim(
                "visit tomorrow",
                "visit",
                "plans",
                temporal_status="planned",
                valid_from="2026-10-27",
            ),
        ],
    )
    assert len(facts) == 3
    assert (await store.get_person(p["id"]))["highlights"] == []
    assert (await store.get_person(p["id"]))["profile_summary"] == ""


async def test_manual_fact_correction_prevents_overwrite_and_dismissal_prevents_relearning(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    original = (await commit_claims(store, p, e, [claim("teacher", "occupation", "work")]))[0]
    memory = await store.correct_fact(p["id"], original["id"], "nurse", 1)
    corrected = next(f for f in memory["facts"] if f["status"] == "accepted")
    assert corrected["manual"]
    facts = await commit_claims(
        store,
        p,
        e,
        [
            claim(
                "doctor",
                "occupation",
                "work",
                operation="change",
                target_fact_id=corrected["id"],
            )
        ],
    )
    assert next(f for f in facts if f["value"] == "doctor")["status"] == "conflict"
    memory = await store.dismiss_fact(p["id"], corrected["id"], memory["version"])
    assert memory["highlights"] == []
    facts = await commit_claims(store, p, e, [claim("nurse", "occupation", "work")])
    assert len([f for f in facts if f["value"] == "nurse"]) == 1
    assert not any(f["status"] == "accepted" for f in facts)


async def test_manual_additive_fact_allows_other_compatible_interests(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    original = (await commit_claims(store, p, e, [claim("gardening")]))[0]
    await store.correct_fact(p["id"], original["id"], "growing orchids", 1)
    facts = await commit_claims(store, p, e, [claim("cooking")])
    assert next(f for f in facts if f["value"] == "cooking")["status"] == "accepted"


async def test_dismissed_identity_is_cleared_and_manual_identity_has_priority(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    fact = (await commit_claims(store, p, e, [claim("Anna", "name", "identity")]))[0]
    assert (await store.get_person(p["id"]))["name"] == "Anna"
    await store.dismiss_fact(p["id"], fact["id"], 1)
    assert (await store.get_person(p["id"]))["name"] is None
    await store.correct_person(p["id"], {"name": "Anne"}, 2)
    facts = await commit_claims(store, p, e, [claim("Annabel", "name", "identity")])
    assert next(f for f in facts if f["value"] == "Annabel")["status"] == "conflict"
    assert (await store.get_person(p["id"]))["name"] == "Anne"


@pytest.mark.parametrize("action", ["replace", "delete"])
async def test_voice_reference_changes_cancel_pending_role_dependent_writes(store, action):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    await store.set_voice_profile([[1, 0]], "test")
    job_id = await store.enqueue_job(
        e,
        "window",
        {
            "visitor_id": p["id"],
            "versions": {p["id"]: 1},
            "voice_version": 1,
        },
    )
    job = await store.claim_job("w", 0)
    if action == "replace":
        await store.set_voice_profile([[0, 1]], "test")
    else:
        await store.delete_voice_profile()
    assert not await store.finish_job(job_id, job["lease_token"], {"summary": "stale"})
    assert (await store.voice_status())["version"] == 2
    async with store.db.transaction() as db:
        assert (await rows(db, "SELECT status FROM jobs WHERE id=?", (job_id,)))[0][
            "status"
        ] == "cancelled"


async def test_voice_profile_is_persistent_and_deletion_keeps_monotonic_version(store):
    status = await store.set_voice_profile([[2, 0], [1, 1]], "test")
    assert status["ready"] and status["sample_count"] == 2
    assert (await MemoryStore(store.db).voice_profile())["embeddings"][0] == [1, 0]
    assert (await store.delete_voice_profile())["version"] == 2
    assert await store.voice_profile() is None
    assert (await store.set_voice_profile([[0, 1]], "test"))["version"] == 3
    for bad in ([], [[0, 0]], [[float("nan"), 1]]):
        with pytest.raises(ValueError, match="Invalid"):
            await store.set_voice_profile(bad, "test")


async def test_evidence_must_exist_and_include_visitor_support_but_can_include_user_context(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    await store.set_voice_profile([[1, 0]], "test")
    job_id = await store.enqueue_job(
        e,
        "w",
        {
            "visitor_id": p["id"],
            "versions": {p["id"]: 1},
            "voice_version": 1,
        },
    )
    job = await store.claim_job("w", 0)
    segments = [
        {"id": "question", "text": "Do you teach?", "role": "user", "start_ms": 0},
        {"id": "answer", "text": "Yes, I do.", "role": "visitor", "start_ms": 1000},
    ]
    facts = [
        claim(
            "teacher",
            "occupation",
            "work",
            evidence=[
                {"segment_id": "question", "quote": "Do you teach?"},
                {"segment_id": "answer", "quote": "Yes, I do."},
            ],
        ),
        claim(
            "nurse",
            "occupation",
            "work",
            evidence=[
                {"segment_id": "question", "quote": "Do you teach?"},
            ],
        ),
        claim(
            "doctor",
            "occupation",
            "work",
            evidence=[
                {"segment_id": "answer", "quote": "invented quote"},
            ],
        ),
    ]
    assert await store.finish_job(
        job_id, job["lease_token"], {"facts": facts, "segments": segments}
    )
    assert [f["value"] for f in await store.facts_for_person(p["id"])] == ["teacher"]


async def test_cross_clip_context_order_idempotency_and_metrics(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    await commit_claims(store, p, e, [claim("gardening"), claim("cooking")])
    context = await store.recent_context(e, limit=1)
    assert len(context) == 1 and context[0]["start_ms"] == 1000
    job_id = await store.enqueue_job(e, "next", {})
    job = await store.claim_job("w", 0)
    result = {
        "segments": [{"id": "last", "role": "uncertain", "text": "Hello", "start_ms": 2000}],
        "metrics": {"processing_ms": 25, "accepted_facts": 0},
    }
    assert await store.finish_job(job_id, job["lease_token"], result)
    assert not await store.finish_job(job_id, job["lease_token"], result)
    assert len(await store.recent_context(e)) == 3
    assert (await store.processing_metrics())[0]["processing_ms"] == 25


async def test_jobs_are_sequential_per_encounter_but_other_encounters_can_progress(store):
    first, other = await store.start_encounter("s"), await store.start_encounter("s")
    a = await store.enqueue_job(first, "a", {})
    b = await store.enqueue_job(first, "b", {})
    c = await store.enqueue_job(other, "c", {})
    first_job = await store.claim_job("w", 0)
    assert first_job["id"] == a
    second_job = await store.claim_job("v", 0)
    assert second_job["id"] == c
    assert await store.claim_job("x", 0) is None
    assert await store.finish_job(a, first_job["lease_token"], {})
    assert (await store.claim_job("w", 1))["id"] == b


async def test_capture_visitor_controls_fact_owner_and_targets_cannot_cross_subjects(store):
    p, other = await store.create_person(), await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    original = (
        await commit_claims(
            store, p, e, [claim("teacher", "occupation", "work", subject="brother")]
        )
    )[0]
    facts = await commit_claims(
        store,
        p,
        e,
        [
            claim(
                "nurse",
                "occupation",
                "work",
                person_id=other["id"],
                operation="change",
                target_fact_id=original["id"],
            )
        ],
    )
    assert len(facts) == 1
    await commit_claims(store, p, e, [claim("gardening", person_id=other["id"])])
    assert await store.facts_for_person(other["id"]) == []
    assert len(await store.facts_for_person(p["id"])) == 2


async def test_late_older_change_cannot_reverse_newer_state(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    original = (
        await commit_claims(
            store,
            p,
            e,
            [claim("doctor", "occupation", "work")],
            capture_start=10000,
        )
    )[0]
    facts = await commit_claims(
        store,
        p,
        e,
        [
            claim(
                "banker",
                "occupation",
                "work",
                operation="change",
                target_fact_id=original["id"],
            )
        ],
        capture_start=3000,
    )
    assert next(f for f in facts if f["value"] == "doctor")["status"] == "accepted"
    assert next(f for f in facts if f["value"] == "banker")["status"] == "conflict"
    assert "doctor" in (await store.get_person(p["id"]))["profile_summary"]


async def test_cross_encounter_observation_order_survives_monotonic_clock_reset(store):
    p = await store.create_person()
    old = await store.start_encounter("old-browser")
    new = await store.start_encounter("new-browser")
    for encounter in (old, new):
        await store.add_participant(encounter, p["id"], "a", 0)
    async with store.db.transaction() as db:
        await db.execute(
            "UPDATE encounters SET started_at=? WHERE id=?", ("2026-10-25T00:00:00+00:00", old)
        )
        await db.execute(
            "UPDATE encounters SET started_at=? WHERE id=?", ("2026-10-26T00:00:00+00:00", new)
        )
    original = (
        await commit_claims(store, p, new, [claim("doctor", "occupation", "work")], capture_start=0)
    )[0]
    facts = await commit_claims(
        store,
        p,
        old,
        [
            claim(
                "banker",
                "occupation",
                "work",
                operation="change",
                target_fact_id=original["id"],
            )
        ],
        capture_start=1000000,
    )
    assert next(f for f in facts if f["value"] == "doctor")["status"] == "accepted"
    assert next(f for f in facts if f["value"] == "banker")["status"] == "conflict"
    newer = await store.start_encounter("third-browser")
    await store.add_participant(newer, p["id"], "b", 0)
    facts = await commit_claims(
        store,
        p,
        newer,
        [
            claim(
                "nurse",
                "occupation",
                "work",
                operation="change",
                target_fact_id=original["id"],
            )
        ],
        capture_start=0,
    )
    assert next(f for f in facts if f["value"] == "nurse")["status"] == "accepted"
    assert next(f for f in facts if f["value"] == "doctor")["status"] == "superseded"


async def test_context_filter_excludes_future_and_overlapping_turns_before_limiting(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    await commit_claims(store, p, e, [claim("gardening")], capture_start=0)
    await commit_claims(store, p, e, [claim("cooking")], capture_start=2000)
    assert await store.recent_context(e, before_ms=500) == []
    context = await store.recent_context(e, limit=1, before_ms=2000)
    assert len(context) == 1 and context[0]["start_ms"] == 0
    assert len(await store.recent_context(e)) == 2


async def test_dismissal_and_manual_correction_suppression_ignore_date_enrichment(store):
    p = await store.create_person()
    e = await store.start_encounter("s")
    await store.add_participant(e, p["id"], "a", 0)
    facts = await commit_claims(store, p, e, [claim("gardening"), claim("cooking")])
    gardening = next(f for f in facts if f["value"] == "gardening")
    cooking = next(f for f in facts if f["value"] == "cooking")
    await store.dismiss_fact(p["id"], gardening["id"], 1)
    await store.correct_fact(p["id"], cooking["id"], "baking", 2)
    facts = await commit_claims(
        store,
        p,
        e,
        [
            claim("gardening", valid_from="2026-10-26"),
            claim("cooking", temporal_status="past", valid_to="2026-10-26"),
        ],
    )
    assert len(facts) == 3
    assert [f["value"] for f in facts if f["status"] == "accepted"] == ["baking"]


async def test_compatible_qualifications_and_work_roles_accumulate(store):
    person = await store.create_person()
    encounter = await store.start_encounter("qualifications")
    await store.add_participant(encounter, person["id"], "visitor", 0)
    await commit_claims(
        store,
        person,
        encounter,
        [claim("BSc biology", "degree", "education"), claim("teacher", "work_role", "work")],
    )
    facts = await commit_claims(
        store,
        person,
        encounter,
        [claim("MSc chemistry", "degree", "education"), claim("coach", "work_role", "work")],
    )
    assert len(facts) == 4
    assert all(fact["status"] == "accepted" for fact in facts)
