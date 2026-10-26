import pytest

from remind.database import Database
from remind.memory.store import MemoryStore


@pytest.fixture
async def store(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.create_schema()
    store = MemoryStore(db)
    yield store
    await db.close()
