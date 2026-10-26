"""Fact consolidation and profile summaries, written within the caller's transaction."""

import json
import math
from datetime import UTC, datetime
from uuid import uuid4

import aiosqlite

from remind.database import Record, rows

IDENTITY_FIELDS = {"name", "relationship", "age", "notes"}
# Exclusivity belongs to the attribute, not its whole category: a visitor may
# have several degrees, qualifications, employers or concurrent work roles.
SINGLE_VALUE_PREDICATES = IDENTITY_FIELDS | {"occupation", "residence"}


def now() -> str:
    return datetime.now(UTC).isoformat()


def normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


async def load_facts(db: aiosqlite.Connection, ident: str) -> list[Record]:
    facts = await rows(
        db, "SELECT * FROM facts WHERE person_id=? ORDER BY created_at DESC,id", (ident,)
    )
    indexed = {fact["id"]: fact for fact in facts}
    for fact in facts:
        fact["manual"] = bool(fact["manual"])
        fact["evidence"] = []
    evidence = await rows(
        db,
        "SELECT ev.fact_id,ev.segment_id,ev.quote FROM fact_evidence ev "
        "JOIN facts f ON f.id=ev.fact_id WHERE f.person_id=? ORDER BY ev.rowid",
        (ident,),
    )
    for source in evidence:
        indexed[source["fact_id"]]["evidence"].append(
            {"segment_id": source["segment_id"], "quote": source["quote"]}
        )
    return facts


async def refresh_profile(db: aiosqlite.Connection, ident: str) -> None:
    found = await rows(db, "SELECT * FROM people WHERE id=?", (ident,))
    if not found:
        return
    person = found[0]
    manual = set(json.loads(person["manual"]))
    accepted = await rows(
        db,
        "SELECT * FROM facts WHERE person_id=? AND subject='visitor' AND status='accepted' "
        "AND temporal_status='current' ORDER BY manual DESC,created_at DESC,id",
        (ident,),
    )
    for field in IDENTITY_FIELDS - {"notes"}:
        if field in manual:
            continue
        candidates = [fact for fact in accepted if fact["predicate"] == field]
        person[field] = candidates[0]["value"] if candidates else None
        await db.execute(f"UPDATE people SET {field}=? WHERE id=?", (person[field], ident))
    highlights = []
    for fact in accepted:
        if fact["predicate"] in {"name", "relationship", "age"}:
            continue
        text = f"{fact['predicate'].replace('_', ' ').capitalize()}: {fact['value']}"
        if text not in highlights:
            highlights.append(text)
    identity = []
    if person["name"]:
        identity.append(person["name"])
    if person["relationship"]:
        identity.append(f"your {person['relationship']}")
    if person["age"]:
        identity.append(f"age {person['age']}")
    summary = ", ".join(identity)
    if highlights:
        summary = ". ".join(filter(None, [summary, *highlights[:6]]))
    await db.execute(
        "UPDATE people SET profile_summary=?,highlights=? WHERE id=?",
        (summary[:2000], json.dumps(highlights[:3]), ident),
    )


async def insert_fact(
    db: aiosqlite.Connection,
    person_id: str,
    encounter_id: str | None,
    job_id: str | None,
    fact: Record,
    status: str = "accepted",
    manual: bool = False,
) -> str:
    ident = str(uuid4())
    stamp = now()
    await db.execute(
        "INSERT INTO facts(id,person_id,encounter_id,job_id,subject,category,predicate,value,"
        "temporal_status,valid_from,valid_to,status,manual,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            person_id,
            encounter_id,
            job_id,
            fact["subject"],
            fact["category"],
            fact["predicate"],
            fact["value"],
            fact.get("temporal_status", "current"),
            fact.get("valid_from"),
            fact.get("valid_to"),
            status,
            int(manual),
            stamp,
            stamp,
        ),
    )
    return ident


