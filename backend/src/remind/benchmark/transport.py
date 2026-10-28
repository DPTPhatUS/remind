"""Replay synchronized source frames and audio through the normal backend interfaces."""

import asyncio
import contextlib
import json
import struct
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect
from websockets.typing import Origin

from remind.benchmark.media import AudioClip, iter_video_frames

Record = dict[str, Any]


def frame_packet(generation: str, sequence: int, capture_ms: float, jpeg: bytes) -> bytes:
    header = json.dumps(
        {
            "version": 1,
            "generation": generation,
            "sequence": sequence,
            "capture_ms": capture_ms,
        },
        separators=(",", ":"),
    ).encode()
    return struct.pack(">I", len(header)) + header + jpeg


async def replay_encounter(
    base_url: str,
    media_path: Path,
    clips: Sequence[AudioClip],
    duration_ms: float,
    output_dir: Path,
    *,
    include_audio: bool,
    drain_seconds: float = 600,
    poll_interval_seconds: float = 0.5,
) -> Record:
    """Run once in real time; expected identities and annotations are never accepted."""
    if duration_ms <= 0 or drain_seconds < 0 or poll_interval_seconds <= 0:
        raise ValueError(
            "Replay duration and poll interval must be positive; drain cannot be negative"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    result: Record = {
        "mode": "backend",
        "faces": [],
        "uploads": [],
        "people": [],
        "prior_people": [],
        "prior_fact_ids": [],
        "fact_observations": [],
        "clock_samples": [{"source_ms": 0.0, "performance_ms": 0.0}],
        "remaining_jobs": [],
        "frames_sent": 0,
        "frames_skipped_late": 0,
        "max_frame_lateness_ms": 0.0,
    }
    loop = asyncio.get_running_loop()
    started = loop.time()
    generation: str | None = None
    observer: asyncio.Task | None = None
    receiver: asyncio.Task | None = None
    observed_facts: set[str] = set()
    previous_poll_ms = 0.0

    def elapsed_ms() -> float:
        return (loop.time() - started) * 1000

    async def due(source_ms: float) -> None:
        await asyncio.sleep(max(0.0, source_ms / 1000 - (loop.time() - started)))

    def check_background() -> None:
        for task in (observer, receiver):
            if task is not None and task.done():
                task.result()
                raise RuntimeError("Replay observation connection ended before source completion")

    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:

        async def get(path: str) -> Any:
            response = await client.get(path)
            response.raise_for_status()
            return response.json()

        async def people() -> list[Record]:
            return [await get(f"/api/people/{person['id']}") for person in await get("/api/people")]

        async def observe() -> None:
            nonlocal previous_poll_ms
            request_ms = elapsed_ms()
            # Once no job is active, the following profile read must include its commit.
            result["remaining_jobs"] = await get("/api/jobs")
            result["people"] = await people()
            received_ms = elapsed_ms()
            for person in result["people"]:
                for fact in person["facts"]:
                    if fact["id"] not in observed_facts:
                        observed_facts.add(fact["id"])
                        result["fact_observations"].append(
                            {
                                "fact_id": fact["id"],
                                "performance_ms": received_ms,
                                "request_ms": request_ms,
                                "poll_interval_ms": received_ms - previous_poll_ms,
                            }
                        )
            previous_poll_ms = request_ms

        async def poll() -> None:
            while True:
                await observe()
                await asyncio.sleep(poll_interval_seconds)

        try:
            result["prior_people"] = await people()
            observed_facts.update(
                fact["id"] for person in result["prior_people"] for fact in person["facts"]
            )
            result["prior_fact_ids"] = sorted(observed_facts)
            response = await client.post("/api/session")
            response.raise_for_status()
            result["session"] = response.json()
            session_generation = str(result["session"]["generation"])
            generation = session_generation
            parsed = urlsplit(base_url)
            socket_url = urlunsplit(
                (
                    "wss" if parsed.scheme == "https" else "ws",
                    parsed.netloc,
                    f"/api/live/{generation}/vision",
                    "",
                    "",
                )
            )
            async with connect(
                socket_url, origin=Origin(base_url.rstrip("/")), max_size=4 * 1024 * 1024
            ) as socket:
                started = loop.time()

                async def receive() -> None:
                    async for message in socket:
                        event = json.loads(message)
                        event["received_ms"] = elapsed_ms()
                        if event.get("type") == "vision":
                            event["source_ms"] = event["capture_ms"]
                            result["faces"].append(event)
                        else:
                            result.setdefault("vision_errors", []).append(event)
                            raise RuntimeError(
                                f"Vision rejected a frame: {event.get('message', event)}"
                            )

                async def send_frames() -> None:
                    frames = iter_video_frames(media_path, include_audio=include_audio)
                    try:
                        sequence = 0
                        while (frame := await asyncio.to_thread(next, frames, None)) is not None:
                            source_ms, jpeg = frame
                            if source_ms >= duration_ms:
                                break
                            await due(source_ms)
                            check_background()
                            lateness = elapsed_ms() - source_ms
                            result["max_frame_lateness_ms"] = max(
                                result["max_frame_lateness_ms"], lateness
                            )
                            if lateness > 100:
                                result["frames_skipped_late"] += 1
                            else:
                                await socket.send(
                                    frame_packet(session_generation, sequence, source_ms, jpeg)
                                )
                                result["frames_sent"] += 1
                                performance_ms = elapsed_ms()
                                previous = result["clock_samples"][-1]
                                if source_ms > previous["source_ms"]:
                                    result["clock_samples"].append(
                                        {"source_ms": source_ms, "performance_ms": performance_ms}
                                    )
                            sequence += 1
                    finally:
                        close = getattr(frames, "close", None)
                        if close is not None:
                            close()
                    await due(duration_ms)
                    result["source_finished_ms"] = elapsed_ms()
                    result["clock_samples"].append(
                        {"source_ms": duration_ms, "performance_ms": result["source_finished_ms"]}
                    )

                async def upload_clips() -> None:
                    for index, clip in enumerate(clips):
                        await due(clip["end_ms"])
                        check_background()
                        metadata = {
                            "window_id": f"direct-{index}",
                            "start_ms": clip["start_ms"],
                            "end_ms": clip["end_ms"],
                        }
                        upload: Record = {"metadata": metadata, "sent_ms": elapsed_ms()}
                        result["uploads"].append(upload)
                        try:
                            response = await client.post(
                                f"/api/live/{generation}/clips",
                                params={"metadata": json.dumps(metadata)},
                                content=await asyncio.to_thread(Path(clip["path"]).read_bytes),
                                headers={"Content-Type": "audio/wav"},
                            )
                            upload.update(received_ms=elapsed_ms(), status=response.status_code)
                            try:
                                upload["receipt"] = response.json()
                            except ValueError:
                                upload["error"] = response.text[:1000]
                            if response.is_error:
                                upload["error"] = f"Upload returned HTTP {response.status_code}"
                        except httpx.HTTPError as exc:
                            upload.update(received_ms=elapsed_ms(), error=str(exc))

                receiver = asyncio.create_task(receive())
                observer = asyncio.create_task(poll())
                async with asyncio.TaskGroup() as producers:
                    producers.create_task(send_frames())
                    producers.create_task(upload_clips())
                check_background()
                response = await client.post(f"/api/session/{generation}/stop")
                response.raise_for_status()
                result["stopped_ms"] = elapsed_ms()
                observer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await observer
                observer = None
                deadline = loop.time() + drain_seconds
                while True:
                    await observe()
                    active = [
                        j for j in result["remaining_jobs"]
                        if j["status"] in {"pending", "running", "waiting_for_attribution"}
                    ]
                    if not active or loop.time() >= deadline:
                        result["drain_timed_out"] = bool(active)
                        break
                    await asyncio.sleep(min(poll_interval_seconds, max(0, deadline - loop.time())))
        except Exception as exc:
            failures = exc.exceptions if isinstance(exc, ExceptionGroup) else [exc]
            result["error"] = "; ".join(f"{type(error).__name__}: {error}" for error in failures)
        finally:
            for task in (observer, receiver):
                if task is not None:
                    task.cancel()
            await asyncio.gather(
                *(task for task in (observer, receiver) if task is not None),
                return_exceptions=True,
            )
            if generation and "stopped_ms" not in result:
                with contextlib.suppress(httpx.HTTPError):
                    await client.post(f"/api/session/{generation}/stop")
            result["finished_ms"] = elapsed_ms()
    if result.get("vision_errors") and not result.get("error"):
        result["error"] = "Vision reported frame errors; inspect vision_errors"
    samples = result["clock_samples"]
    result["alignment_valid"] = (
        not result.get("error")
        and len(samples) >= 2
        and samples[-1]["source_ms"] == duration_ms
        and all(
            a["source_ms"] < b["source_ms"] and a["performance_ms"] < b["performance_ms"]
            for a, b in zip(samples, samples[1:], strict=False)
        )
    )
    (output_dir / "transport.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
