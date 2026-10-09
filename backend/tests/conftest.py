import pytest

from remind.database import Database
from remind.memory.store import MemoryStore


@pytest.fixture
async def store(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await db.create_schema()
    store = MemoryStore(db)
    await store.ensure_patient()
    yield store
    await db.close()
