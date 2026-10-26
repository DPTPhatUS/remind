import asyncio
import sqlite3

import pytest

from remind.database import Database, rows


@pytest.mark.parametrize("error", [ValueError("cancel save"), asyncio.CancelledError()])
async def test_failed_transaction_rolls_back_and_releases_lock(store, error):
    with pytest.raises(type(error)):
        async with store.db.transaction() as connection:
            await connection.execute(
                "INSERT INTO people(id,name,created_at) VALUES(?,?,?)",
                ("interrupted", "Anna", "2026-10-27T00:00:00+00:00"),
            )
            raise error
    assert await store.list_people() == []
    assert (await store.create_person("Anne"))["name"] == "Anne"


async def test_open_close_guards_preserve_the_current_connection(tmp_path):
    database = Database(tmp_path / "nested" / "memory.db")
    with pytest.raises(RuntimeError, match="not open"):
        async with database.transaction():
            pytest.fail("A closed database must not start a transaction")
    await database.create_schema()
    try:
        with pytest.raises(RuntimeError, match="already open"):
            await database.create_schema()
        async with database.transaction() as connection:
            assert await rows(connection, "SELECT version FROM user_voice") == [{"version": 0}]
    finally:
        await database.close()
    await database.close()
    with pytest.raises(RuntimeError, match="not open"):
        async with database.transaction():
            pytest.fail("A closed database must not start a transaction")


async def test_foreign_keys_reject_orphan_records_without_breaking_later_writes(store):
    with pytest.raises(sqlite3.IntegrityError):
        await store.add_participant("missing-encounter", "missing-person", "track", 0)
    person = await store.create_person("Anna")
    encounter = await store.start_encounter("session")
    await store.add_participant(encounter, person["id"], "track", 0)
    assert (await store.get_encounter(encounter))["id"] == encounter
