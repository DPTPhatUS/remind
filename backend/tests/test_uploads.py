"""Concurrent recording intake with real HTTP streaming and isolated persistence."""

import asyncio
import errno
import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from remind.app import create_app
from remind.config import Settings
from remind.runtime import Runtime


@pytest.fixture
async def uploads(tmp_path, monkeypatch, request):
    settings = Settings(
        data_dir=tmp_path, openai_api_key="test", spool_limit_bytes=getattr(request, "param", 10)
    )
    monkeypatch.setattr("remind.runtime.Providers", lambda _: SimpleNamespace(close=AsyncMock()))
    runtime = Runtime(settings, verifier=object())
    await runtime.database.create_schema()
    runtime.session = SimpleNamespace(
        generation="capture",
        forgotten=False,
        stopped=False,
        last_heartbeat=0,
        snapshot=AsyncMock(return_value={"timeline": [], "voice_version": 0}),
    )
    monkeypatch.setattr("remind.app.Runtime", lambda *args: runtime)
    # Keep the real intake path; background model processing is outside these tests.
    transport = httpx.ASGITransport(app=create_app(settings))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield SimpleNamespace(client=client, runtime=runtime, directory=tmp_path / "spool")
    finally:
        await runtime.providers.close()
        runtime.memory_pool.shutdown(wait=True)
        runtime.vision_pool.shutdown(wait=True)
        await runtime.database.close()


def metadata(window, start=0):
    return {
        "metadata": json.dumps(
            {
                "window_id": window,
                "start_ms": start,
                "end_ms": start + 1000,
            }
        )
    }


async def test_concurrent_uploads_cannot_exceed_storage_limit(uploads):
    arrived = 0
    ready = asyncio.Event()

    async def body():
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), 2)
        yield b"12345678"

    responses = await asyncio.gather(
        *(
            uploads.client.post("/api/live/capture/clips", params=metadata(str(i)), content=body())
            for i in range(2)
        )
    )

    assert sorted(response.status_code for response in responses) == [200, 507]
    assert sum(path.stat().st_size for path in uploads.directory.iterdir()) == 8
    assert len(await uploads.runtime.jobs.pending()) == 1


@pytest.mark.parametrize(
    ("uploads", "first", "tail", "competing"),
    [(10, b"1234", b"56", b"abcd"), (25000, b"x" * 17000, b"x" * 1000, b"y" * 7000)],
    indirect=["uploads"],
    ids=["buffered", "flushed"],
)
async def test_slow_upload_does_not_block_or_double_count(uploads, first, tail, competing):
    stalled = asyncio.Event()
    resume = asyncio.Event()

    async def body():
        yield first
        stalled.set()
        await resume.wait()
        yield tail

    slow = asyncio.create_task(
        uploads.client.post("/api/live/capture/clips", params=metadata("slow"), content=body())
    )
    try:
        await asyncio.wait_for(stalled.wait(), 2)
        other = await asyncio.wait_for(
            uploads.client.post(
                "/api/live/capture/clips", params=metadata("other"), content=competing
            ),
            2,
        )
        assert other.status_code == 200
    finally:
        resume.set()
        result = await slow

    assert result.status_code == 200
    assert sum(path.stat().st_size for path in uploads.directory.iterdir()) == (
        len(first) + len(tail) + len(competing)
    )


async def test_cancelled_upload_releases_buffered_reservations(uploads):
    stalled = asyncio.Event()

    async def body():
        yield b"12345678"
        stalled.set()
        await asyncio.Event().wait()

    pending = asyncio.create_task(
        uploads.client.post("/api/live/capture/clips", params=metadata("cancelled"), content=body())
    )
    try:
        await asyncio.wait_for(stalled.wait(), 2)
        rejected = await uploads.client.post(
            "/api/live/capture/clips", params=metadata("blocked"), content=b"abcd"
        )
        assert rejected.status_code == 507
    finally:
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

    assert list(uploads.directory.iterdir()) == []
    response = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("retry"), content=b"12345678"
    )
    assert response.status_code == 200


async def test_interrupted_upload_releases_space(uploads):
    async def body():
        yield b"12345678"
        raise OSError("connection lost")

    with pytest.raises(ExceptionGroup) as failure:
        await uploads.client.post(
            "/api/live/capture/clips", params=metadata("interrupted"), content=body()
        )

    assert isinstance(failure.value.exceptions[0], OSError)
    assert str(failure.value.exceptions[0]) == "connection lost"

    assert list(uploads.directory.iterdir()) == []
    response = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("retry"), content=b"12345678"
    )
    assert response.status_code == 200


