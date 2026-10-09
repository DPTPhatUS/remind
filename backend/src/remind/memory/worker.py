import asyncio
import contextlib
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from remind.audio.media import decode_clip
from remind.audio.providers import Providers
from remind.audio.speaker import LightSpeaker, assign_speakers
from remind.audio.windows import AudioWindowBuffer
from remind.memory.extraction import validate_extraction
from remind.memory.store import rows
from remind.vision.engine import OpenCVVision
from remind.vision.gallery import FaceGallery


class MemoryWorker:
    def __init__(self, store, settings, registry):
        self.store, self.settings, self.registry = store, settings, registry
        self.providers = Providers(settings) if settings.openai_api_key else None
        self.speaker = None
        self.vision = None
        self.speaker_status = "not loaded"
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory")

    def load_speaker(self):
        if self.speaker is None:
            speaker = LightSpeaker(self.registry, self.settings.speaker_device)
            vision = OpenCVVision(self.registry, self.settings.vision_threads)
            self.speaker, self.vision = speaker, vision
            self.speaker_status = "available; thresholds uncalibrated"

    async def run_once(self):
        if self.providers is None:
            self.speaker_status = "conversation processing needs API key"
            return False
        job = await self.store.claim_job("memory", int(time.time() * 1000))
        if not job:
            return False
        loop = asyncio.get_running_loop()

        async def renew():
            while True:
                await asyncio.sleep(30)
                if not await self.store.renew_lease(
                    job["id"], job["lease_token"], int(time.time() * 1000)
                ):
                    return

        renewal = asyncio.create_task(renew())
        try:
            payload = job["payload"]
            media = await loop.run_in_executor(self.pool, decode_clip, payload["clip_path"])
            vad = AudioWindowBuffer()
            speech = vad.accept(media["pcm"].tobytes(), 0, 16000)
            if vad.flush():
                speech.append(True)
            if not speech:
                await self.store.finish_job(
                    job["id"], job["lease_token"], {"facts": [], "segments": []}
                )
                return True
            segments = await self.providers.transcribe(media["pcm"])
            mapping = {}
            try:
                await loop.run_in_executor(self.pool, self.load_speaker)
                gallery = FaceGallery(self.settings.match_threshold, self.settings.match_margin)
                templates = await self.store.templates()
                gallery.replace(
                    [
                        (t["person_id"], np.frombuffer(t["embedding"], np.float32))
                        for t in templates
                        if t["model"] == "sface-2021dec"
                    ]
                )
                evidence = await loop.run_in_executor(
                    self.pool,
                    self.speaker.evidence,
                    media,
                    segments,
                    self.vision,
                    gallery,
                    payload["timeline"],
                    payload["start_ms"],
                )
                mapping = assign_speakers(segments, evidence, self.settings.speaker_threshold)
            except (ImportError, FileNotFoundError, ValueError) as exc:
                self.speaker_status = f"Unavailable: {exc}; personal facts remain unassigned"
            mapping = {
                speaker: pid for speaker, pid in mapping.items() if pid in payload["versions"]
            }
            async with self.store.db.transaction() as db:
                encounters = await rows(
                    db, "SELECT summary FROM encounters WHERE id=?", (payload["encounter"],)
                )
            previous = encounters[0]["summary"] if encounters else ""
            result = await self.providers.extract(segments, mapping, previous or "")
            validated = validate_extraction(result, segments, mapping)
            await self.store.finish_job(job["id"], job["lease_token"], validated)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.store.fail_job(
                job["id"],
                job["lease_token"],
                type(exc).__name__ + ": " + str(exc)[:160],
                int(time.time() * 1000),
            )
        finally:
            renewal.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renewal
        return True

    async def cleanup(self):
        root = (self.settings.data_dir / "spool").resolve()
        async with self.store.db.transaction() as db:
            pending = await rows(db, "SELECT path FROM cleanup")
            for entry in pending:
                path = Path(entry["path"]).resolve()
                if path.is_relative_to(root):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        continue
                await db.execute("DELETE FROM cleanup WHERE path=?", (entry["path"],))
        if root.exists():
            for path in root.iterdir():
                if (
                    path.is_file()
                    and time.time() - path.stat().st_mtime > self.settings.media_retention_seconds
                ):
                    path.unlink(missing_ok=True)

    async def close(self):
        if self.providers:
            await self.providers.close()
        self.pool.shutdown(wait=True)
