import json
from datetime import UTC, datetime
from uuid import uuid4

import aiosqlite
import numpy as np
from numpy.typing import ArrayLike

from remind.database import Database, Record, rows
from remind.memory.cleanup import cancel_clip
from remind.memory.contracts import TranscriptTurn
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


async def save_conversation_result(
    db: aiosqlite.Connection,
    encounter_id: str,
    job_id: str,
    person: Record | None,
    result: Record,
    order: float,
) -> None:
    """Persist within a transaction; person must be an authorized raw store row."""
    transcript_rows = await rows(
        db, "SELECT id,data FROM transcripts WHERE encounter_id=?", (encounter_id,)
    )
    sources = {source["id"]: json.loads(source["data"]) for source in transcript_rows}
    if person is not None:
        for fact in result.get("facts", []):
            await save_claim(db, person, encounter_id, job_id, fact, sources)
        await refresh_profile(db, person["id"])
    await db.execute(
        "UPDATE encounters SET summary=COALESCE(?,summary),summary_order=? "
        "WHERE id=? AND summary_order<=?",
        (result.get("summary"), order, encounter_id, order),
    )


class MemoryStore:
    def __init__(self, db: Database, template_threshold: float = 0.55) -> None:
        self.db = db
        self.template_threshold = template_threshold

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
            # A shared recording contains the forgotten visitor even if other turns
            # belong to somebody else. Keep their independent text memories only.
            clips = await rows(
                db,
                "SELECT DISTINCT c.id,c.path FROM clips c "
                "JOIN transcripts t ON t.clip_id=c.id JOIN encounters e ON e.id=t.encounter_id "
                "WHERE e.person_id=?",
                (ident,),
            )
            for clip in clips:
                await cancel_clip(db, clip["id"], clip["path"])
            # Queued audio may not have produced transcripts yet.
            for clip in await rows(db, "SELECT id,path,timeline FROM clips WHERE cancelled=0"):
                if any(point.get("visitor_id") == ident for point in json.loads(clip["timeline"])):
                    await cancel_clip(db, clip["id"], clip["path"])
            await db.execute("DELETE FROM people WHERE id=?", (ident,))
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

    async def enroll_person(self, thumbnail: bytes | None, samples: list) -> Record:
        from remind.vision.gallery import normalize_embedding

        ident = uid()
        vectors = [normalize_embedding(sample) for sample in samples]
        if not vectors or len(vectors) > 8:
            raise ValueError("Enrollment requires one to eight face samples")
        async with self.db.transaction() as db:
            await db.execute(
                "INSERT INTO people(id,created_at,thumbnail) VALUES(?,?,?)",
                (ident, now(), thumbnail),
            )
            for index, vector in enumerate(vectors):
                await db.execute(
                    "INSERT INTO templates VALUES(?,?,?,?,?)",
                    (uid(), ident, "sface-2021dec", vector.tobytes(), int(index < 4)),
                )
        self.db.revision += 1
        person = await self.get_person(ident)
        assert person is not None
        return person

    async def update_templates(self, person_id: str, feature: ArrayLike) -> bool:
        from remind.vision.gallery import normalize_embedding

        vector = normalize_embedding(feature)
        async with self.db.transaction() as db:
            fixed = await rows(
                db, "SELECT embedding FROM templates WHERE person_id=? AND fixed=1", (person_id,)
            )
            if (
                not fixed
                or max(float(np.frombuffer(r["embedding"], np.float32) @ vector) for r in fixed)
                < self.template_threshold
            ):
                return False
            adaptive = await rows(
                db,
                "SELECT id,embedding FROM templates WHERE person_id=? AND fixed=0 ORDER BY rowid",
                (person_id,),
            )
            if any(
                float(np.frombuffer(r["embedding"], np.float32) @ vector) > 0.999 for r in adaptive
            ):
                return False
            if len(adaptive) >= 4:
                await db.execute("DELETE FROM templates WHERE id=?", (adaptive[0]["id"],))
            await db.execute(
                "INSERT INTO templates VALUES(?,?,?,?,0)",
                (uid(), person_id, "sface-2021dec", vector.tobytes()),
            )
        self.db.revision += 1
        return True

    async def templates(self) -> list[Record]:
        async with self.db.transaction() as db:
            return await rows(db, "SELECT person_id,model,embedding,fixed FROM templates")

    async def start_session(self, generation: str) -> None:
        async with self.db.transaction() as db:
            await db.execute(
                "INSERT OR IGNORE INTO capture_sessions(generation,started_at) VALUES(?,?)",
                (generation, now()),
            )

    async def start_encounter(self, generation: str, person_id: str, start_ms: float) -> str:
        ident = uid()
        await self.start_session(generation)
        async with self.db.transaction() as db:
            await db.execute(
                "INSERT INTO encounters(id,generation,person_id,start_ms,started_at) "
                "VALUES(?,?,?,?,?)",
                (ident, generation, person_id, start_ms, now()),
            )
        return ident

    async def get_encounter(self, encounter_id: str) -> Record | None:
        async with self.db.transaction() as db:
            result = await rows(db, "SELECT * FROM encounters WHERE id=?", (encounter_id,))
            return result[0] if result else None

    async def close_encounter(self, encounter: str, end_ms: float) -> None:
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE encounters SET ended_at=?,end_ms=? WHERE id=? AND ended_at IS NULL",
                (now(), end_ms, encounter),
            )
        self.db.revision += 1

    async def person_memory(
        self, ident: str, exclude_encounter_id: str | None = None
    ) -> Record | None:
        async with self.db.transaction() as db:
            result = await rows(db, f"SELECT {PERSON_COLUMNS} FROM people WHERE id=?", (ident,))
            if not result:
                return None
            person = public_person(result[0])
            encounters = await rows(
                db,
                "SELECT * FROM encounters WHERE person_id=? "
                "AND ended_at IS NOT NULL AND id!=? ORDER BY started_at DESC LIMIT 30",
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
        *,
        after_ms: float | None = None,
    ) -> list[TranscriptTurn]:
        async with self.db.transaction() as db:
            segments = await rows(
                db,
                "SELECT data FROM transcripts WHERE encounter_id=? "
                "AND (? IS NULL OR json_extract(data,'$.end_ms')<=?) "
                "AND (? IS NULL OR json_extract(data,'$.start_ms')>=?) "
                "ORDER BY start_ms DESC,rowid DESC LIMIT ?",
                (encounter_id, before_ms, before_ms, after_ms, after_ms, max(0, min(200, limit))),
            )
        return [json.loads(segment["data"]) for segment in reversed(segments)]

    async def latest_audio_gap(self, encounter_id: str, before_ms: float) -> float | None:
        async with self.db.transaction() as db:
            found = await rows(
                db,
                """
                SELECT max(c.end_ms) AS end_ms FROM clips c
                JOIN jobs audio ON audio.clip_id=c.id AND audio.kind='audio'
                JOIN encounters encounter ON encounter.generation=c.generation
                WHERE encounter.id=? AND c.start_ms<? AND c.end_ms>encounter.start_ms
                  AND c.audio_done=0 AND audio.status IN ('failed','cancelled')
                """,
                (encounter_id, before_ms),
            )
        return found[0]["end_ms"]

    async def pending_cleanup(self) -> list[str]:
        async with self.db.transaction() as db:
            return [r["path"] for r in await rows(db, "SELECT path FROM cleanup")]

    async def complete_cleanup(self, path: str) -> None:
        async with self.db.transaction() as db:
            await db.execute("DELETE FROM cleanup WHERE path=?", (path,))
