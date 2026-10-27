import sqlite3

import pytest

from remind.benchmark import conversation
from remind.benchmark.inputs import ConversationCase
from remind.config import Settings
from remind.database import Database
from remind.memory.store import MemoryStore


def claim(segment, predicate, value, category="other", **fields):
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
        "evidence": [{"segment_id": segment["id"], "quote": segment["text"]}],
        **fields,
    }


def make_case(turns, facts):
    batches = [
        {
            "id": f"batch-{i}",
            "start_ms": i * 2000,
            "end_ms": (i + 1) * 2000,
            "turns": [
                {
                    "id": f"turn-{i}",
                    "start_ms": i * 2000,
                    "end_ms": (i + 1) * 2000,
                    "role": role,
                    "text": text,
                }
            ],
        }
        for i, (role, text) in enumerate(turns)
    ]
    return ConversationCase.model_validate(
        {
            "id": "case",
            "encounters": [
                {"id": "meeting", "started_at": "2026-10-27T10:00:00+07:00", "batches": batches}
            ],
            "facts": facts,
        }
    )


class Provider:
    def __init__(self, propose):
        self.propose = propose
        self.seen = []

    async def extract(self, dialogue, summary, existing, date, current_ids):
        self.seen.append((dialogue, existing, date))
        return {
            "summary": "Conversation summary",
            "facts": self.propose(dialogue, existing, current_ids),
        }

    async def verify(self, facts, dialogue, existing):
        return {
            "assessments": [
                {"fact_index": i, "supported": True, "affirmative": True, "reason": "Fixture"}
                for i in range(len(facts))
            ]
        }

    async def close(self):
        pass


async def test_text_learning_accumulates_context_and_saves_without_voice(tmp_path, monkeypatch):
    case = make_case(
        [
            ("user", "What is your name?"),
            ("visitor", "Anna"),
            ("visitor", "I like gardening and music"),
            ("visitor", "I like gardening again"),
        ],
        [
            {"id": "name", "subject": "visitor", "predicate": "name", "value": "Anna"},
            {
                "id": "interest-1",
                "subject": "visitor",
                "predicate": "interest",
                "value": "gardening",
            },
            {"id": "interest-2", "subject": "visitor", "predicate": "interest", "value": "music"},
        ],
    )

    def propose(dialogue, existing, current_ids):
        current = next(s for s in dialogue if s["id"] in current_ids)
        if current["text"] == "Anna":
            assert dialogue[0]["text"] == "What is your name?"
            return [
                claim(
                    current,
                    "name",
                    "Anna",
                    "identity",
                    evidence=[{"segment_id": s["id"], "quote": s["text"]} for s in dialogue],
                )
            ]
        if "gardening" in current["text"]:
            return [
                claim(current, "interest", "gardening", "interests"),
                *(
                    [claim(current, "interest", "music", "interests")]
                    if "music" in current["text"]
                    else []
                ),
            ]
        return []

    provider = Provider(propose)
    monkeypatch.setattr(conversation, "Providers", lambda _: provider)
    result = await conversation.run_case(
        case, tmp_path, Settings(data_dir=tmp_path, openai_api_key="fixture")
    )
    assert result["status"] == "complete", result["errors"]
    outcome = result["outcomes"][0]
    assert outcome["scores"]["memory"]["fact_coverage"]["rate"] == 1
    assert len(outcome["facts"]) == 3
    gardening = next(f for f in outcome["facts"] if f["value"] == "gardening")
    assert len(gardening["evidence"]) == 2
    assert all(date == "2026-10-27T10:00:00+07:00" for _, _, date in provider.seen)
    with sqlite3.connect(tmp_path / "data.sqlite3") as db:
        assert db.execute("SELECT embeddings FROM user_voice").fetchone()[0] is None
        assert db.execute("SELECT count(*) FROM templates").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM jobs WHERE status='done'").fetchone()[0] == 4


@pytest.mark.parametrize(
    "unsafe", ["user_only", "fake_quote", "wrong_segment", "negation", "uncertain"]
)
async def test_invalid_evidence_does_not_become_a_saved_fact(tmp_path, monkeypatch, unsafe):
    role = "user" if unsafe == "user_only" else "uncertain" if unsafe == "uncertain" else "visitor"
    case = make_case(
        [(role, "I am not a teacher")],
        [
            {
                "id": "absence",
                "subject": "visitor",
                "predicate": "occupation",
                "value": "teacher",
                "present": False,
            }
        ],
    )

    def propose(dialogue, existing, current_ids):
        fact = claim(dialogue[-1], "occupation", "teacher", "work")
        if unsafe == "fake_quote":
            fact["evidence"][0]["quote"] = "I am a teacher"
        elif unsafe == "wrong_segment":
            fact["evidence"][0]["segment_id"] = "invented"
        elif unsafe == "negation":
            fact["polarity"] = "negative"
        return [fact]

    monkeypatch.setattr(conversation, "Providers", lambda _: Provider(propose))
    result = await conversation.run_case(
        case, tmp_path, Settings(data_dir=tmp_path, openai_api_key="fixture")
    )
    assert result["outcomes"][0]["facts"] == []
    assert result["outcomes"][0]["scores"]["memory"]["required_absence"]["rate"] == 1


