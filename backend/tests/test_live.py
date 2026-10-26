import json
import struct
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

from remind.config import Settings
from remind.live.protocol import decode_packet
from remind.live.queues import LatestQueue
from remind.live.session import LiveSession
from remind.live.stream import serve_vision


def test_packet_rejects_invalid_lengths_and_nonfinite_time():
    with pytest.raises(ValueError):
        decode_packet(b"abc")
    with pytest.raises(ValueError):
        decode_packet(struct.pack(">I", 999999) + b"{}")
    header = json.dumps(
        {"version": 1, "generation": "a", "sequence": 1, "capture_ms": float("nan")}
    ).encode()
    with pytest.raises(ValueError):
        decode_packet(struct.pack(">I", len(header)) + header + b"x")


@pytest.mark.parametrize("field", ["version", "sequence", "capture_ms"])
def test_packet_rejects_booleans_as_numbers(field):
    header = {"version": 1, "generation": "a", "sequence": 1, "capture_ms": 0}
    header[field] = True
    encoded = json.dumps(header).encode()
    with pytest.raises(ValueError):
        decode_packet(struct.pack(">I", len(encoded)) + encoded + b"image")


@pytest.mark.parametrize("header", [b"null", b"[]", b"\xff"])
def test_packet_rejects_non_object_or_invalid_utf8_header(header):
    with pytest.raises(ValueError):
        decode_packet(struct.pack(">I", len(header)) + header + b"image")


async def test_queue_keeps_only_latest():
    queue = LatestQueue()
    for i in range(100):
        queue.put(i)
    assert await queue.get() == 99
    assert queue.dropped == 99


def test_vision_stream_rejects_stale_frames_malformed_packets_and_stopped_sessions():
    session = SimpleNamespace(
        generation="one", stopped=False, last_heartbeat=0, observe=AsyncMock(return_value=[])
    )
    engine = SimpleNamespace(detect=Mock(return_value=[]))
    app = FastAPI()

    def packet(sequence, generation="one"):
        header = json.dumps(
            {"version": 1, "generation": generation, "sequence": sequence, "capture_ms": 100}
        ).encode()
        return struct.pack(">I", len(header)) + header + b"frame"

    with ThreadPoolExecutor(max_workers=1) as pool:

        @app.websocket("/vision")
        async def vision(socket: WebSocket):
            await socket.accept()
            await serve_vision(socket, session, engine, pool)

        with TestClient(app) as client:
            with client.websocket_connect("/vision") as socket:
                socket.send_bytes(packet(99, generation="old"))
                socket.send_bytes(packet(2))
                assert socket.receive_json()["sequence"] == 2
                socket.send_bytes(packet(1))
                socket.send_bytes(packet(3))
                assert socket.receive_json()["sequence"] == 3
                socket.send_bytes(b"malformed")
                with pytest.raises(WebSocketDisconnect) as disconnected:
                    socket.receive_json()
                assert disconnected.value.code == 1008
            session.stopped = True
            with client.websocket_connect("/vision") as socket:
                socket.send_bytes(packet(4))
                with pytest.raises(WebSocketDisconnect) as disconnected:
                    socket.receive_json()
                assert disconnected.value.code == 1000

    assert engine.detect.call_count == 2
    assert session.observe.await_count == 2
    assert session.last_heartbeat > 0


async def test_enroll_return_and_wrong_generation(store):
    session = LiveSession("one", store, Settings())
    feature = np.zeros(128, dtype=np.float32)
    feature[0] = 1
    observations = [
        {"box": [0.3, 0.2, 0.3, 0.4], "embedding": feature, "quality": True, "thumbnail": b"x"}
    ]
    for t in range(0, 2100, 100):
        output = await session.observe(observations, t)
    assert output[0]["person_id"]
    person_id = output[0]["person_id"]
    assert len(await store.list_people()) == 1
    await session.stop()
    fresh = LiveSession("two", store, Settings())
    for t in [0, 100, 200]:
        output = await fresh.observe(observations, t)
    assert output[0]["person_id"] == person_id
    assert output[0]["memory"]["last_encounter"]["id"] == session.encounter
    await fresh.stop()


async def test_bad_face_does_not_inherit_identity(store):
    session = LiveSession("one", store, Settings())
    v = np.zeros(128, dtype=np.float32)
    v[0] = 1
    obs = {"box": [0.3, 0.2, 0.3, 0.4], "embedding": v, "quality": True, "thumbnail": b"x"}
    for t in range(0, 2100, 100):
        await session.observe([obs], t)
    output = await session.observe([{**obs, "quality": False, "embedding": None}], 2200)
    assert not any(t["person_id"] for t in output)
    await session.stop()


