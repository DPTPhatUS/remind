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
        generation="one", stopped=False, last_heartbeat=0, observe=AsyncMock(return_value={})
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


def face(index=0, quality=True):
    return {
        "box": [0.3, 0.2, 0.3, 0.4],
        "embedding": np.eye(128, dtype=np.float32)[index] if quality else None,
        "quality": quality,
        "thumbnail": b"x",
    }


async def enroll(session, index=0, start=0):
    view = None
    for stamp in range(start, start + 2400, 100):
        view = await session.observe([face(index)], stamp)
    assert view["encounter"]["visitor_id"]
    return view["encounter"]["visitor_id"]


async def test_enroll_once_and_return_after_restart(store):
    session = LiveSession("one", store, Settings())
    person = await enroll(session)
    for stamp in range(2400, 10000, 100):
        await session.observe([face()], stamp)
    assert len(await store.list_people()) == 1
    assert len(await store.templates()) <= 8
    await session.stop()
    fresh = LiveSession("two", store, Settings())
    for stamp in (0, 100, 200):
        view = await fresh.observe([face()], stamp)
    assert view["encounter"]["visitor_id"] == person
    assert view["encounter"]["memory"]["last_encounter"]


async def test_absence_allows_five_seconds_but_not_missing_frames(store):
    from remind.memory.association import associate_turn

    session = LiveSession("one", store, Settings())
    person = await enroll(session)
    for stamp in range(2400, 7300, 100):
        view = await session.observe([], stamp)
    assert view["encounter"]["visitor_id"] == person
    assert view["encounter"]["learning_available"]
    snapshot = await session.snapshot(3000, 4000)
    turn = {"start_ms": 3000, "end_ms": 4000}
    assert associate_turn(turn, snapshot["timeline"], final=True)["reason"] == "absence_allowance"
    stale = await session.snapshot(3000, 8000)
    assert (
        associate_turn({"start_ms": 3000, "end_ms": 8000}, stale["timeline"], final=True)["status"]
        == "unattributed"
    )
    view = await session.observe([], 7300)
    assert not view["encounter"]["visitor_id"]
    assert not view["encounter"]["learning_available"]


async def test_bad_quality_keeps_history_but_does_not_extend_confirmation(store):
    session = LiveSession("one", store, Settings())
    person = await enroll(session)
    for stamp in range(2400, 7300, 100):
        view = await session.observe([face(quality=False)], stamp)
    assert view["candidate"]["person_id"] == person
    assert view["encounter"]["state"] == "absent"
    view = await session.observe([face(quality=False)], 7300)
    assert view["encounter"]["visitor_id"] is None


async def test_competitor_pauses_immediately_and_switches_before_absence_timeout(store):
    session = LiveSession("one", store, Settings())
    first = await enroll(session)
    other = await store.enroll_person(b"b", [np.eye(128, dtype=np.float32)[1]])
    old = session.encounter
    initial = await session.observe([face(1)], 2400)
    assert not initial["encounter"]["learning_available"]
    assert initial["encounter"]["visitor_id"] == first
    for stamp in (2500, 2600):
        view = await session.observe([face(1)], stamp)
    assert view["encounter"]["visitor_id"] == other["id"]
    assert session.encounter != old
    before = await session.snapshot(2000, 2500)
    assert before["timeline"][0]["visitor_id"] == first


async def test_multiple_faces_barrier_cannot_be_backfilled(store):
    session = LiveSession("one", store, Settings())
    await enroll(session)
    view = await session.observe([face(), face(1, quality=False)], 2400)
    assert view["candidate"] is None
    assert view["encounter"]["reason"] == "multiple_faces"
    assert not view["encounter"]["learning_available"]
    await session.observe([], 2500)
    assert session.reason == "new_candidate"
    for stamp in (2600, 2700, 2800):
        await session.observe([face()], stamp)
    snapshot = await session.snapshot(2400, 2800)
    assert not snapshot["timeline"][0]["eligible"]
    assert snapshot["timeline"][-1]["eligible"]


async def test_initial_backfill_requires_same_candidate_and_snapshot_is_independent(store):
    session = LiveSession("one", store, Settings())
    await session.observe([], 0)
    await enroll(session, start=100)
    snapshot = await session.snapshot(0, 2400)
    assert not snapshot["timeline"][0]["eligible"]
    assert snapshot["timeline"][1]["reason"] == "initial_candidate_backfill"
    snapshot["timeline"][1]["eligible"] = False
    assert (await session.snapshot(100, 2400))["timeline"][0]["eligible"]
    with pytest.raises(ValueError, match="increase"):
        await session.observe([face()], 100)


async def test_discontinuous_initial_candidate_is_not_retroactively_assigned(store):
    session = LiveSession("one", store, Settings())
    for stamp in (0, 100, 200):
        await session.observe([face()], stamp)
    await session.observe([], 300)
    await enroll(session, index=1, start=400)
    snapshot = await session.snapshot(0, 3000)
    assert snapshot["timeline"][0]["reason"] == "candidate_discontinuity"
    assert not snapshot["timeline"][0]["eligible"]


async def test_saved_memory_refreshes_without_camera_restart(store):
    session = LiveSession("one", store, Settings())
    person_id = await enroll(session)
    await store.correct_person(person_id, {"name": "Anna"}, 1)
    view = await session.observe([face()], 2400)
    assert view["encounter"]["memory"]["name"] == "Anna"
