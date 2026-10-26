import json
from datetime import UTC, datetime
from uuid import uuid4

import aiosqlite
import numpy as np
from numpy.typing import ArrayLike

from remind.database import Database, Record, rows
from remind.memory.facts import (
    IDENTITY_FIELDS,
    SINGLE_VALUE_PREDICATES,
    insert_fact,
    load_facts,
    refresh_profile,
    save_claim,
)

PERSON_COLUMNS = "id,name,relationship,age,notes,version,profile_summary,highlights,created_at"


def uid() -> str:
    return str(uuid4())


def now() -> str:
    return datetime.now(UTC).isoformat()


def public_person(person: Record) -> Record:
    return {**person, "highlights": json.loads(person["highlights"])}


class MemoryStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_person(
        self,
        name: str | None = None,
        relationship: str | None = None,
        thumbnail: bytes | None = None,
    ) -> Record:
        ident = uid()
        async with self.db.transaction() as db:
            await db.execute(
                "INSERT INTO people(id,name,relationship,created_at,thumbnail) VALUES(?,?,?,?,?)",
                (ident, name, relationship, now(), thumbnail),
            )
            supplied = {
                key: value
                for key, value in {"name": name, "relationship": relationship}.items()
                if value
            }
            for key, value in supplied.items():
                await insert_fact(
                    db,
                    ident,
                    None,
                    None,
                    {
                        "subject": "visitor",
                        "category": "identity",
                        "predicate": key,
                        "value": value,
                    },
                    manual=True,
                )
            if supplied:
                await db.execute(
                    "UPDATE people SET manual=? WHERE id=?", (json.dumps(sorted(supplied)), ident)
                )
                await refresh_profile(db, ident)
            result = await rows(db, f"SELECT {PERSON_COLUMNS} FROM people WHERE id=?", (ident,))
            person = public_person(result[0])
        self.db.revision += 1
        return person

    async def get_person(self, ident: str) -> Record | None:
        async with self.db.transaction() as db:
            result = await rows(db, f"SELECT {PERSON_COLUMNS} FROM people WHERE id=?", (ident,))
            return public_person(result[0]) if result else None

    async def thumbnail(self, ident: str) -> bytes | None:
        async with self.db.transaction() as db:
            result = await rows(db, "SELECT thumbnail FROM people WHERE id=?", (ident,))
            return result[0]["thumbnail"] if result else None

    async def list_people(self) -> list[Record]:
        async with self.db.transaction() as db:
            result = await rows(db, f"SELECT {PERSON_COLUMNS} FROM people ORDER BY created_at DESC")
            return [public_person(person) for person in result]

    async def facts_for_person(self, ident: str) -> list[Record]:
        async with self.db.transaction() as db:
            return await load_facts(db, ident)

    async def _require_version(
        self,
        db: aiosqlite.Connection,
        ident: str,
        version: int,
    ) -> Record:
        current = await rows(db, "SELECT * FROM people WHERE id=?", (ident,))
        if not current or current[0]["version"] != version:
            raise ValueError("Person changed; reload before saving")
        return current[0]

    async def correct_person(
        self,
        ident: str,
        fields: dict[str, str | None],
        version: int,
    ) -> Record | None:
        if not fields or not set(fields) <= IDENTITY_FIELDS:
            raise ValueError("Invalid fields")
        async with self.db.transaction() as db:
            current = await self._require_version(db, ident, version)
            manual = set(json.loads(current["manual"])) | set(fields)
            for key, value in fields.items():
                await db.execute(f"UPDATE people SET {key}=? WHERE id=?", (value, ident))
                await db.execute(
                    "UPDATE facts SET status='superseded',manual=1,updated_at=? "
                    "WHERE person_id=? AND subject='visitor' AND predicate=? "
                    "AND status IN ('accepted','conflict')",
                    (now(), ident, key),
                )
                if value:
                    await insert_fact(
                        db,
                        ident,
                        None,
                        None,
                        {
                            "subject": "visitor",
                            "category": "identity",
                            "predicate": key,
                            "value": value,
                            "temporal_status": "current",
                        },
                        manual=True,
                    )
            await db.execute(
                "UPDATE people SET manual=?,version=version+1 WHERE id=?",
                (json.dumps(sorted(manual)), ident),
            )
            await refresh_profile(db, ident)
        self.db.revision += 1
        return await self.get_person(ident)

    async def correct_fact(
        self,
        ident: str,
        fact_id: str,
        value: str,
        version: int,
    ) -> Record | None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("A fact value is required")
        async with self.db.transaction() as db:
            current = await self._require_version(db, ident, version)
            found = await rows(
                db, "SELECT * FROM facts WHERE id=? AND person_id=?", (fact_id, ident)
            )
            if not found:
                raise ValueError("Fact not found")
            fact = found[0]
            singleton = fact["predicate"] in SINGLE_VALUE_PREDICATES
            if singleton and fact["temporal_status"] == "current":
                await db.execute(
                    "UPDATE facts SET status='superseded',manual=1,updated_at=? WHERE person_id=? "
                    "AND subject=? AND predicate=? AND status='accepted' "
                    "AND temporal_status='current'",
                    (now(), ident, fact["subject"], fact["predicate"]),
                )
            await db.execute(
                "UPDATE facts SET status='superseded',manual=1,updated_at=? WHERE id=?",
                (now(), fact_id),
            )
            replacement = {**fact, "value": value.strip()}
            replacement_id = await insert_fact(db, ident, None, None, replacement, manual=True)
            await db.execute(
                "INSERT OR IGNORE INTO fact_evidence SELECT ?,segment_id,quote FROM fact_evidence "
                "WHERE fact_id=?",
                (replacement_id, fact_id),
            )
            if (
                fact["subject"] == "visitor"
                and fact["predicate"] in IDENTITY_FIELDS
                and fact["temporal_status"] == "current"
            ):
                field = fact["predicate"]
                manual = set(json.loads(current["manual"])) | {field}
                await db.execute(
                    f"UPDATE people SET {field}=?,manual=? WHERE id=?",
                    (value.strip(), json.dumps(sorted(manual)), ident),
                )
            await db.execute("UPDATE people SET version=version+1 WHERE id=?", (ident,))
            await refresh_profile(db, ident)
        self.db.revision += 1
        return await self.person_memory(ident)

    async def dismiss_fact(self, ident: str, fact_id: str, version: int) -> Record | None:
        async with self.db.transaction() as db:
            current = await self._require_version(db, ident, version)
            found = await rows(
                db, "SELECT * FROM facts WHERE id=? AND person_id=?", (fact_id, ident)
            )
            if not found:
                raise ValueError("Fact not found")
            fact = found[0]
            await db.execute(
                "UPDATE facts SET status='dismissed',manual=1,updated_at=? WHERE id=?",
                (now(), fact_id),
            )
            if (
                fact["subject"] == "visitor"
                and fact["predicate"] in IDENTITY_FIELDS
                and fact["status"] == "accepted"
                and fact["temporal_status"] == "current"
                and current[fact["predicate"]] == fact["value"]
            ):
                await db.execute(f"UPDATE people SET {fact['predicate']}=NULL WHERE id=?", (ident,))
            await db.execute("UPDATE people SET version=version+1 WHERE id=?", (ident,))
            await refresh_profile(db, ident)
        self.db.revision += 1
        return await self.person_memory(ident)

    async def forget_person(self, ident: str) -> None:
        async with self.db.transaction() as db:
            encounters = await rows(
                db, "SELECT DISTINCT encounter_id FROM participants WHERE person_id=?", (ident,)
            )
            affected = set()
            for encounter in encounters:
                eid = encounter["encounter_id"]
                await db.execute("INSERT OR IGNORE INTO invalidated_encounters VALUES(?)", (eid,))
                for job in await rows(db, "SELECT payload FROM jobs WHERE encounter_id=?", (eid,)):
                    path = json.loads(job["payload"]).get("clip_path")
                    if path:
                        await db.execute("INSERT OR IGNORE INTO cleanup VALUES(?)", (path,))
                await db.execute(
                    "UPDATE jobs SET status='cancelled',payload='{}',lease_token=NULL WHERE "
                    "encounter_id=?",
                    (eid,),
                )
                source_facts = await rows(
                    db,
                    "SELECT DISTINCT f.id,f.person_id,f.predicate,f.subject FROM facts f "
                    "LEFT JOIN fact_evidence ev ON ev.fact_id=f.id "
                    "LEFT JOIN transcripts t ON t.id=ev.segment_id "
                    "WHERE f.encounter_id=? OR t.encounter_id=?",
                    (eid, eid),
                )
                for fact in source_facts:
                    affected.add(fact["person_id"])
                    if fact["subject"] == "visitor" and fact["predicate"] in IDENTITY_FIELDS:
                        person = await rows(
                            db, "SELECT manual FROM people WHERE id=?", (fact["person_id"],)
                        )
                        if person and fact["predicate"] not in json.loads(person[0]["manual"]):
                            await db.execute(
                                f"UPDATE people SET {fact['predicate']}=NULL WHERE id=?",
                                (fact["person_id"],),
                            )
                    await db.execute("DELETE FROM facts WHERE id=?", (fact["id"],))
                await db.execute("DELETE FROM transcripts WHERE encounter_id=?", (eid,))
                await db.execute("UPDATE encounters SET summary=NULL WHERE id=?", (eid,))
            await db.execute("DELETE FROM people WHERE id=?", (ident,))
            for other in affected - {ident}:
                await db.execute("UPDATE people SET version=version+1 WHERE id=?", (other,))
                await refresh_profile(db, other)
        self.db.revision += 1

    async def voice_profile(self) -> Record | None:
        async with self.db.transaction() as db:
            profile = (await rows(db, "SELECT * FROM user_voice WHERE id=1"))[0]
            if profile["embeddings"] is None:
                return None
            return {
                "version": profile["version"],
                "model": profile["model"],
                "embeddings": json.loads(profile["embeddings"]),
                "created_at": profile["created_at"],
            }

    async def voice_status(self) -> Record:
        async with self.db.transaction() as db:
            profile = (await rows(db, "SELECT * FROM user_voice WHERE id=1"))[0]
            embeddings = json.loads(profile["embeddings"]) if profile["embeddings"] else []
            return {
                "ready": bool(embeddings),
                "version": profile["version"],
                "model": profile["model"],
                "sample_count": len(embeddings),
                "updated_at": profile["updated_at"],
            }

    async def set_voice_profile(self, embeddings: ArrayLike, model: str) -> Record:
        vectors = np.asarray(embeddings, dtype=np.float32)
        if (
            not isinstance(model, str)
            or not model
            or vectors.ndim != 2
            or not vectors.size
            or not np.isfinite(vectors).all()
            or (np.linalg.norm(vectors, axis=1) < 1e-8).any()
        ):
            raise ValueError("Invalid voice embeddings")
        vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
        async with self.db.transaction() as db:
            stamp = now()
            await db.execute(
                "UPDATE user_voice SET version=version+1,model=?,embeddings=?,created_at=?,"
                "updated_at=? WHERE id=1",
                (model, json.dumps(vectors.tolist()), stamp, stamp),
            )
        self.db.revision += 1
        return await self.voice_status()

    async def delete_voice_profile(self) -> Record:
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE user_voice SET version=version+1,model=NULL,embeddings=NULL,"
                "created_at=NULL,updated_at=? WHERE id=1",
                (now(),),
            )
        self.db.revision += 1
        return await self.voice_status()

    async def add_template(
        self,
        person_id: str,
        embedding: ArrayLike,
        model: str = "sface-2021dec",
    ) -> None:
        array = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if array.size != 128 or not np.isfinite(array).all() or np.linalg.norm(array) < 1e-8:
            raise ValueError("Invalid face embedding")
        array /= np.linalg.norm(array)
        async with self.db.transaction() as db:
            count = (
                await rows(
                    db, "SELECT count(*) AS n FROM templates WHERE person_id=?", (person_id,)
                )
            )[0]["n"]
            if count >= 8:
                return
            await db.execute(
                "INSERT INTO templates VALUES(?,?,?,?)", (uid(), person_id, model, array.tobytes())
            )
        self.db.revision += 1

    async def templates(self) -> list[Record]:
        async with self.db.transaction() as db:
            return await rows(db, "SELECT person_id,model,embedding FROM templates")

    async def start_encounter(self, generation: str) -> str:
        ident = uid()
        async with self.db.transaction() as db:
            await db.execute(
                "INSERT INTO encounters(id,generation,started_at) VALUES(?,?,?)",
                (ident, generation, now()),
            )
        return ident

    async def get_encounter(self, encounter_id: str) -> Record | None:
        async with self.db.transaction() as db:
            result = await rows(db, "SELECT * FROM encounters WHERE id=?", (encounter_id,))
            return result[0] if result else None

    async def add_participant(
        self,
        encounter: str,
        person_id: str,
        track_id: str,
        start_ms: float,
    ) -> None:
        async with self.db.transaction() as db:
            await db.execute(
                "INSERT OR IGNORE INTO participants VALUES(?,?,?,?,NULL)",
                (encounter, person_id, track_id, start_ms),
            )

    async def end_participant(self, encounter: str, track_id: str, end_ms: float) -> None:
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE participants SET end_ms=? WHERE encounter_id=? AND track_id=? "
                "AND end_ms IS NULL",
                (end_ms, encounter, track_id),
            )

    async def close_encounter(self, encounter: str, summary: str | None = None) -> None:
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE encounters SET ended_at=?,summary=COALESCE(?,summary) WHERE id=?",
                (now(), summary, encounter),
            )
        self.db.revision += 1

    async def recover_encounters(self) -> None:
        async with self.db.transaction() as db:
            await db.execute("UPDATE encounters SET ended_at=? WHERE ended_at IS NULL", (now(),))

    async def person_memory(
        self,
        ident: str,
        exclude_encounter_id: str | None = None,
    ) -> Record | None:
        async with self.db.transaction() as db:
            result = await rows(db, f"SELECT {PERSON_COLUMNS} FROM people WHERE id=?", (ident,))
            if not result:
                return None
            person = public_person(result[0])
            encounters = await rows(
                db,
                "SELECT DISTINCT e.* FROM encounters e JOIN participants p ON p.encounter_id=e.id "
                "WHERE p.person_id=? AND e.ended_at IS NOT NULL AND e.id!=? "
                "ORDER BY e.started_at DESC LIMIT 30",
                (ident, exclude_encounter_id or ""),
            )
            facts = await load_facts(db, ident)
        return {
            **person,
            "last_encounter": encounters[0] if encounters else None,
            "encounters": encounters,
            "facts": facts,
        }

    async def recent_context(
        self,
        encounter_id: str,
        limit: int = 40,
        before_ms: float | None = None,
    ) -> list[Record]:
        async with self.db.transaction() as db:
            segments = await rows(
                db,
                "SELECT data FROM transcripts WHERE encounter_id=? "
                "AND (? IS NULL OR json_extract(data,'$.end_ms')<=?) "
                "ORDER BY start_ms DESC,rowid DESC LIMIT ?",
                (encounter_id, before_ms, before_ms, max(0, min(200, limit))),
            )
        return [json.loads(segment["data"]) for segment in reversed(segments)]

    async def enqueue_job(self, encounter: str, window_key: str, payload: Record) -> str:
        async with self.db.transaction() as db:
            if await rows(db, "SELECT id FROM invalidated_encounters WHERE id=?", (encounter,)):
                raise ValueError("This encounter was forgotten")
            existing = await rows(
                db,
                "SELECT id,payload FROM jobs WHERE encounter_id=? AND window_key=?",
                (encounter, window_key),
            )
            if existing:
                old_path = json.loads(existing[0]["payload"]).get("clip_path")
                new_path = payload.get("clip_path")
                if new_path and new_path != old_path:
                    await db.execute("INSERT OR IGNORE INTO cleanup VALUES(?)", (new_path,))
                return existing[0]["id"]
            ident = uid()
            await db.execute(
                "INSERT INTO jobs(id,encounter_id,window_key,payload,created_at) VALUES(?,?,?,?,?)",
                (ident, encounter, window_key, json.dumps(payload), now()),
            )
            return ident

    async def pending_jobs(self) -> list[Record]:
        async with self.db.transaction() as db:
            return await rows(
                db,
                "SELECT id,status,attempts,error FROM jobs "
                "WHERE status IN ('pending','running','failed') ORDER BY created_at",
            )

    async def retry_job(self, ident: str) -> bool:
        async with self.db.transaction() as db:
            result = await db.execute(
                "UPDATE jobs SET status='pending',attempts=0,next_at=0,error=NULL "
                "WHERE id=? AND status='failed' AND encounter_id NOT IN "
                "(SELECT id FROM invalidated_encounters)",
                (ident,),
            )
            return result.rowcount == 1

    async def claim_job(self, worker_id: str, now_ms: int) -> Record | None:
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE jobs SET status='failed',error='Retry limit reached',lease_token=NULL "
                "WHERE status='running' AND attempts>=3 AND lease_until<?",
                (now_ms,),
            )
            candidates = await rows(
                db,
                "SELECT j.* FROM jobs j WHERE j.attempts<3 AND "
                "((j.status='pending' AND j.next_at<=?) "
                "OR (j.status='running' AND j.lease_until<?)) "
                "AND NOT EXISTS(SELECT 1 FROM jobs r WHERE r.encounter_id=j.encounter_id "
                "AND r.id!=j.id AND r.status='running' AND r.lease_until>=?) "
                "AND NOT EXISTS(SELECT 1 FROM jobs earlier "
                "WHERE earlier.encounter_id=j.encounter_id "
                "AND earlier.created_at<j.created_at AND earlier.status IN ('pending','running')) "
                "ORDER BY j.created_at LIMIT 1",
                (now_ms, now_ms, now_ms),
            )
            if not candidates:
                return None
            job = candidates[0]
            token = worker_id + ":" + uid()
            await db.execute(
                "UPDATE jobs SET status='running',attempts=attempts+1,lease_token=?,lease_until=? "
                "WHERE id=?",
                (token, now_ms + 180000, job["id"]),
            )
            return {**job, "lease_token": token, "payload": json.loads(job["payload"])}

    async def renew_lease(self, ident: str, token: str, now_ms: int) -> bool:
        async with self.db.transaction() as db:
            result = await db.execute(
                "UPDATE jobs SET lease_until=? WHERE id=? AND lease_token=? AND status='running'",
                (now_ms + 180000, ident, token),
            )
            return result.rowcount == 1

    async def fail_job(self, ident: str, token: str, error: str, now_ms: int) -> None:
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,"
                "error=?,next_at=?,lease_token=NULL "
                "WHERE id=? AND lease_token=? AND status='running'",
                (str(error)[:240], now_ms + 5000, ident, token),
            )

    async def finish_job(self, ident: str, token: str, result: Record) -> bool:
        async with self.db.transaction() as db:
            found = await rows(
                db,
                "SELECT * FROM jobs WHERE id=? AND lease_token=? AND status='running'",
                (ident, token),
            )
            if not found:
                return False
            job, eid = found[0], found[0]["encounter_id"]
            payload = json.loads(job["payload"])
            if await rows(db, "SELECT id FROM invalidated_encounters WHERE id=?", (eid,)):
                return False
            for pid, version in payload.get("versions", {}).items():
                person = await rows(db, "SELECT version FROM people WHERE id=?", (pid,))
                if not person or person[0]["version"] != version:
                    await db.execute(
                        "UPDATE jobs SET status='cancelled',lease_token=NULL,"
                        "error='Person changed' WHERE id=?",
                        (ident,),
                    )
                    return False
            voice = (await rows(db, "SELECT * FROM user_voice WHERE id=1"))[0]
            if "voice_version" in payload and payload["voice_version"] != voice["version"]:
                await db.execute(
                    "UPDATE jobs SET status='cancelled',lease_token=NULL,"
                    "error='Voice reference changed' WHERE id=?",
                    (ident,),
                )
                return False
            for segment in result.get("segments", []):
                segment_id = segment.get("id")
                if not isinstance(segment_id, str) or not segment_id:
                    continue
                await db.execute(
                    "INSERT OR IGNORE INTO transcripts VALUES(?,?,?,?,?)",
                    (segment_id, ident, eid, segment.get("start_ms", 0), json.dumps(segment)),
                )
            transcript_rows = await rows(
                db, "SELECT id,data FROM transcripts WHERE encounter_id=?", (eid,)
            )
            sources = {source["id"]: json.loads(source["data"]) for source in transcript_rows}
            visitor_id = payload.get("visitor_id")
            people = (
                await rows(db, "SELECT * FROM people WHERE id=?", (visitor_id,))
                if visitor_id
                else []
            )
            participant = (
                await rows(
                    db,
                    "SELECT 1 FROM participants WHERE encounter_id=? AND person_id=?",
                    (eid, visitor_id),
                )
                if visitor_id
                else []
            )
            if (
                people
                and participant
                and voice["embeddings"]
                and visitor_id in payload.get("versions", {})
            ):
                for fact in result.get("facts", []):
                    await save_claim(db, people[0], eid, ident, fact, sources)
                await refresh_profile(db, visitor_id)
            order = payload.get("end_ms", 0)
            await db.execute(
                "UPDATE encounters SET summary=COALESCE(?,summary),summary_order=? "
                "WHERE id=? AND summary_order<=?",
                (result.get("summary"), order, eid, order),
            )
            if result.get("metrics") is not None:
                await db.execute(
                    "INSERT OR REPLACE INTO job_metrics VALUES(?,?)",
                    (ident, json.dumps(result["metrics"])),
                )
            await db.execute(
                "UPDATE jobs SET status='done',lease_token=NULL,error=NULL WHERE id=?", (ident,)
            )
        self.db.revision += 1
        return True

    async def processing_metrics(self) -> list[Record]:
        async with self.db.transaction() as db:
            result = await rows(db, "SELECT job_id,data FROM job_metrics ORDER BY rowid")
        return [{"job_id": metric["job_id"], **json.loads(metric["data"])} for metric in result]

    async def pending_cleanup(self) -> list[str]:
        async with self.db.transaction() as db:
            result = await rows(db, "SELECT path FROM cleanup")
            return [entry["path"] for entry in result]

    async def complete_cleanup(self, path: str) -> None:
        async with self.db.transaction() as db:
            await db.execute("DELETE FROM cleanup WHERE path=?", (path,))