async def test_provider_failure_keeps_expected_facts_in_coverage(tmp_path, monkeypatch):
    case = make_case(
        [("visitor", "I am Anna")],
        [{"id": "name", "subject": "visitor", "predicate": "name", "value": "Anna"}],
    )

    class Broken(Provider):
        async def extract(self, *args):
            raise TimeoutError("Provider unavailable")

    monkeypatch.setattr(conversation, "Providers", lambda _: Broken(None))
    result = await conversation.run_case(
        case, tmp_path, Settings(data_dir=tmp_path, openai_api_key="fixture")
    )
    assert result["status"] == "failed"
    assert result["outcomes"][0]["scores"]["memory"]["fact_coverage"]["rate"] == 0


async def test_text_benchmark_and_live_commits_preserve_the_same_history(tmp_path, monkeypatch):
    from remind.memory.learning import learn_conversation

    messages = [
        ("visitor", "I am 32"),
        ("visitor", "Correction, I am 33"),
        ("visitor", "I am a teacher"),
        ("visitor", "Now I am a nurse"),
        ("visitor", "My sister is a doctor"),
        ("visitor", "I plan to visit Paris"),
    ]
    expected = [
        {"id": "age", "subject": "visitor", "predicate": "age", "value": "33"},
        {
            "id": "old-age",
            "subject": "visitor",
            "predicate": "age",
            "value": "32",
            "status": "superseded",
        },
        {"id": "job", "subject": "visitor", "predicate": "occupation", "value": "nurse"},
        {
            "id": "old-job",
            "subject": "visitor",
            "predicate": "occupation",
            "value": "teacher",
            "status": "superseded",
            "temporal_status": "past",
        },
        {
            "id": "relative",
            "subject": "visitor.sister",
            "predicate": "occupation",
            "value": "doctor",
        },
        {
            "id": "plan",
            "subject": "visitor",
            "predicate": "travel",
            "value": "Paris",
            "temporal_status": "planned",
        },
    ]
    case = make_case(messages, expected)

    def propose(dialogue, existing, current_ids):
        current = next(s for s in dialogue if s["id"] in current_ids)
        text = current["text"]
        if text == "I am 32":
            return [claim(current, "age", "32", "age")]
        if text.startswith("Correction"):
            target = next(
                f for f in existing if f["predicate"] == "age" and f["status"] == "accepted"
            )
            return [
                claim(current, "age", "33", "age", operation="correct", target_fact_id=target["id"])
            ]
        if text == "I am a teacher":
            return [claim(current, "occupation", "teacher", "work")]
        if text.startswith("Now"):
            target = next(
                f for f in existing if f["predicate"] == "occupation" and f["status"] == "accepted"
            )
            return [
                claim(
                    current,
                    "occupation",
                    "nurse",
                    "work",
                    operation="change",
                    target_fact_id=target["id"],
                )
            ]
        if text.startswith("My sister"):
            return [claim(current, "occupation", "doctor", "work", subject="visitor.sister")]
        return [claim(current, "travel", "Paris", "plans", temporal_status="planned")]

    settings = Settings(data_dir=tmp_path, openai_api_key="fixture")
    text_dir = tmp_path / "text"
    text_dir.mkdir()
    monkeypatch.setattr(conversation, "Providers", lambda _: Provider(propose))
    benchmark = await conversation.run_case(case, text_dir, settings)
    assert benchmark["status"] == "complete", benchmark["errors"]
    text_facts = benchmark["outcomes"][0]["facts"]
    assert benchmark["outcomes"][0]["scores"]["memory"]["historical_state_coverage"]["rate"] == 1

    database = Database(tmp_path / "live.sqlite3")
    await database.create_schema()
    store = MemoryStore(database)
    try:
        # Live commit authorization is exercised with an ordinary unit-test reference.
        await store.set_voice_profile([[1.0, 0.0]], "unit-test")
        voice = await store.voice_status()
        person = await store.create_person()
        eid = await store.start_encounter("live-test")
        await store.add_participant(eid, person["id"], "track", 0)
        provider = Provider(propose)
        for batch in case.encounters[0].batches:
            job_id = await store.enqueue_job(
                eid,
                batch.id,
                {
                    "visitor_id": person["id"],
                    "versions": {person["id"]: person["version"]},
                    "voice_version": voice["version"],
                    "start_ms": batch.start_ms,
                    "end_ms": batch.end_ms,
                },
            )
            job = await store.claim_job("live-test", 0)
            segments = [
                {**t.model_dump(), "id": f"{job_id}:{t.id}", "speaker": t.role} for t in batch.turns
            ]
            learned = await learn_conversation(
                store,
                provider,
                settings,
                eid,
                person["id"],
                segments,
                batch.start_ms,
                can_learn=True,
            )
            assert await store.finish_job(job_id, job["lease_token"], learned)
        live_facts = await store.facts_for_person(person["id"])
    finally:
        await database.close()

    def comparable(facts):
        return sorted(
            (
                f["subject"],
                f["predicate"],
                f["value"],
                f["status"],
                f["temporal_status"],
                tuple(sorted(e["quote"] for e in f["evidence"])),
            )
            for f in facts
        )

    assert comparable(text_facts) == comparable(live_facts)
    assert not any(f["subject"] == "visitor" and f["value"] == "doctor" for f in text_facts)
