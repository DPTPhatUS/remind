"""Durable clip intake, attribution, and audio/learning jobs."""

import json
import time
from collections import defaultdict

from remind.database import Record, rows
from remind.memory.association import associate_turn
from remind.memory.store import MemoryStore, now, save_conversation_result, uid


def milliseconds() -> int:
    return int(time.time() * 1000)


class CaptureStore:
    def __init__(self, memory: MemoryStore, attribution_wait_seconds: int = 30):
        self.memory = memory
        self.db = memory.db
        self.wait_ms = attribution_wait_seconds * 1000

    async def receive_clip(
        self,
        generation: str,
        window_key: str,
        start_ms: float,
        end_ms: float,
        path: str | None,
        timeline: list[Record],
        voice_version: int | None,
        *,
        input_kind: str = "media",
    ) -> Record:
        await self.memory.start_session(generation)
        stamp = milliseconds()
        async with self.db.transaction() as db:
            session = (
                await rows(
                    db, "SELECT cancelled FROM capture_sessions WHERE generation=?", (generation,)
                )
            )[0]
            if session["cancelled"]:
                raise ValueError("This capture session was forgotten")
            existing = await rows(
                db,
                "SELECT id FROM clips WHERE generation=? AND window_key=?",
                (generation, window_key),
            )
            if existing:
                if path:
                    await db.execute("INSERT OR IGNORE INTO cleanup VALUES(?)", (path,))
                clip_id = existing[0]["id"]
            else:
                clip_id = uid()
                await db.execute(
                    "INSERT INTO clips(id,generation,window_key,start_ms,end_ms,path,"
                    "received_ms,expires_ms,voice_version,timeline,input_kind) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        clip_id,
                        generation,
                        window_key,
                        start_ms,
                        end_ms,
                        path,
                        stamp,
                        stamp + 86400000,
                        voice_version,
                        json.dumps(timeline),
                        input_kind,
                    ),
                )
                await db.execute(
                    "INSERT INTO jobs(id,clip_id,kind,payload,created_at) VALUES(?,?,'audio',?,?)",
                    (uid(), clip_id, "{}", now()),
                )
        return await self.receipt(clip_id)

    async def receive_transcript_batch(
        self,
        encounter_id: str,
        window_key: str,
        start_ms: float,
        end_ms: float,
        turns: list[Record],
    ) -> Record:
        """Trusted transcript input for the conversation benchmark; never an HTTP input."""
        encounter = await self.memory.get_encounter(encounter_id)
        if not encounter:
            raise ValueError("Encounter not found")
        person = await self.memory.get_person(encounter["person_id"])
        if not person:
            raise ValueError("Person not found")
        receipt = await self.receive_clip(
            encounter["generation"],
            window_key,
            start_ms,
            end_ms,
            None,
            [],
            None,
            input_kind="conversation",
        )
        audio_job = await self.claim_job("conversation")
        if (
            not audio_job
            or audio_job["clip_id"] != receipt["clip_id"]
            or audio_job["kind"] != "audio"
        ):
            raise RuntimeError("Previous transcript work must finish before the next batch")
        segments = [
            {
                **t,
                "id": f"{audio_job['id']}:{t['id']}",
                "start_ms": t["start_ms"] - start_ms,
                "end_ms": t["end_ms"] - start_ms,
                "association": {
                    "status": "attributed",
                    "reason": "trusted_transcript",
                    "encounter_id": encounter_id,
                    "visitor_id": person["id"],
                    "person_version": person["version"],
                },
            }
            for t in turns
        ]
        await self.finish_audio(
            audio_job, {"segments": segments, "voice_ready": True, "metrics": {}}
        )
        job = await self.claim_job("conversation")
        if not job or job["clip_id"] != receipt["clip_id"] or job["kind"] != "learning":
            raise RuntimeError("Unable to claim transcript learning batch")
        return job

    async def receipt(self, clip_id: str) -> Record:
        async with self.db.transaction() as db:
            clip = (await rows(db, "SELECT * FROM clips WHERE id=?", (clip_id,)))[0]
            jobs = await rows(
                db, "SELECT id,kind,status,error FROM jobs WHERE clip_id=?", (clip_id,)
            )
            count = (
                await rows(
                    db,
                    "SELECT count(*) AS n FROM transcripts WHERE clip_id=? "
                    "AND encounter_id IS NOT NULL",
                    (clip_id,),
                )
            )[0]["n"]
        if clip["cancelled"]:
            state = "cancelled"
        elif any(j["status"] == "failed" for j in jobs):
            state = "failed"
        elif not clip["audio_done"]:
            state = "transcribing"
        elif not clip["attribution_final"]:
            state = "waiting_for_attribution"
        elif any(j["kind"] == "learning" and j["status"] in ("pending", "running") for j in jobs):
            state = "learning"
        elif count:
            state = "completed"
        else:
            state = "completed_without_attribution"
        return {"clip_id": clip_id, "status": state, "jobs": jobs}

    async def update_timeline(
        self,
        generation: str,
        timeline: list[Record],
        *,
        final: bool = False,
        cancel_unresolved: bool = False,
    ) -> None:
        stamp = milliseconds()
        async with self.db.transaction() as db:
            clips = await rows(
                db,
                "SELECT * FROM clips WHERE generation=? AND attribution_final=0 AND cancelled=0",
                (generation,),
            )
            for clip in clips:
                if cancel_unresolved:
                    if clip["path"]:
                        await db.execute("INSERT OR IGNORE INTO cleanup VALUES(?)", (clip["path"],))
                    await db.execute(
                        "UPDATE clips SET cancelled=1,path=NULL,timeline='[]' WHERE id=?",
                        (clip["id"],),
                    )
                    await db.execute(
                        "UPDATE jobs SET status='cancelled',lease_token=NULL,payload='{}' "
                        "WHERE clip_id=? AND status!='done'",
                        (clip["id"],),
                    )
                    continue
                # Session history may already have been trimmed for a delayed upload.
                # Preserve the original capture snapshot when no covering history remains.
                before = [p for p in timeline if p["ms"] <= clip["start_ms"]]
                points = ([before[-1]] if before else []) + [
                    p for p in timeline if clip["start_ms"] < p["ms"] <= clip["end_ms"]
                ]
                history = points if points else json.loads(clip["timeline"])
                expired = stamp >= clip["received_ms"] + self.wait_ms
                await db.execute(
                    "UPDATE clips SET timeline=? WHERE id=?", (json.dumps(history), clip["id"])
                )
                await self._resolve(db, clip, history, final=final or expired)

    async def _resolve(self, db, clip: Record, timeline: list[Record], *, final: bool) -> None:
        turns = await rows(db, "SELECT id,data FROM transcripts WHERE clip_id=?", (clip["id"],))
        pending = False
        for row in turns:
            turn = json.loads(row["data"])
            if turn.get("association", {}).get("status") not in (None, "pending"):
                continue
            association = associate_turn(turn, timeline, final=final)
            if (
                association["status"] == "unattributed"
                and association["reason"] == "initial_candidate"
            ):
                association["reason"] = (
                    "attribution_expired"
                    if milliseconds() >= clip["received_ms"] + self.wait_ms
                    else "identity_unresolved"
                )
            if association["status"] == "attributed":
                # The capture-time version is immutable even if a helper corrected
                # this profile while identity was being established.
                person = await rows(
                    db, "SELECT version FROM people WHERE id=?", (association["visitor_id"],)
                )
                if not person or person[0]["version"] != association["person_version"]:
                    association = {
                        "status": "unattributed",
                        "reason": "person_changed",
                        "visitor_id": None,
                        "encounter_id": None,
                    }
            turn["association"] = association
            pending |= association["status"] == "pending"
            await db.execute(
                "UPDATE transcripts SET data=?,encounter_id=?,expires_ms=? WHERE id=?",
                (
                    json.dumps(turn),
                    association.get("encounter_id"),
                    None if association["status"] == "attributed" else clip["expires_ms"],
                    row["id"],
                ),
            )
        if clip["audio_done"]:
            if not pending or final:
                await db.execute(
                    "UPDATE clips SET attribution_final=1,attribution_finalized_ms="
                    "COALESCE(attribution_finalized_ms,?) WHERE id=?",
                    (milliseconds(), clip["id"]),
                )
                await self._schedule_learning(db, clip)
        elif final:
            # Audio is allowed to finish after stop/restart using this frozen history.
            await db.execute(
                "UPDATE clips SET attribution_final=1,attribution_finalized_ms="
                "COALESCE(attribution_finalized_ms,?) WHERE id=?",
                (milliseconds(), clip["id"]),
            )

    async def _schedule_learning(self, db, clip: Record) -> None:
        groups: dict[str, list[Record]] = defaultdict(list)
        for row in await rows(
            db,
            "SELECT encounter_id,data FROM transcripts WHERE clip_id=? "
            "AND encounter_id IS NOT NULL ORDER BY start_ms,id",
            (clip["id"],),
        ):
            groups[row["encounter_id"]].append(json.loads(row["data"]))
        for eid, turns in groups.items():
            association = turns[0]["association"]
            if any(
                t["association"]["person_version"] != association["person_version"] for t in turns
            ):
                continue
            payload = {
                "visitor_id": association["visitor_id"],
                "person_version": association["person_version"],
                "voice_version": clip["voice_version"],
                "segment_ids": [t["id"] for t in turns],
                "start_ms": min(t["start_ms"] for t in turns),
                "end_ms": max(t["end_ms"] for t in turns),
            }
            await db.execute(
                "INSERT OR IGNORE INTO jobs(id,clip_id,kind,encounter_id,payload,"
                "created_at) VALUES(?,?,'learning',?,?,?)",
                (uid(), clip["id"], eid, json.dumps(payload), now()),
            )

    async def claim_job(self, worker_id: str, stamp: int | None = None) -> Record | None:
        stamp = milliseconds() if stamp is None else stamp
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE jobs SET status='failed',error='Retry limit reached',"
                "lease_token=NULL WHERE status='running' AND attempts>=3 AND lease_until<?",
                (stamp,),
            )
            found = await rows(
                db,
                "SELECT j.* FROM jobs j JOIN clips c ON c.id=j.clip_id "
                "WHERE c.cancelled=0 AND j.attempts<3 AND ((j.status='pending' AND j.next_at<=?) "
                "OR (j.status='running' AND j.lease_until<?)) "
                "AND (j.kind='audio' OR (NOT EXISTS(SELECT 1 FROM jobs running "
                "WHERE running.encounter_id=j.encounter_id AND running.id!=j.id "
                "AND running.status='running' AND running.lease_until>=?) "
                "AND NOT EXISTS(SELECT 1 FROM clips earlier "
                "WHERE earlier.generation=c.generation AND earlier.start_ms<c.start_ms "
                "AND earlier.cancelled=0 "
                "AND (earlier.audio_done=0 OR earlier.attribution_final=0)) "
                "AND NOT EXISTS(SELECT 1 FROM jobs e JOIN clips ec ON ec.id=e.clip_id "
                "WHERE e.encounter_id=j.encounter_id AND e.id!=j.id "
                "AND ec.start_ms<c.start_ms AND e.status IN ('pending','running','failed')))) "
                "ORDER BY c.received_ms,j.created_at,j.rowid LIMIT 1",
                (stamp, stamp, stamp),
            )
            if not found:
                return None
            job = found[0]
            token = worker_id + ":" + uid()
            await db.execute(
                "UPDATE jobs SET status='running',attempts=attempts+1,lease_token=?,"
                "lease_until=? WHERE id=?",
                (token, stamp + 180000, job["id"]),
            )
            clip = (await rows(db, "SELECT * FROM clips WHERE id=?", (job["clip_id"],)))[0]
        return {**job, "lease_token": token, "payload": json.loads(job["payload"]), "clip": clip}

    async def renew_lease(self, ident: str, token: str, stamp: int) -> bool:
        async with self.db.transaction() as db:
            result = await db.execute(
                "UPDATE jobs SET lease_until=? WHERE id=? AND lease_token=? AND status='running'",
                (stamp + 180000, ident, token),
            )
            return result.rowcount == 1

    async def fail_job(self, ident: str, token: str, error: str, stamp: int) -> None:
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,"
                "error=?,next_at=?,lease_token=NULL WHERE id=? AND lease_token=? "
                "AND status='running'",
                (error[:240], stamp + 5000, ident, token),
            )

    async def retry_job(self, ident: str) -> bool:
        async with self.db.transaction() as db:
            result = await db.execute(
                "UPDATE jobs SET status='pending',attempts=0,next_at=0,error=NULL "
                "WHERE id=? AND status='failed' "
                "AND clip_id IN (SELECT id FROM clips WHERE cancelled=0)",
                (ident,),
            )
            return result.rowcount == 1

    async def pending_jobs(self) -> list[Record]:
        async with self.db.transaction() as db:
            jobs = await rows(
                db,
                "SELECT id,clip_id,kind,status,attempts,error FROM jobs "
                "WHERE status IN ('pending','running','failed') ORDER BY created_at",
            )
            waiting = await rows(
                db,
                "SELECT id AS clip_id FROM clips WHERE audio_done=1 "
                "AND attribution_final=0 AND cancelled=0",
            )
        return jobs + [
            {
                "id": r["clip_id"],
                **r,
                "kind": "attribution",
                "status": "waiting_for_attribution",
                "attempts": 0,
                "error": None,
            }
            for r in waiting
        ]

    async def finish_audio(self, job: Record, audio: Record) -> bool:
        async with self.db.transaction() as db:
            if not await self._owns_job(db, job):
                return False
            clip = (await rows(db, "SELECT * FROM clips WHERE id=?", (job["clip_id"],)))[0]
            for source in audio["segments"]:
                turn = {
                    **source,
                    "start_ms": source["start_ms"] + clip["start_ms"],
                    "end_ms": source["end_ms"] + clip["start_ms"],
                    "association": source["association"]
                    if clip["input_kind"] == "conversation"
                    else {"status": "pending"},
                }
                await db.execute(
                    "INSERT OR IGNORE INTO transcripts "
                    "(id,clip_id,job_id,encounter_id,start_ms,data,expires_ms) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        turn["id"],
                        clip["id"],
                        job["id"],
                        turn["association"].get("encounter_id"),
                        turn["start_ms"],
                        json.dumps(turn),
                        None
                        if turn["association"].get("status") == "attributed"
                        else clip["expires_ms"],
                    ),
                )
            await db.execute(
                "UPDATE clips SET audio_done=1,voice_ready=?,audio_completed_ms=? WHERE id=?",
                (int(audio["voice_ready"]), milliseconds(), clip["id"]),
            )
            clip["audio_done"] = 1
            await self._resolve(
                db,
                clip,
                json.loads(clip["timeline"]),
                final=bool(clip["attribution_final"])
                or milliseconds() >= clip["received_ms"] + self.wait_ms,
            )
            await self._done(db, job, audio["metrics"])
        return True

    async def learning_segments(self, job: Record) -> list[Record]:
        async with self.db.transaction() as db:
            found = await rows(
                db,
                "SELECT id,data FROM transcripts WHERE clip_id=? AND encounter_id=? "
                "ORDER BY start_ms,id",
                (job["clip_id"], job["encounter_id"]),
            )
        wanted = set(job["payload"]["segment_ids"])
        return [json.loads(r["data"]) for r in found if r["id"] in wanted]

    async def finish_learning(self, job: Record, result: Record) -> bool:
        started = time.perf_counter()
        async with self.db.transaction() as db:
            if not await self._owns_job(db, job):
                return False
            payload = job["payload"]
            person = await rows(db, "SELECT * FROM people WHERE id=?", (payload["visitor_id"],))
            encounter = await rows(
                db,
                "SELECT * FROM encounters WHERE id=? AND person_id=?",
                (job["encounter_id"], payload["visitor_id"]),
            )
            voice = (await rows(db, "SELECT version,embeddings FROM user_voice WHERE id=1"))[0]
            clip = (await rows(db, "SELECT * FROM clips WHERE id=?", (job["clip_id"],)))[0]
            trusted = clip["input_kind"] == "conversation"
            allowed = bool(
                person
                and encounter
                and person[0]["version"] == payload["person_version"]
                and (trusted or voice["version"] == payload["voice_version"])
            )
            if not allowed:
                await db.execute(
                    "UPDATE jobs SET status='cancelled',lease_token=NULL,"
                    "error='Person or voice reference changed' WHERE id=?",
                    (job["id"],),
                )
                return False
            fact_owner = (
                person[0] if trusted or (voice["embeddings"] and clip["voice_ready"]) else None
            )
            await save_conversation_result(
                db, job["encounter_id"], job["id"], fact_owner, result, payload["end_ms"]
            )
            await self._done(db, job, result["metrics"])
        result["metrics"]["commit_ms"] = round((time.perf_counter() - started) * 1000, 2)
        async with self.db.transaction() as db:
            # Timing is optional observation data; forgetting between the claim
            # commit and this update must not recreate a deleted metrics row.
            await db.execute(
                "UPDATE job_metrics SET data=? WHERE job_id=?",
                (json.dumps(result["metrics"]), job["id"]),
            )
        self.db.revision += 1
        return True

    async def _owns_job(self, db, job: Record) -> bool:
        return bool(
            await rows(
                db,
                "SELECT j.id FROM jobs j JOIN clips c ON c.id=j.clip_id "
                "WHERE j.id=? AND j.lease_token=? AND j.status='running' AND c.cancelled=0",
                (job["id"], job["lease_token"]),
            )
        )

    async def _done(self, db, job: Record, metrics: Record) -> None:
        await db.execute(
            "INSERT OR REPLACE INTO job_metrics VALUES(?,?)", (job["id"], json.dumps(metrics))
        )
        await db.execute(
            "UPDATE jobs SET status='done',lease_token=NULL,error=NULL WHERE id=?", (job["id"],)
        )

    async def recover(self) -> None:
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE capture_sessions SET ended_at=? WHERE ended_at IS NULL", (now(),)
            )
            for encounter in await rows(db, "SELECT * FROM encounters WHERE ended_at IS NULL"):
                ends = [encounter["start_ms"]]
                for row in await rows(
                    db, "SELECT data FROM transcripts WHERE encounter_id=?", (encounter["id"],)
                ):
                    ends.append(json.loads(row["data"])["end_ms"])
                for row in await rows(
                    db, "SELECT timeline FROM clips WHERE generation=?", (encounter["generation"],)
                ):
                    ends.extend(
                        point["ms"]
                        for point in json.loads(row["timeline"])
                        if point.get("encounter_id") == encounter["id"]
                    )
                await db.execute(
                    "UPDATE encounters SET ended_at=?,end_ms=? WHERE id=?",
                    (now(), max(ends), encounter["id"]),
                )
            for clip in await rows(
                db, "SELECT * FROM clips WHERE attribution_final=0 AND cancelled=0"
            ):
                await self._resolve(db, clip, json.loads(clip["timeline"]), final=True)
            await db.execute(
                "UPDATE jobs SET status='failed',lease_token=NULL,"
                "error='Retry limit reached' WHERE status='running' AND attempts>=3"
            )
            # The previous process cannot still own a lease after startup.
            await db.execute(
                "UPDATE jobs SET status='pending',lease_token=NULL,lease_until=0 "
                "WHERE status='running' AND attempts<3"
            )

    async def expire(self, stamp: int | None = None) -> None:
        stamp = milliseconds() if stamp is None else stamp
        async with self.db.transaction() as db:
            for clip in await rows(
                db,
                "SELECT * FROM clips WHERE attribution_final=0 AND cancelled=0 "
                "AND received_ms+?<=?",
                (self.wait_ms, stamp),
            ):
                await self._resolve(db, clip, json.loads(clip["timeline"]), final=True)
            for clip in await rows(db, "SELECT id,path FROM clips WHERE expires_ms<=?", (stamp,)):
                if clip["path"]:
                    await db.execute("INSERT OR IGNORE INTO cleanup VALUES(?)", (clip["path"],))
                await db.execute(
                    "UPDATE clips SET path=NULL,timeline='[]' WHERE id=?", (clip["id"],)
                )
                await db.execute(
                    "UPDATE jobs SET status='cancelled',lease_token=NULL,error='Media expired' "
                    "WHERE clip_id=? AND kind='audio' AND status IN ('pending','running','failed')",
                    (clip["id"],),
                )
            await db.execute(
                "DELETE FROM transcripts WHERE expires_ms IS NOT NULL AND expires_ms<=?", (stamp,)
            )
