import json
import struct

import numpy as np
import pytest

from remind.config import Settings
from remind.live.protocol import decode_packet
from remind.live.queues import LatestQueue
from remind.live.session import LiveSession


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


async def test_queue_keeps_only_latest():
    queue = LatestQueue()
    for i in range(100):
        queue.put(i)
    assert await queue.get() == 99
    assert queue.dropped == 99


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
