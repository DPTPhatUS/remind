import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS patient(id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL);
INSERT OR IGNORE INTO patient VALUES(1,'You');
CREATE TABLE IF NOT EXISTS people(
 id TEXT PRIMARY KEY, name TEXT, relationship TEXT, age TEXT, notes TEXT,
 version INTEGER NOT NULL DEFAULT 1, manual TEXT NOT NULL DEFAULT '[]',
 profile_summary TEXT NOT NULL DEFAULT '', highlights TEXT NOT NULL DEFAULT '[]',
 created_at TEXT NOT NULL, thumbnail BLOB);
CREATE TABLE IF NOT EXISTS user_voice(
 id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL DEFAULT 0,
 model TEXT, embeddings TEXT, created_at TEXT, updated_at TEXT);
INSERT OR IGNORE INTO user_voice(id) VALUES(1);
CREATE TABLE IF NOT EXISTS templates(
 id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
 model TEXT NOT NULL, embedding BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS encounters(
 id TEXT PRIMARY KEY, generation TEXT NOT NULL, started_at TEXT NOT NULL,
 ended_at TEXT, summary TEXT, summary_order REAL NOT NULL DEFAULT -1);
CREATE TABLE IF NOT EXISTS participants(
 encounter_id TEXT REFERENCES encounters(id) ON DELETE CASCADE,
 person_id TEXT REFERENCES people(id) ON DELETE CASCADE, track_id TEXT,
 start_ms REAL NOT NULL, end_ms REAL,
 PRIMARY KEY(encounter_id,person_id,track_id,start_ms));
CREATE TABLE IF NOT EXISTS jobs(
 id TEXT PRIMARY KEY, encounter_id TEXT REFERENCES encounters(id) ON DELETE CASCADE,
 window_key TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0, lease_token TEXT, lease_until INTEGER DEFAULT 0,
 next_at INTEGER DEFAULT 0, error TEXT, created_at TEXT NOT NULL,
 UNIQUE(encounter_id,window_key));
CREATE TABLE IF NOT EXISTS transcripts(
 id TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
 encounter_id TEXT REFERENCES encounters(id) ON DELETE CASCADE,
 start_ms REAL NOT NULL DEFAULT 0, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facts(
 id TEXT PRIMARY KEY, person_id TEXT REFERENCES people(id) ON DELETE CASCADE,
 encounter_id TEXT REFERENCES encounters(id) ON DELETE CASCADE,
 job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
 subject TEXT NOT NULL, category TEXT NOT NULL, predicate TEXT NOT NULL, value TEXT NOT NULL,
 temporal_status TEXT NOT NULL DEFAULT 'current', valid_from TEXT, valid_to TEXT,
 status TEXT NOT NULL DEFAULT 'accepted', manual INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fact_evidence(
 fact_id TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
 segment_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
 quote TEXT NOT NULL, PRIMARY KEY(fact_id,segment_id,quote));
CREATE TABLE IF NOT EXISTS job_metrics(
 job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS invalidated_encounters(id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS cleanup(path TEXT PRIMARY KEY);
CREATE INDEX IF NOT EXISTS participants_person ON participants(person_id,encounter_id);
CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(status,next_at);
CREATE INDEX IF NOT EXISTS transcripts_encounter ON transcripts(encounter_id,start_ms);
CREATE INDEX IF NOT EXISTS facts_person ON facts(person_id,status);
"""


class Database:
    def __init__(self, url: str):
        self.path = url.removeprefix("sqlite+aiosqlite:///")
        self.lock = asyncio.Lock()
        self.connection: aiosqlite.Connection | None = None
        self.revision = 0

    async def create_schema(self):
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("PRAGMA busy_timeout=5000")
        await self.connection.executescript(SCHEMA)
        await self.connection.commit()

    @asynccontextmanager
    async def transaction(self):
        async with self.lock:
            assert self.connection is not None
            try:
                yield self.connection
                await self.connection.commit()
            except BaseException:
                await self.connection.rollback()
                raise

    async def close(self):
        if self.connection:
            await self.connection.close()
            self.connection = None
