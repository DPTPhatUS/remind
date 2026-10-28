import asyncio
import contextlib
import time
from concurrent.futures import Executor

from fastapi import WebSocket, WebSocketDisconnect

from remind.live.protocol import FrameHeader, decode_packet
from remind.live.queues import LatestQueue
from remind.live.session import LiveSession
from remind.vision.engine import OpenCVVision


async def serve_vision(
    socket: WebSocket, session: LiveSession, engine: OpenCVVision, pool: Executor
) -> None:
    """Process the latest frame while a separate task receives incoming frames."""
    queue = LatestQueue[tuple[FrameHeader, bytes]]()

    async def receive() -> None:
        sequence = -1
        while True:
            header, data = decode_packet(await socket.receive_bytes())
            if session.stopped:
                raise WebSocketDisconnect(code=1000)
            session.last_heartbeat = time.monotonic()
            if header["generation"] != session.generation or header["sequence"] <= sequence:
                continue
            sequence = header["sequence"]
            queue.put((header, data))

    async def process() -> None:
        processed = 0
        started = time.monotonic()
        while True:
            header, data = await queue.get()
            before = time.perf_counter()
            try:
                observations = await asyncio.get_running_loop().run_in_executor(
                    pool, engine.detect, data
                )
                view = await session.observe(observations, header["capture_ms"])
                processed += 1
                await socket.send_json(
                    {
                        "type": "vision",
                        "generation": session.generation,
                        "sequence": header["sequence"],
                        "capture_ms": header["capture_ms"],
                        **view,
                        "processing_ms": (time.perf_counter() - before) * 1000,
                        "processed_fps": processed / max(0.001, time.monotonic() - started),
                        "dropped": queue.dropped,
                    }
                )
            except ValueError as exc:
                await socket.send_json({"type": "error", "message": str(exc)})

    tasks = [asyncio.create_task(receive()), asyncio.create_task(process())]
    close_code = 1000
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    except ValueError:
        close_code = 1008
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with contextlib.suppress(RuntimeError):
            await socket.close(code=close_code)
