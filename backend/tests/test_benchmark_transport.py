import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from remind.benchmark import transport
from remind.live.protocol import decode_packet


def test_frame_packet_uses_the_production_protocol():
    packet = transport.frame_packet("generation", 7, 125.5, b"jpeg-image")
    header, jpeg = decode_packet(packet)
    assert header == {
        "version": 1,
        "generation": "generation",
        "sequence": 7,
        "capture_ms": 125.5,
    }
    assert jpeg == b"jpeg-image"


class FakeSocket:
    def __init__(self, events):
        self.messages = asyncio.Queue()
        self.events = events

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.messages.get()

    async def send(self, packet):
        header, jpeg = decode_packet(packet)
        assert jpeg == b"jpeg"
        self.events.append(("frame", header["capture_ms"]))
        await self.messages.put(
            json.dumps(
                {
                    **header,
                    "type": "vision",
                    "detections": [{"box": [0.1, 0.1, 0.2, 0.2]}],
                    "candidate": {"person_id": "profile", "confirmed": True},
                    "encounter": {"visitor_id": "profile"},
                    "dropped": 0,
                }
            )
        )
        await asyncio.sleep(0)


def mock_server(
    monkeypatch, *, upload_status=200, pending=False, delay_upload=False, commit_on_drain=False
):
    events = []
    uploads = []
    socket = FakeSocket(events)
    fact = {"id": "old", "value": "old information"}
    state = {"stopped": False, "committed": False}

    async def handler(request):
        path = request.url.path
        if path == "/api/people":
            return httpx.Response(200, json=[{"id": "profile"}])
        if path == "/api/people/profile":
            has_new_fact = state["committed"] if commit_on_drain else bool(uploads)
            return httpx.Response(
                200,
                json={"id": "profile", "facts": [fact, *([{"id": "new"}] if has_new_fact else [])]},
            )
        if path == "/api/session":
            return httpx.Response(200, json={"generation": "generation", "voice_ready": True})
        if path == "/api/jobs":
            if commit_on_drain and state["stopped"]:
                state["committed"] = True
            active = pending or (commit_on_drain and not state["stopped"] and bool(uploads))
            return httpx.Response(200, json=[{"id": "job", "status": "running"}] if active else [])
        if path == "/api/live/generation/clips":
            metadata = json.loads(request.url.params["metadata"])
            assert request.content == b"wave-data"
            assert request.headers["Content-Type"] == "audio/wav"
            events.append(("upload", metadata["end_ms"]))
            uploads.append(metadata)
            if delay_upload:
                await asyncio.sleep(0.03)
            return httpx.Response(
                upload_status,
                json={"status": "queued", "job_id": f"job-{len(uploads)}"},
            )
        if path == "/api/session/generation/stop":
            state["stopped"] = True
            events.append(("stop", None))
            return httpx.Response(200, json={"pending_jobs": int(pending)})
        pytest.fail(f"Unexpected request {request.method} {request.url}")

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        transport.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(**kwargs, transport=httpx.MockTransport(handler)),
    )

    @asynccontextmanager
    async def connect(url, **kwargs):
        assert url == "ws://localhost:8000/api/live/generation/vision"
        assert kwargs["origin"] == "http://localhost:8000"
        yield socket

    monkeypatch.setattr(transport, "connect", connect)
    monkeypatch.setattr(
        transport,
        "iter_video_frames",
        lambda _, **kwargs: iter([(0.0, b"jpeg"), (10.0, b"jpeg"), (25.0, b"jpeg")]),
    )
    return events, uploads


async def test_drain_reads_profiles_after_the_last_job_commit(tmp_path, monkeypatch):
    mock_server(monkeypatch, commit_on_drain=True)
    media = tmp_path / "clip.wav"
    media.write_bytes(b"wave-data")
    result = await transport.replay_encounter(
        "http://localhost:8000",
        tmp_path / "source.mp4",
        [{"path": media, "start_ms": 0, "end_ms": 30}],
        30,
        tmp_path,
        include_audio=True,
    )
    assert "error" not in result
    assert result["remaining_jobs"] == []
    assert [fact["id"] for fact in result["people"][0]["facts"]] == ["old", "new"]
    assert [sighting["fact_id"] for sighting in result["fact_observations"]] == ["new"]


async def test_vision_rejection_is_a_run_error(tmp_path, monkeypatch):
    mock_server(monkeypatch)

    async def reject(self, _):
        await self.messages.put(json.dumps({"type": "error", "message": "Invalid JPEG frame"}))
        await asyncio.sleep(0)

    monkeypatch.setattr(FakeSocket, "send", reject)
    result = await transport.replay_encounter(
        "http://localhost:8000", tmp_path / "source.mp4", [], 30, tmp_path, include_audio=True
    )
    assert "Invalid JPEG frame" in result["error"]
    assert result["vision_errors"][0]["message"] == "Invalid JPEG frame"
    assert result["alignment_valid"] is False