async def test_write_failure_removes_partial_file_and_releases_reservation(uploads, monkeypatch):
    async def body():
        yield b"12345678"

    open_file = Path.open

    @contextmanager
    def fail_write(path, *args, **kwargs):
        with open_file(path, *args, **kwargs) as recording:

            def write(chunk):
                recording.write(chunk[:2])
                raise OSError(errno.ENOSPC, "No space left on device")

            yield SimpleNamespace(write=write)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "open", fail_write)
        with pytest.raises(OSError, match="No space left on device"):
            await uploads.runtime.spool.save(body())

    assert list(uploads.directory.iterdir()) == []
    accepted = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("accepted"), content=b"12345678"
    )
    assert accepted.status_code == 200


async def test_failed_partial_file_deletion_stays_counted_until_cleanup(
    uploads, monkeypatch, caplog
):
    async def body():
        yield b"12345678"
        raise OSError("connection lost")

    unlink = Path.unlink

    def fail(path, *args, **kwargs):
        if path.parent == uploads.directory:
            raise PermissionError("recording locked")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", fail)
        with pytest.raises(ExceptionGroup) as failure:
            await uploads.client.post(
                "/api/live/capture/clips", params=metadata("interrupted"), content=body()
            )

    assert isinstance(failure.value.exceptions[0], OSError)
    assert str(failure.value.exceptions[0]) == "connection lost"
    assert "Could not remove incomplete recording" in caplog.text
    (remaining,) = uploads.directory.iterdir()
    assert remaining.stat().st_size == 8
    rejected = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("blocked"), content=b"abcd"
    )
    assert rejected.status_code == 507
    os.utime(remaining, (0, 0))
    await uploads.runtime.worker.cleanup()
    accepted = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("after-cleanup"), content=b"12345678"
    )
    assert accepted.status_code == 200


async def test_existing_recordings_count_after_quota_coordinator_restart(uploads):
    from remind.spool import RecordingSpool

    uploads.directory.mkdir()
    recording = uploads.directory / "unfinished.webm"
    recording.write_bytes(b"12345678")
    uploads.runtime.spool = RecordingSpool(uploads.directory, 10)
    rejected = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("blocked"), content=b"abcd"
    )
    assert rejected.status_code == 507
    recording.unlink()
    accepted = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("accepted"), content=b"12345678"
    )
    assert accepted.status_code == 200


async def test_duplicate_media_stays_counted_until_successful_deletion(uploads, monkeypatch):
    original = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("same"), content=b"1234"
    )
    duplicate = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("same"), content=b"1234"
    )
    assert duplicate.json() == original.json()
    (pending,) = await uploads.runtime.store.pending_cleanup()
    unlink = Path.unlink

    def fail(path, *args, **kwargs):
        if str(path) == pending:
            raise PermissionError("recording locked")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", fail)
        await uploads.runtime.worker.cleanup()
    rejected = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("new"), content=b"abcd"
    )
    assert rejected.status_code == 507
    await uploads.runtime.worker.cleanup()
    accepted = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("new"), content=b"abcd"
    )
    assert accepted.status_code == 200
    assert len(await uploads.runtime.jobs.pending()) == 2


async def test_skipped_media_releases_capacity_when_cleanup_removes_it(uploads):
    store = uploads.runtime.store
    person = await store.create_person()
    encounter = await store.start_encounter("capture", person["id"], 1000)
    await uploads.runtime.captures.receive_transcript_batch(
        encounter,
        "newer",
        1000,
        2000,
        [
            {
                "id": "turn",
                "start_ms": 1100,
                "end_ms": 1900,
                "role": "visitor",
                "text": "I enjoy gardening.",
            }
        ],
    )
    skipped = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("older"), content=b"12345678"
    )
    assert skipped.json()["status"] == "skipped"
    rejected = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("latest", 3000), content=b"abcd"
    )
    assert rejected.status_code == 507
    await uploads.runtime.worker.cleanup()
    accepted = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("latest", 3000), content=b"12345678"
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "transcribing"


@pytest.mark.parametrize("uploads", [32 * 1024 * 1024], indirect=True)
async def test_oversized_upload_keeps_413_and_releases_its_file(uploads):
    response = await uploads.client.post(
        "/api/live/capture/clips",
        params=metadata("too-large"),
        content=b"x" * (16 * 1024 * 1024 + 1),
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "Clip exceeds 16 MiB"
    assert list(uploads.directory.iterdir()) == []
    accepted = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("accepted"), content=b"12345678"
    )
    assert accepted.status_code == 200


async def test_rejected_intake_removes_media_and_releases_space(uploads, monkeypatch):
    with monkeypatch.context() as scoped:
        scoped.setattr(
            uploads.runtime.captures, "receive_clip", AsyncMock(side_effect=ValueError("forgotten"))
        )
        response = await uploads.client.post(
            "/api/live/capture/clips", params=metadata("rejected"), content=b"12345678"
        )
    assert response.status_code == 409
    assert list(uploads.directory.iterdir()) == []
    accepted = await uploads.client.post(
        "/api/live/capture/clips", params=metadata("accepted"), content=b"12345678"
    )
    assert accepted.status_code == 200
