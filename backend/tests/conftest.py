import pytest

from remind.database import Database
from remind.memory.capture import CaptureStore
from remind.memory.jobs import JobQueue
from remind.memory.store import MemoryStore


@pytest.fixture
async def store(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.create_schema()
    store = MemoryStore(db)
    yield store
    await db.close()


@pytest.fixture
def captures(store):
    return CaptureStore(store, JobQueue(store.db))
