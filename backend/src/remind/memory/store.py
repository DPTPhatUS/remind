import json
from datetime import UTC, datetime
from uuid import uuid4

import numpy as np

from remind.database import Database


def uid():
    return str(uuid4())


def now():
    return datetime.now(UTC).isoformat()


async def rows(db, sql, args=()):
    cursor = await db.execute(sql, args)
    return [dict(r) for r in await cursor.fetchall()]


class MemoryStore:
    def __init__(self, db: Database):
        self.db = db

    async def ensure_patient(self):
        async with self.db.transaction() as db:
            return (await rows(db, "SELECT * FROM patient"))[0]

    async def create_person(self, name=None, relationship=None, thumbnail=None):
        ident = uid()
        async with self.db.transaction() as db:
            await db.execute(
                "INSERT INTO people(id,name,relationship,created_at,thumbnail) VALUES(?,?,?,?,?)",
                (ident, name, relationship, now(), thumbnail),
            )
        self.db.revision += 1
        return await self.get_person(ident)

    async def get_person(self, ident):
        async with self.db.transaction() as db:
            result = await rows(
                db,
                "SELECT id,name,relationship,age,notes,version,created_at FROM people WHERE id=?",
                (ident,),
            )
            return result[0] if result else None

    async def thumbnail(self, ident):
        async with self.db.transaction() as db:
            result = await rows(db, "SELECT thumbnail FROM people WHERE id=?", (ident,))
            return result[0]["thumbnail"] if result else None

    async def list_people(self):
        async with self.db.transaction() as db:
            return await rows(
                db,
                "SELECT id,name,relationship,age,notes,version,created_at FROM people ORDER "
                "BY created_at DESC",
            )

    async def correct_person(self, ident, fields, version):
        allowed = {"name", "relationship", "age", "notes"}
        if not fields or not set(fields) <= allowed:
            raise ValueError("Invalid fields")
        async with self.db.transaction() as db:
            current = await rows(db, "SELECT * FROM people WHERE id=?", (ident,))
            if not current or current[0]["version"] != version:
                raise ValueError("Person changed; reload before saving")
            manual = set(json.loads(current[0]["manual"])) | set(fields)
            for key, value in fields.items():
                await db.execute(f"UPDATE people SET {key}=? WHERE id=?", (value, ident))
            await db.execute(
                "UPDATE people SET manual=?,version=version+1 WHERE id=?",
                (json.dumps(sorted(manual)), ident),
            )
        self.db.revision += 1
        return await self.get_person(ident)

    async def forget_person(self, ident):
        async with self.db.transaction() as db:
            encounters = await rows(
                db, "SELECT DISTINCT encounter_id FROM participants WHERE person_id=?", (ident,)
            )
            affected = set()
            for encounter in encounters:
                eid = encounter["encounter_id"]
                await db.execute("INSERT OR IGNORE INTO invalidated_encounters VALUES(?)", (eid,))
                for job in await rows(db, "SELECT payload FROM jobs WHERE encounter_id=?", (eid,)):
                    for key in ("audio_path", "clip_path"):
                        path = json.loads(job["payload"]).get(key)
                        if path:
                            await db.execute("INSERT OR IGNORE INTO cleanup VALUES(?)", (path,))
                await db.execute(
                    "UPDATE jobs SET status='cancelled',payload='{}',lease_token=NULL WHERE "
                    "encounter_id=?",
                    (eid,),
                )
                await db.execute("DELETE FROM transcripts WHERE encounter_id=?", (eid,))
                affected.update(
                    (f["person_id"], f["predicate"])
                    for f in await rows(
                        db, "SELECT person_id,predicate FROM facts WHERE encounter_id=?", (eid,)
                    )
                )
                await db.execute("DELETE FROM facts WHERE encounter_id=?", (eid,))
                await db.execute("UPDATE encounters SET summary=NULL WHERE id=?", (eid,))
            for pid, predicate in affected:
                person = await rows(db, "SELECT manual FROM people WHERE id=?", (pid,))
                if predicate not in {"name", "age", "relationship", "notes"} or not person:
                    continue
                if predicate in json.loads(person[0]["manual"]):
                    continue
                remaining = await rows(
                    db,
                    "SELECT value FROM facts WHERE person_id=? AND predicate=? AND "
                    "status='accepted' ORDER BY created_at DESC LIMIT 1",
                    (pid, predicate),
                )
                await db.execute(
                    f"UPDATE people SET {predicate}=?,version=version+1 WHERE id=?",
                    (remaining[0]["value"] if remaining else None, pid),
                )
            await db.execute("DELETE FROM people WHERE id=?", (ident,))
        self.db.revision += 1

    async def add_template(self, person_id, embedding, model="sface-2021dec"):
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

    async def templates(self):
        async with self.db.transaction() as db:
            return await rows(db, "SELECT person_id,model,embedding FROM templates")

    async def start_encounter(self, generation):
        ident = uid()
        async with self.db.transaction() as db:
            await db.execute(
                "INSERT INTO encounters(id,generation,started_at) VALUES(?,?,?)",
                (ident, generation, now()),
            )
        return ident

    async def add_participant(self, encounter, person_id, track_id, start_ms):
        async with self.db.transaction() as db:
            await db.execute(
                "INSERT OR IGNORE INTO participants VALUES(?,?,?,?,NULL)",
                (encounter, person_id, track_id, start_ms),
            )

    async def end_participant(self, encounter, track_id, end_ms):
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE participants SET end_ms=? WHERE encounter_id=? AND track_id=? AND "
                "end_ms IS NULL",
                (end_ms, encounter, track_id),
            )

    async def close_encounter(self, encounter, summary=None):
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE encounters SET ended_at=?,summary=COALESCE(?,summary) WHERE id=?",
                (now(), summary, encounter),
            )
        self.db.revision += 1

    async def recover_encounters(self):
        async with self.db.transaction() as db:
            await db.execute("UPDATE encounters SET ended_at=? WHERE ended_at IS NULL", (now(),))

    async def person_memory(self, ident, exclude_encounter_id=None):
        person = await self.get_person(ident)
        if person is None:
            return None
        async with self.db.transaction() as db:
            encounters = await rows(
                db,
                """SELECT DISTINCT e.* FROM encounters e JOIN participants p ON p.encounter_id=e.id
                WHERE p.person_id=? AND e.ended_at IS NOT NULL AND e.id!=?
                ORDER BY e.started_at DESC LIMIT 30""",
                (ident, exclude_encounter_id or ""),
            )
            facts = await rows(
                db, "SELECT * FROM facts WHERE person_id=? ORDER BY created_at DESC", (ident,)
            )
        return {
            **person,
            "last_encounter": encounters[0] if encounters else None,
            "encounters": encounters,
            "facts": facts,
        }

    async def enqueue_job(self, encounter, window_key, payload):
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
            await db.execute(
                "INSERT OR IGNORE INTO jobs(id,encounter_id,window_key,payload,created_at) "
                "VALUES(?,?,?,?,?)",
                (uid(), encounter, window_key, json.dumps(payload), now()),
            )
            return (
                await rows(
                    db,
                    "SELECT id FROM jobs WHERE encounter_id=? AND window_key=?",
                    (encounter, window_key),
                )
            )[0]["id"]

    async def pending_jobs(self):
        async with self.db.transaction() as db:
            return await rows(
                db,
                "SELECT id,status,attempts,error FROM jobs WHERE status IN "
                "('pending','running','failed') ORDER BY created_at",
            )

    async def retry_job(self, ident):
        async with self.db.transaction() as db:
            result = await db.execute(
                "UPDATE jobs SET status='pending',attempts=0,next_at=0,error=NULL "
                "WHERE id=? AND status='failed' AND encounter_id NOT IN "
                "(SELECT id FROM invalidated_encounters)",
                (ident,),
            )
            return result.rowcount == 1

    async def claim_job(self, worker_id, now_ms):
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE jobs SET status='failed',error='Retry limit reached',lease_token=NULL "
                "WHERE status='running' AND attempts>=3 AND lease_until<?",
                (now_ms,),
            )
            candidates = await rows(
                db,
                """SELECT * FROM jobs WHERE attempts<3 AND
                ((status='pending' AND next_at<=?) OR (status='running' AND lease_until<?))
                ORDER BY created_at LIMIT 1""",
                (now_ms, now_ms),
            )
            if not candidates:
                return None
            job = candidates[0]
            token = worker_id + ":" + uid()
            await db.execute(
                "UPDATE jobs SET "
                "status='running',attempts=attempts+1,lease_token=?,lease_until=? WHERE id=?",
                (token, now_ms + 180000, job["id"]),
            )
            return {**job, "lease_token": token, "payload": json.loads(job["payload"])}

    async def renew_lease(self, ident, token, now_ms):
        async with self.db.transaction() as db:
            result = await db.execute(
                "UPDATE jobs SET lease_until=? WHERE id=? AND lease_token=? AND status='running'",
                (now_ms + 180000, ident, token),
            )
            return result.rowcount == 1

    async def fail_job(self, ident, token, error, now_ms):
        async with self.db.transaction() as db:
            await db.execute(
                """UPDATE jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,
                error=?,next_at=?,lease_token=NULL WHERE id=? AND lease_token=?""",
                (str(error)[:240], now_ms + 5000, ident, token),
            )

    async def finish_job(self, ident, token, result):
        async with self.db.transaction() as db:
            found = await rows(
                db,
                "SELECT * FROM jobs WHERE id=? AND lease_token=? AND status='running'",
                (ident, token),
            )
            if not found:
                return False
            job = found[0]
            payload = json.loads(job["payload"])
            if await rows(
                db, "SELECT id FROM invalidated_encounters WHERE id=?", (job["encounter_id"],)
            ):
                return False
            for pid, version in payload.get("versions", {}).items():
                person = await rows(db, "SELECT version FROM people WHERE id=?", (pid,))
                if not person or person[0]["version"] != version:
                    await db.execute(
                        "UPDATE jobs SET status='cancelled',lease_token=NULL WHERE id=?", (ident,)
                    )
                    return False
            eid = job["encounter_id"]
            for segment in result.get("segments", []):
                await db.execute(
                    "INSERT INTO transcripts VALUES(?,?,?,?)",
                    (uid(), ident, eid, json.dumps(segment)),
                )
            for fact in result.get("facts", []):
                pid = fact["person_id"]
                if pid not in payload.get("versions", {}):
                    continue
                person = (await rows(db, "SELECT * FROM people WHERE id=?", (pid,)))[0]
                predicate, value = fact["predicate"], fact["value"]
                conflict = predicate in {"name", "relationship", "age", "notes"} and person[
                    predicate
                ] not in (None, "", value)
                await db.execute(
                    "INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        uid(),
                        pid,
                        eid,
                        ident,
                        predicate,
                        value,
                        json.dumps(fact["evidence"]),
                        now(),
                        "conflict" if conflict else "accepted",
                    ),
                )
                if (
                    predicate in {"name", "relationship", "age", "notes"}
                    and predicate not in json.loads(person["manual"])
                    and not conflict
                ):
                    await db.execute(f"UPDATE people SET {predicate}=? WHERE id=?", (value, pid))
            order = payload.get("end_ms", 0)
            await db.execute(
                "UPDATE encounters SET summary=COALESCE(?,summary),summary_order=? "
                "WHERE id=? AND summary_order<=?",
                (result.get("summary"), order, eid, order),
            )
            await db.execute(
                "UPDATE jobs SET status='done',lease_token=NULL,error=NULL WHERE id=?", (ident,)
            )
        self.db.revision += 1
        return True
