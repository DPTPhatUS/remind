"""Durable job leasing, retries and status; stage results belong to CaptureStore."""

import json
import time

from remind.database import Database, Record, rows
from remind.memory.contracts import ClaimedJob, JobFields
from remind.memory.store import uid


class JobQueue:
    def __init__(self, db: Database):
        self.db = db

    async def claim(self, worker_id: str, stamp: int | None = None) -> ClaimedJob | None:
        stamp = int(time.time() * 1000) if stamp is None else stamp
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE jobs SET status='failed',error='Retry limit reached',"
                "lease_token=NULL WHERE status='running' AND attempts>=3 AND lease_until<?",
                (stamp,),
            )
            found = await rows(
                db,
                """
                SELECT j.* FROM jobs j JOIN clips c ON c.id=j.clip_id
                WHERE c.cancelled=0 AND j.attempts<3
                  AND ((j.status='pending' AND j.next_at<=?)
                       OR (j.status='running' AND j.lease_until<?))
                  AND (j.kind='audio' OR (
                    NOT EXISTS (
                      SELECT 1 FROM jobs running
                      WHERE running.encounter_id=j.encounter_id AND running.id!=j.id
                        AND running.status='running' AND running.lease_until>=?
                    )
                    AND NOT EXISTS (
                      SELECT 1 FROM clips earlier
                      WHERE earlier.generation=c.generation AND earlier.start_ms<c.start_ms
                        AND earlier.cancelled=0
                        AND (
                          (earlier.audio_done=1 AND earlier.attribution_final=0)
                          OR (earlier.audio_done=0 AND EXISTS (
                            SELECT 1 FROM jobs audio
                            WHERE audio.clip_id=earlier.id AND audio.kind='audio'
                              AND audio.status IN ('pending','running')
                          ))
                        )
                    )
                    AND NOT EXISTS (
                      SELECT 1 FROM jobs e JOIN clips ec ON ec.id=e.clip_id
                      WHERE e.encounter_id=j.encounter_id AND e.id!=j.id
                        AND ec.start_ms<c.start_ms AND e.status IN ('pending','running')
                    )
                  ))
                ORDER BY c.received_ms,j.created_at,j.rowid LIMIT 1
                """,
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
        common: JobFields = {
            "id": job["id"],
            "clip_id": job["clip_id"],
            "lease_token": token,
        }
        if job["kind"] == "audio":
            return {
                **common,
                "kind": "audio",
                "clip": {
                    "path": clip["path"],
                    "voice_version": clip["voice_version"],
                },
            }
        return {
            **common,
            "kind": "learning",
            "encounter_id": job["encounter_id"],
            "payload": json.loads(job["payload"]),
            "clip": {
                "voice_ready": clip["voice_ready"],
                "input_kind": clip["input_kind"],
                "received_ms": clip["received_ms"],
                "audio_completed_ms": clip["audio_completed_ms"],
                "attribution_finalized_ms": clip["attribution_finalized_ms"],
            },
        }

    async def renew(self, ident: str, token: str, stamp: int) -> bool:
        async with self.db.transaction() as db:
            result = await db.execute(
                "UPDATE jobs SET lease_until=? WHERE id=? AND lease_token=? AND status='running'",
                (stamp + 180000, ident, token),
            )
            return result.rowcount == 1

    async def fail(self, ident: str, token: str, error: str, stamp: int) -> None:
        async with self.db.transaction() as db:
            await db.execute(
                "UPDATE jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,"
                "error=?,next_at=?,lease_token=NULL WHERE id=? AND lease_token=? "
                "AND status='running'",
                (error[:240], stamp + 5000, ident, token),
            )

    async def pending(self) -> list[Record]:
        async with self.db.transaction() as db:
            jobs = await rows(
                db,
                "SELECT id,clip_id,kind,status,attempts,error FROM jobs "
                "WHERE status IN ('pending','running','failed','skipped') ORDER BY created_at",
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