async def test_delayed_clip_retains_original_encounter(store):
    session = LiveSession("one", store, Settings())
    feature = np.zeros(128, dtype=np.float32)
    feature[0] = 1
    observation = {
        "box": [0.3, 0.2, 0.3, 0.4],
        "embedding": feature,
        "quality": True,
        "thumbnail": b"x",
    }
    for t in range(0, 2100, 100):
        await session.observe([observation], t)
    old = session.encounter
    await session.observe([], 11000)
    for t in (12000, 12100, 12200):
        await session.observe([observation], t)
    assert session.encounter != old
    snapshot = await session.snapshot(0, 3000)
    assert snapshot["encounter"] == old
    await session.stop()


def face(index=0):
    return {
        "box": [0.3, 0.2, 0.3, 0.4],
        "embedding": np.eye(128, dtype=np.float32)[index],
        "quality": True,
        "thumbnail": b"x",
    }


async def test_new_visitor_closes_original_encounter_and_mixed_clip_is_rejected(store):
    first = await store.create_person(name="Anna")
    second = await store.create_person(name="Ben")
    await store.add_template(first["id"], face(0)["embedding"])
    await store.add_template(second["id"], face(1)["embedding"])
    session = LiveSession("one", store, Settings())
    for stamp in (0, 100, 200, 300):
        await session.observe([face(0)], stamp)
    original = session.encounter
    before = await session.snapshot(200, 300)
    for stamp in (400, 500, 600, 700):
        await session.observe([face(1)], stamp)
    assert session.encounter != original
    assert session.visitor_id == second["id"]
    assert (await store.person_memory(first["id"]))["last_encounter"]["id"] == original
    assert await session.snapshot(200, 700) is None
    assert before["visitor_id"] == first["id"]
    assert all(t["visitor_id"] == first["id"] for t in before["timeline"])
    await session.stop()


async def test_second_unusable_face_suspends_learning_and_timeline_is_immutable(store):
    session = LiveSession("one", store, Settings())
    for stamp in range(0, 2400, 100):
        await session.observe([face()], stamp)
    snapshot = await session.snapshot(2100, 2300)
    assert all(t["eligible"] for t in snapshot["timeline"])
    unclear = {**face(1), "embedding": None, "quality": False}
    await session.observe([face(), unclear], 2400)
    group = await session.snapshot(2300, 2400)
    assert group["timeline"][-1]["face_count"] == 2
    assert group["timeline"][-1]["eligible"] is False
    # Callers own their snapshot: neither mutation nor future backfill can change it.
    snapshot["timeline"][0]["eligible"] = False
    assert (await session.snapshot(2100, 2300))["timeline"][0]["eligible"] is True
    await session.stop()


async def test_memory_commit_refreshes_live_reminder_without_restarting_camera(store):
    session = LiveSession("one", store, Settings())
    for stamp in range(0, 2400, 100):
        tracks = await session.observe([face()], stamp)
    pid = tracks[0]["person_id"]
    person = await store.get_person(pid)
    await store.correct_person(pid, {"name": "Anna"}, person["version"])
    tracks = await session.observe([face()], 2400)
    assert tracks[0]["memory"]["name"] == "Anna"
    assert tracks[0]["memory"]["last_encounter"] is None
    await session.stop()


async def test_forgotten_visitor_cannot_be_bound_to_a_delayed_clip(store):
    session = LiveSession("one", store, Settings())
    for stamp in range(0, 2400, 100):
        tracks = await session.observe([face()], stamp)
    await store.forget_person(tracks[0]["person_id"])
    assert await session.snapshot(2100, 2300) is None
    await session.stop()


async def test_gallery_refresh_does_not_hide_a_concurrent_enrollment(store, monkeypatch):
    read_templates = store.templates
    visitor = await store.create_person(name="Anna")
    added = False

    async def read_then_enroll():
        nonlocal added
        templates = await read_templates()
        if not added:
            added = True
            await store.add_template(visitor["id"], face()["embedding"])
        return templates

    monkeypatch.setattr(store, "templates", read_then_enroll)
    session = LiveSession("one", store, Settings())
    for stamp in (0, 100, 200, 300):
        tracks = await session.observe([face()], stamp)
    assert tracks[0]["person_id"] == visitor["id"]
    assert len(await store.list_people()) == 1
    await session.stop()
