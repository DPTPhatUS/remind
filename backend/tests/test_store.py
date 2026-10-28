import pytest

from remind.memory.capture import CaptureStore
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
    captures = CaptureStore(store)
    if capture_start is None:
        context = await store.recent_context(encounter)
        capture_start = max((s.get("end_ms", 0) for s in context), default=-1000) + 1000
    turns = [
        {
            "id": str(i),
            "text": f"I said {fact['value']}.",
            "role": "visitor",
            "start_ms": capture_start + i * 1000,
            "end_ms": capture_start + i * 1000 + 900,
        }
        for i, fact in enumerate(claims)
    ]
    job = await captures.receive_transcript_batch(
        encounter, uid(), capture_start, capture_start + max(1, len(claims)) * 1000, turns
    )
    segments = await captures.learning_segments(job)
    for fact, segment in zip(claims, segments, strict=True):
        fact["evidence"] = [{"segment_id": segment["id"], "quote": segment["text"]}]
    assert await captures.finish_learning(
        job, {"facts": claims, "segments": segments, "metrics": {}}
    )
    return await store.facts_for_person(person["id"])


async def test_correction_and_forget_invalidate_old_jobs(store):
    person = await store.create_person(name="Anna")
    corrected = await store.correct_person(person["id"], {"name": "Anne"}, version=1)
    assert corrected["version"] == 2
    with pytest.raises(ValueError, match="changed"):
        await store.correct_person(person["id"], {"name": "Wrong"}, version=1)
    await store.forget_person(person["id"])
    assert await store.get_person(person["id"]) is None
    assert await store.list_people() == []


async def test_facts_accumulate_and_repeat_sources_without_duplicate_claims(store):
    p = await store.create_person()
    e = await store.start_encounter("s", p["id"], 0)
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
    e = await store.start_encounter("s", p["id"], 0)
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
    e = await store.start_encounter("s", p["id"], 0)
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
    e = await store.start_encounter("s", p["id"], 0)
    await commit_claims(store, p, e, [claim("teacher", "occupation", "work")])
    facts = await commit_claims(store, p, e, [claim("nurse", "occupation", "work")])
    conflict = next(f for f in facts if f["status"] == "conflict")
    memory = await store.correct_fact(p["id"], conflict["id"], "doctor", 1)
    assert [f["value"] for f in memory["facts"] if f["status"] == "accepted"] == ["doctor"]


async def test_dismissing_old_identity_does_not_clear_new_manual_name(store):
    p = await store.create_person()
    e = await store.start_encounter("s", p["id"], 0)
    original = (await commit_claims(store, p, e, [claim("Anna", "name", "identity")]))[0]
    await store.correct_person(p["id"], {"name": "Anne"}, 1)
    await store.dismiss_fact(p["id"], original["id"], 2)
    assert (await store.get_person(p["id"]))["name"] == "Anne"


async def test_related_people_past_and_planned_facts_are_not_current_visitor_highlights(store):
    p = await store.create_person()
    e = await store.start_encounter("s", p["id"], 0)
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
    e = await store.start_encounter("s", p["id"], 0)
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
    e = await store.start_encounter("s", p["id"], 0)
    original = (await commit_claims(store, p, e, [claim("gardening")]))[0]
    await store.correct_fact(p["id"], original["id"], "growing orchids", 1)
    facts = await commit_claims(store, p, e, [claim("cooking")])
    assert next(f for f in facts if f["value"] == "cooking")["status"] == "accepted"


async def test_dismissed_identity_is_cleared_and_manual_identity_has_priority(store):
    p = await store.create_person()
    e = await store.start_encounter("s", p["id"], 0)
    fact = (await commit_claims(store, p, e, [claim("Anna", "name", "identity")]))[0]
    assert (await store.get_person(p["id"]))["name"] == "Anna"
    await store.dismiss_fact(p["id"], fact["id"], 1)
    assert (await store.get_person(p["id"]))["name"] is None
    await store.correct_person(p["id"], {"name": "Anne"}, 2)
    facts = await commit_claims(store, p, e, [claim("Annabel", "name", "identity")])
    assert next(f for f in facts if f["value"] == "Annabel")["status"] == "conflict"
    assert (await store.get_person(p["id"]))["name"] == "Anne"


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


async def test_capture_visitor_controls_fact_owner_and_targets_cannot_cross_subjects(store):
    p, other = await store.create_person(), await store.create_person()
    e = await store.start_encounter("s", p["id"], 0)
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
    e = await store.start_encounter("s", p["id"], 0)
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
    old = await store.start_encounter("old-browser", p["id"], 0)
    new = await store.start_encounter("new-browser", p["id"], 0)
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
    newer = await store.start_encounter("third-browser", p["id"], 0)
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
    e = await store.start_encounter("s", p["id"], 0)
    await commit_claims(store, p, e, [claim("gardening")], capture_start=0)
    await commit_claims(store, p, e, [claim("cooking")], capture_start=2000)
    assert await store.recent_context(e, before_ms=500) == []
    context = await store.recent_context(e, limit=1, before_ms=2000)
    assert len(context) == 1 and context[0]["start_ms"] == 0
    assert len(await store.recent_context(e)) == 2


async def test_dismissal_and_manual_correction_suppression_ignore_date_enrichment(store):
    p = await store.create_person()
    e = await store.start_encounter("s", p["id"], 0)
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
    encounter = await store.start_encounter("qualifications", person["id"], 0)
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