async def save_claim(
    db: aiosqlite.Connection,
    person: Record,
    encounter_id: str,
    job_id: str,
    fact: Record,
    sources: dict[str, Record],
) -> None:
    required = ("subject", "category", "predicate", "value")
    if any(not isinstance(fact.get(key), str) or not fact[key].strip() for key in required):
        return
    if fact.get("temporal_status", "current") not in {"current", "past", "planned"}:
        return
    evidence = fact.get("evidence", [])
    if not isinstance(evidence, list) or not evidence:
        return
    validated = []
    for source in evidence:
        if not isinstance(source, dict):
            return
        segment_id = source.get("segment_id")
        if not isinstance(segment_id, str):
            return
        segment = sources.get(segment_id)
        quote = source.get("quote")
        if (
            not segment
            or not isinstance(quote, str)
            or not quote.strip()
            or quote not in segment.get("text", "")
            or segment.get("role") not in {"user", "visitor"}
        ):
            return
        validated.append({"segment_id": source["segment_id"], "quote": quote})
    if not any(sources[source["segment_id"]].get("role") == "visitor" for source in validated):
        return
    operation = fact.get("operation", "add")
    if operation not in {"add", "correct", "change"}:
        return
    all_facts = await rows(
        db,
        "SELECT * FROM facts WHERE person_id=? AND subject=? AND predicate=?",
        (person["id"], fact["subject"], fact["predicate"]),
    )
    # A manual removal/correction suppresses the removed claim even if a
    # later extraction adds dates or changes its temporal classification.
    if any(
        old["manual"]
        and old["status"] in {"dismissed", "superseded"}
        and normalized(old["value"]) == normalized(fact["value"])
        for old in all_facts
    ):
        return
    matching = next(
        (
            old
            for old in all_facts
            if normalized(old["value"]) == normalized(fact["value"])
            and old["temporal_status"] == fact.get("temporal_status", "current")
            and old["valid_from"] == fact.get("valid_from")
            and old["valid_to"] == fact.get("valid_to")
        ),
        None,
    )
    if matching and (
        matching["status"] == "dismissed"
        or (matching["status"] == "superseded" and (matching["manual"] or operation == "add"))
    ):
        return
    current = [
        old
        for old in all_facts
        if old["status"] == "accepted" and old["temporal_status"] == "current"
    ]
    target_id = fact.get("target_fact_id")
    target = next(
        (old for old in all_facts if old["id"] == target_id and old["status"] == "accepted"),
        None,
    )
    if operation in {"correct", "change"} and not target:
        return
    if (
        operation == "change"
        and target is not None
        and (
            target["temporal_status"] != "current"
            or fact.get("temporal_status", "current") != "current"
        )
    ):
        return
    manual_field = fact["subject"] == "visitor" and fact["predicate"] in json.loads(
        person["manual"]
    )
    singleton = fact["predicate"] in SINGLE_VALUE_PREDICATES
    protected = manual_field or (singleton and any(old["manual"] for old in current))
    conflict = protected or (
        singleton and bool(current) and fact.get("temporal_status", "current") == "current"
    )
    if operation in {"correct", "change"} and target is not None:
        if target["manual"] or manual_field:
            conflict = True
        elif matching and matching["id"] == target_id:
            conflict = False
        elif not await newer_than_target(db, encounter_id, validated, sources, target["id"]):
            # Upload order is independent of observation order. Keep late
            # evidence without allowing it to reverse a newer current state.
            conflict = True
        else:
            await db.execute(
                "UPDATE facts SET status='superseded',temporal_status=CASE WHEN ?='change' "
                "THEN 'past' ELSE temporal_status END,valid_to=COALESCE(?,valid_to),"
                "updated_at=? WHERE id=?",
                (operation, fact.get("valid_from"), now(), target_id),
            )
            conflict = False
    if matching and matching["status"] != "superseded":
        fact_id = matching["id"]
        status = matching["status"]
        if operation in {"correct", "change"} and not conflict:
            status = "accepted"
        await db.execute(
            "UPDATE facts SET status=?,updated_at=? WHERE id=?", (status, now(), fact_id)
        )
    else:
        fact_id = await insert_fact(
            db,
            person["id"],
            encounter_id,
            job_id,
            fact,
            status="conflict" if conflict else "accepted",
        )
    for source in validated:
        await db.execute(
            "INSERT OR IGNORE INTO fact_evidence VALUES(?,?,?)",
            (fact_id, source["segment_id"], source["quote"]),
        )


async def newer_than_target(
    db: aiosqlite.Connection,
    encounter_id: str,
    evidence: list[Record],
    sources: dict[str, Record],
    target_id: str,
) -> bool:
    encounter = (await rows(db, "SELECT started_at FROM encounters WHERE id=?", (encounter_id,)))[0]
    current_ends: list[float] = []
    for item in evidence:
        segment = sources[item["segment_id"]]
        if segment.get("role") != "visitor":
            continue
        end_ms = segment.get("end_ms")
        if not isinstance(end_ms, (int, float)) or not math.isfinite(end_ms):
            return False
        current_ends.append(float(end_ms))
    if not current_ends:
        return False
    observed = (encounter["started_at"], max(current_ends))
    prior = await rows(
        db,
        "SELECT e.started_at,t.data FROM fact_evidence ev "
        "JOIN transcripts t ON t.id=ev.segment_id JOIN encounters e ON e.id=t.encounter_id "
        "WHERE ev.fact_id=?",
        (target_id,),
    )
    prior_observations = []
    for row in prior:
        segment = json.loads(row["data"])
        if segment.get("role") == "visitor" and isinstance(segment.get("end_ms"), (int, float)):
            prior_observations.append((row["started_at"], segment["end_ms"]))
    return bool(prior_observations) and observed > max(prior_observations)
