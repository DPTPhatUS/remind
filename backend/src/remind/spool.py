"""Bound temporary recording storage across concurrent streamed uploads."""

import asyncio
import logging
from collections.abc import AsyncIterable
from pathlib import Path
from stat import S_ISREG
from uuid import uuid4

MAX_CLIP_BYTES = 16 * 1024 * 1024

logger = logging.getLogger(__name__)


class SpoolFullError(Exception):
    """The recording cannot fit within the shared storage limit."""


class ClipTooLargeError(ValueError):
    """The recording exceeds the per-clip upload limit."""


class RecordingSpool:
    def __init__(self, directory: Path, limit_bytes: int):
        self.directory = directory.resolve()
        self.limit_bytes = limit_bytes
        self._lock = asyncio.Lock()
        self._uploads: dict[Path, int] = {}

    def _used_bytes(self) -> int:
        # Active reservations include buffered writes; count their files only once.
        used = sum(self._uploads.values())
        for path in self.directory.iterdir():
            if path in self._uploads:
                continue
            try:
                info = path.stat()
            except FileNotFoundError:
                # Scheduled cleanup can remove a recording during the scan.
                continue
            if S_ISREG(info.st_mode):
                used += info.st_size
        return used

    async def save(self, chunks: AsyncIterable[bytes]) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (str(uuid4()) + ".webm")
        async with self._lock:
            if self._used_bytes() >= self.limit_bytes:
                raise SpoolFullError
            self._uploads[path] = 0
        try:
            total = 0
            with path.open("wb") as recording:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_CLIP_BYTES:
                        raise ClipTooLargeError
                    async with self._lock:
                        if self._used_bytes() + len(chunk) > self.limit_bytes:
                            raise SpoolFullError
                        self._uploads[path] += len(chunk)
                    recording.write(chunk)
            if total == 0:
                raise ValueError("Clip is empty")
        except BaseException:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove incomplete recording %s", path.name, exc_info=True)
            raise
        finally:
            # The file is closed: remaining bytes now count directly from disk,
            # including failed deletions and files left by an interrupted process.
            async with self._lock:
                del self._uploads[path]
        return path
