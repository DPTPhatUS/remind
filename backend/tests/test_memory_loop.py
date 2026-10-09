"""Deterministic logic test: injected media/providers, real SQLite and live session."""

import numpy as np

from remind.config import Settings
from remind.database import Database
from remind.live.session import LiveSession
from remind.memory.store import MemoryStore
from remind.memory.worker import MemoryWorker


async def test_introduction_worker_restart_and_recall(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, openai_api_key="")
    db = Database(str(tmp_path / "memory.db"))
    await db.create_schema()
    store = MemoryStore(db)
    session = LiveSession("first", store, settings)
    vector = np.eye(128, dtype=np.float32)[0]
    observation = {
        "box": [0.3, 0.2, 0.3, 0.4],
        "embedding": vector,
        "quality": True,
        "thumbnail": b"x",
    }
    for stamp in range(0, 3000, 100):
        tracks = await session.observe([observation], stamp)
    pid = tracks[0]["person_id"]
    snapshot = await session.snapshot(0, 3000)
    assert snapshot["timeline"][0]["people"][0]["person_id"] == pid
    await store.enqueue_job(
        snapshot["encounter"], "intro", {**snapshot, "clip_path": "injected.webm"}
    )
    segments = [
        {"id": "s", "speaker": "A", "text": "My name is Anna.", "start_ms": 200, "end_ms": 1200}
    ]

    class Provider:
        async def transcribe(self, pcm):
            return segments

        async def extract(self, received, mapping, previous):
            assert mapping == {"A": pid}
            return {
                "summary": "Anna visited and introduced herself.",
                "facts": [
                    {
                        "person_id": pid,
                        "predicate": "name",
                        "value": "Anna",
                        "segment_ids": ["s"],
                        "quote": "My name is Anna.",
                    }
                ],
            }

        async def close(self):
            pass

    class Speaker:
        def evidence(self, media, received, vision, gallery, timeline, start):
            assert timeline == snapshot["timeline"]
            assert gallery.match(vector).person_id == pid
            return [{"segment_id": "s", "person_id": pid, "score": 0.99, "coverage": 1}]

    class Vad:
        def accept(self, *args):
            return [True]

        def flush(self):
            return None

    monkeypatch.setattr(
        "remind.memory.worker.decode_clip", lambda _: {"pcm": np.ones(16000, dtype=np.int16)}
    )
    monkeypatch.setattr("remind.memory.worker.AudioWindowBuffer", Vad)
    worker = MemoryWorker(store, settings, None)
    worker.providers = Provider()
    worker.speaker = Speaker()
    assert await worker.run_once()
    await worker.close()
    await session.stop()
    await db.close()

    reopened = Database(str(tmp_path / "memory.db"))
    await reopened.create_schema()
    returning = LiveSession("return", MemoryStore(reopened), settings)
    for stamp in (0, 100, 200):
        tracks = await returning.observe([observation], stamp)
    memory = tracks[0]["memory"]
    assert memory["name"] == "Anna"
    assert memory["last_encounter"]["summary"] == "Anna visited and introduced herself."
    assert memory["last_encounter"]["id"] == snapshot["encounter"]
    await returning.stop()
    await reopened.close()
