import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from remind.config import Settings
from remind.runtime import Runtime


@pytest.fixture
async def runtime_factory(tmp_path, monkeypatch):
    events = []
    runtimes = []
    providers = []

    def create_provider(settings):
        provider = SimpleNamespace(
            close=AsyncMock(side_effect=lambda: events.append("provider closed"))
        )
        providers.append(provider)
        return provider

    def create_pool(*, max_workers, thread_name_prefix):
        assert max_workers == 1
        pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=thread_name_prefix)
        shutdown = pool.shutdown

        def close(*, wait):
            events.append(f"{thread_name_prefix} pool closed")
            shutdown(wait=wait)

        monkeypatch.setattr(pool, "shutdown", close)
        return pool

    monkeypatch.setattr("remind.runtime.Providers", create_provider)
    monkeypatch.setattr("remind.runtime.ThreadPoolExecutor", create_pool)
    monkeypatch.setattr("remind.runtime.OpenCVVision", lambda *args: object())

    def create(api_key="test"):
        runtime = Runtime(Settings(data_dir=tmp_path, openai_api_key=api_key), verifier=object())
        close_database = runtime.database.close

        async def close():
            events.append("database closed")
            await close_database()

        monkeypatch.setattr(runtime.database, "close", close)
        runtimes.append(runtime)
        return runtime

    yield create, events, providers

    for runtime in runtimes:
        runtime.memory_pool.shutdown(wait=True)
        runtime.vision_pool.shutdown(wait=True)
        await runtime.database.close()


@pytest.mark.parametrize("api_key", ["test", ""])
async def test_runtime_supplies_and_closes_shared_resources(runtime_factory, monkeypatch, api_key):
    create, events, providers = runtime_factory
    runtime = create(api_key)
    assert runtime.worker.verifier is runtime.verifier
    assert runtime.worker.pool is runtime.memory_pool
    assert runtime.worker.providers is runtime.providers
    assert providers == ([runtime.providers] if api_key else [])
    claim = AsyncMock(return_value=None)
    monkeypatch.setattr(runtime.jobs, "claim", claim)

    async with runtime.lifespan(None):
        assert await runtime.worker.run_once() is False
        if not api_key:
            claim.assert_not_awaited()
            assert runtime.worker.speaker_status == "Conversation processing needs API key"

    assert events == (["provider closed"] if api_key else []) + [
        "memory pool closed", "vision pool closed", "database closed"
    ]
    if api_key:
        runtime.providers.close.assert_awaited_once()
    assert runtime.database.connection is None
    with pytest.raises(RuntimeError, match="cannot schedule new futures after shutdown"):
        runtime.memory_pool.submit(lambda: None)


@pytest.mark.parametrize("stop_fails", [False, True])
async def test_shutdown_stops_session_and_awaits_tasks_before_closing_resources(
    runtime_factory, monkeypatch, stop_fails
):
    create, events, _ = runtime_factory
    runtime = create()
    started = [asyncio.Event(), asyncio.Event()]
    cancelling = [asyncio.Event(), asyncio.Event()]
    finish_cancellation = asyncio.Event()

    async def background(index):
        started[index].set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelling[index].set()
            await finish_cancellation.wait()
            events.append(f"task {index} stopped")

    monkeypatch.setattr(runtime, "maintain_memory", lambda: background(0))
    monkeypatch.setattr(runtime, "watch_session", lambda: background(1))

    async def stop():
        events.append("session stopped")
        if stop_fails:
            raise RuntimeError("session stop")

    runtime.session = SimpleNamespace(stop=stop)
    lifecycle = runtime.lifespan(None)
    await lifecycle.__aenter__()
    await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started)), 1)
    shutdown = asyncio.create_task(lifecycle.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in cancelling)), 1)
        assert events == ["session stopped"]
    finally:
        finish_cancellation.set()
        with pytest.raises(RuntimeError, match="session stop") if stop_fails else nullcontext():
            await shutdown

    assert set(events[1:3]) == {"task 0 stopped", "task 1 stopped"}
    assert events[3:] == [
        "provider closed", "memory pool closed", "vision pool closed", "database closed"
    ]


async def test_startup_failure_closes_resources(runtime_factory, monkeypatch):
    create, events, _ = runtime_factory
    runtime = create()
    monkeypatch.setattr(runtime.captures, "recover", AsyncMock(side_effect=RuntimeError("recover")))

    with pytest.raises(RuntimeError, match="recover"):
        async with runtime.lifespan(None):
            pytest.fail("Startup should not succeed")

    assert events == [
        "provider closed", "memory pool closed", "vision pool closed", "database closed"
    ]
    assert runtime.database.connection is None


async def test_provider_close_failure_still_closes_all_resources(runtime_factory):
    create, events, _ = runtime_factory
    runtime = create()
    runtime.providers.close.side_effect = RuntimeError("provider close")

    with pytest.raises(RuntimeError, match="provider close"):
        async with runtime.lifespan(None):
            pass

    assert events == ["memory pool closed", "vision pool closed", "database closed"]
    assert runtime.database.connection is None
    for pool in (runtime.memory_pool, runtime.vision_pool):
        with pytest.raises(RuntimeError, match="cannot schedule new futures after shutdown"):
            pool.submit(lambda: None)


@pytest.mark.parametrize("pool_name", ["memory_pool", "vision_pool"])
async def test_executor_shutdown_failure_still_closes_remaining_resources(
    runtime_factory, monkeypatch, pool_name
):
    create, events, _ = runtime_factory
    runtime = create()
    pool = getattr(runtime, pool_name)
    shutdown = pool.shutdown

    def fail(*, wait):
        shutdown(wait=wait)
        raise RuntimeError("executor shutdown")

    with monkeypatch.context() as scoped:
        scoped.setattr(pool, "shutdown", fail)
        with pytest.raises(RuntimeError, match="executor shutdown"):
            async with runtime.lifespan(None):
                pass

    assert events == [
        "provider closed", "memory pool closed", "vision pool closed", "database closed"
    ]
    assert runtime.database.connection is None


async def test_shutdown_failure_preserves_original_error_context(runtime_factory):
    create, events, _ = runtime_factory
    runtime = create()
    runtime.providers.close.side_effect = RuntimeError("provider close")
    original = ValueError("application failure")

    with pytest.raises(RuntimeError, match="provider close") as failure:
        async with runtime.lifespan(None):
            raise original

    assert failure.value.__context__ is original
    assert events == ["memory pool closed", "vision pool closed", "database closed"]