async def test_replay_uses_normal_endpoints_and_observes_first_new_fact(tmp_path, monkeypatch):
    events, uploads = mock_server(monkeypatch, delay_upload=True)
    media = tmp_path / "clip.wav"
    media.write_bytes(b"wave-data")
    result = await transport.replay_encounter(
        "http://localhost:8000",
        tmp_path / "source.mp4",
        [
            {"path": media, "start_ms": 0, "end_ms": 20},
            {"path": media, "start_ms": 20, "end_ms": 40},
        ],
        40,
        tmp_path / "output",
        include_audio=True,
        poll_interval_seconds=0.005,
    )
    assert "error" not in result
    assert result["mode"] == "backend"
    assert result["frames_sent"] == 3
    assert [frame["source_ms"] for frame in result["faces"]] == [0, 10, 25]
    assert result["prior_fact_ids"] == ["old"]
    assert [observation["fact_id"] for observation in result["fact_observations"]] == ["new"]
    assert result["fact_observations"][0]["poll_interval_ms"] > 0
    assert len(uploads) == 2
    assert all(upload["received_ms"] >= upload["sent_ms"] for upload in result["uploads"])
    # The later frame is sent while the earlier upload is still awaiting its response.
    assert result["faces"][-1]["received_ms"] < result["uploads"][0]["received_ms"]
    assert events[-1] == ("stop", None)
    assert result["remaining_jobs"] == []
    assert result["drain_timed_out"] is False
    assert result["clock_samples"][0] == {"source_ms": 0, "performance_ms": 0}
    assert result["clock_samples"][-1]["source_ms"] == 40
    assert result["alignment_valid"] is True
    assert json.loads((tmp_path / "output" / "transport.json").read_text()) == result


async def test_upload_failure_is_recorded_without_retry(tmp_path, monkeypatch):
    _, uploads = mock_server(monkeypatch, upload_status=503)
    media = tmp_path / "clip.wav"
    media.write_bytes(b"wave-data")
    result = await transport.replay_encounter(
        "http://localhost:8000",
        tmp_path / "source.mp4",
        [{"path": media, "start_ms": 0, "end_ms": 30}],
        30,
        tmp_path,
        include_audio=True,
    )
    assert len(uploads) == 1
    assert result["uploads"][0]["status"] == 503
    assert result["uploads"][0]["error"] == "Upload returned HTTP 503"
    assert "stopped_ms" in result


async def test_drain_timeout_preserves_pending_jobs(tmp_path, monkeypatch):
    mock_server(monkeypatch, pending=True)
    result = await transport.replay_encounter(
        "http://localhost:8000",
        tmp_path / "source.mp4",
        [],
        30,
        tmp_path,
        include_audio=True,
        drain_seconds=0,
    )
    assert result["drain_timed_out"] is True
    assert result["remaining_jobs"] == [{"id": "job", "status": "running"}]


async def test_late_frames_are_skipped_without_retiming_source(tmp_path, monkeypatch):
    mock_server(monkeypatch)

    def slow_decode(_, **kwargs):
        import time

        time.sleep(0.12)
        yield 0.0, b"jpeg"
        yield 150.0, b"jpeg"

    monkeypatch.setattr(transport, "iter_video_frames", slow_decode)
    result = await transport.replay_encounter(
        "http://localhost:8000", tmp_path / "source.mp4", [], 180, tmp_path, include_audio=True
    )
    assert "error" not in result
    assert result["frames_skipped_late"] == 1
    assert result["max_frame_lateness_ms"] >= 100
    assert [frame["source_ms"] for frame in result["faces"]] == [150]


async def test_decode_failure_stops_session_and_cancels_pending_uploads(tmp_path, monkeypatch):
    events, uploads = mock_server(monkeypatch)

    def broken_decode(_, **kwargs):
        yield 0.0, b"jpeg"
        raise ValueError("Source video decoding failed")

    monkeypatch.setattr(transport, "iter_video_frames", broken_decode)
    media = tmp_path / "clip.wav"
    media.write_bytes(b"wave-data")
    result = await transport.replay_encounter(
        "http://localhost:8000",
        tmp_path / "source.mp4",
        [{"path": media, "start_ms": 0, "end_ms": 500}],
        500,
        tmp_path,
        include_audio=True,
    )
    assert result["error"] == "ValueError: Source video decoding failed"
    assert events[-1] == ("stop", None)
    assert uploads == []
    assert "source_finished_ms" not in result
    assert result["alignment_valid"] is False
