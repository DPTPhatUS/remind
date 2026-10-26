import asyncio
import copy
import time
from typing import Any, TypedDict

import numpy as np

from remind.config import Settings
from remind.memory.store import MemoryStore
from remind.vision.gallery import FaceGallery
from remind.vision.tracking import Track, Tracker
from remind.vision.types import FaceObservation


class VisiblePerson(TypedDict):
    track_id: str
    person_id: str | None
    state: str
    box: list[float]
    last_seen_ms: float
    memory: dict[str, Any] | None


class CapturedPerson(TypedDict):
    person_id: str | None
    track_id: str
    box: list[float]


class TimelineEntry(TypedDict):
    ms: float
    encounter: str | None
    visitor_id: str | None
    eligible: bool
    face_count: int
    people: list[CapturedPerson]


class LiveSession:
    def __init__(self, generation: str, store: MemoryStore, settings: Settings):
        self.generation = generation
        self.store = store
        self.settings = settings
        self.tracker = Tracker()
        self.gallery = FaceGallery(settings.match_threshold, settings.match_margin)
        self.revision = -1
        self.encounter: str | None = None
        self.visitor_id: str | None = None
        self.last_presence: float = 0
        self.seen: dict[tuple[str, str], float] = {}
        self.cards: dict[str, dict[str, Any]] = {}
        self.stopped = False
        self.lock = asyncio.Lock()
        self.last_heartbeat = time.monotonic()
        self.timeline: list[TimelineEntry] = []

    async def _refresh_gallery(self) -> None:
        revision = self.store.db.revision
        if self.revision == revision:
            return
        entries = await self.store.templates()
        self.gallery.replace(
            [
                (entry["person_id"], np.frombuffer(entry["embedding"], np.float32))
                for entry in entries
                if entry["model"] == "sface-2021dec"
            ]
        )
        self.cards.clear()
        # A concurrent write after the read must still trigger the next refresh.
        self.revision = revision

    async def _recognize_track(self, track: Track, capture_ms: float) -> None:
        assert track.feature is not None
        match = self.gallery.match(track.feature)
        if match.person_id:
            if track.candidate == match.person_id:
                track.votes += 1
            else:
                track.candidate = match.person_id
                track.votes = 1
            track.person_id = match.person_id if track.votes >= 3 else None
            track.state = "remembered" if track.person_id else "observing"
            return

        track.person_id = None
        track.candidate = None
        track.votes = 0
        track.state = "ambiguous" if match.ambiguous else "unknown"
        eligible = (
            not match.ambiguous
            and capture_ms - track.first_ms >= self.settings.enrollment_ms
            and track.usable_count >= self.settings.min_observations
            and track.box[2] >= 0.12
        )
        if not eligible:
            return

        # The session lock serializes the final gallery check and enrollment.
        await self._refresh_gallery()
        recheck = self.gallery.match(track.feature)
        if recheck.person_id or recheck.ambiguous:
            return
        person = await self.store.create_person(thumbnail=track.thumbnail)
        for sample in track.samples:
            await self.store.add_template(person["id"], sample)
        track.person_id = person["id"]
        track.candidate = person["id"]
        track.votes = 3
        track.state = "remembered"
        await self._refresh_gallery()

    def _backfill_identity(self, track: Track, visitor_id: str) -> None:
        # Retain the introduction while this same uninterrupted face was stabilizing.
        for entry in self.timeline:
            if (
                entry["ms"] < track.first_ms
                or entry["face_count"] != 1
                or entry["encounter"] not in (None, self.encounter)
            ):
                continue
            for person in entry["people"]:
                if person["track_id"] == track.id and person["person_id"] in (None, visitor_id):
                    person["person_id"] = visitor_id
                    entry["encounter"] = self.encounter
                    entry["visitor_id"] = visitor_id
                    entry["eligible"] = True

    async def _update_encounter(
        self, single: VisiblePerson | None, tracks: list[Track], capture_ms: float
    ) -> None:
        visitor_id = single["person_id"] if single else None
        if visitor_id and single:
            if self.encounter and self.visitor_id != visitor_id:
                await self.close_encounter(capture_ms)
            if self.encounter is None:
                self.encounter = await self.store.start_encounter(self.generation)
                self.visitor_id = visitor_id
                track = next(track for track in tracks if track.id == single["track_id"])
                self._backfill_identity(track, visitor_id)

            key = (single["track_id"], visitor_id)
            if key not in self.seen:
                await self.store.add_participant(
                    self.encounter, visitor_id, single["track_id"], capture_ms
                )
            self.seen[key] = capture_ms
            self.last_presence = capture_ms

        if self.encounter is None:
            return
        for key, last_seen in list(self.seen.items()):
            if capture_ms - last_seen > 2000:
                await self.store.end_participant(self.encounter, key[0], last_seen)
                del self.seen[key]
        if self.encounter and capture_ms - self.last_presence > 8000:
            await self.close_encounter(capture_ms)

    async def observe(
        self, observations: list[FaceObservation], capture_ms: float
    ) -> list[VisiblePerson]:
        async with self.lock:
            if self.stopped:
                return []
            await self._refresh_gallery()
            tracks = self.tracker.update(observations, capture_ms)
            result: list[VisiblePerson] = []
            for track in tracks:
                if not track.quality:
                    continue
                await self._recognize_track(track, capture_ms)
                result.append(
                    {
                        "track_id": track.id,
                        "person_id": track.person_id,
                        "state": track.state,
                        "box": track.box,
                        "last_seen_ms": capture_ms,
                        "memory": None,
                    }
                )

            # Count unusable faces too: one usable face among several is not one-on-one.
            single = result[0] if len(observations) == 1 and len(result) == 1 else None
            await self._update_encounter(single, tracks, capture_ms)
            for item in result:
                person_id = item["person_id"]
                if person_id:
                    if person_id not in self.cards:
                        memory = await self.store.person_memory(
                            person_id, exclude_encounter_id=self.encounter
                        )
                        if memory is not None:
                            self.cards[person_id] = memory
                    item["memory"] = self.cards.get(person_id)

            visitor_id = single["person_id"] if single else None
            self.timeline.append(
                {
                    "ms": capture_ms,
                    "encounter": self.encounter,
                    "visitor_id": self.visitor_id,
                    "eligible": bool(visitor_id and visitor_id == self.visitor_id),
                    "face_count": len(observations),
                    "people": [
                        {
                            "person_id": item["person_id"],
                            "track_id": item["track_id"],
                            "box": item["box"],
                        }
                        for item in result
                    ],
                }
            )
            self.timeline = [entry for entry in self.timeline if capture_ms - entry["ms"] < 120000]
            return result

    async def snapshot(self, start_ms: float, end_ms: float) -> dict[str, Any] | None:
        async with self.lock:
            timeline = [entry for entry in self.timeline if start_ms <= entry["ms"] <= end_ms]
            encounters = {entry["encounter"] for entry in timeline if entry["encounter"]}
            visitor_ids = {entry["visitor_id"] for entry in timeline if entry["visitor_id"]}
            # Delayed clips must bind to one captured visitor, never the current visitor.
            if len(encounters) != 1 or len(visitor_ids) != 1:
                return None
            visitor_id = next(iter(visitor_ids))
            person = await self.store.get_person(visitor_id)
            if person is None:
                return None
            return {
                "encounter": next(iter(encounters)),
                "visitor_id": visitor_id,
                "voice_version": (await self.store.voice_status())["version"],
                "versions": {visitor_id: person["version"]},
                "timeline": copy.deepcopy(timeline),
                "start_ms": start_ms,
                "end_ms": end_ms,
            }

    async def _finish_encounter(self, capture_ms: float | None = None) -> None:
        if self.encounter is None:
            return
        for (track_id, _), last_seen in self.seen.items():
            end_ms = last_seen if capture_ms is None else min(last_seen, capture_ms)
            await self.store.end_participant(self.encounter, track_id, end_ms)
        await self.store.close_encounter(self.encounter)

    async def close_encounter(self, capture_ms: float) -> None:
        await self._finish_encounter(capture_ms)
        self.encounter = None
        self.visitor_id = None
        self.seen.clear()
        self.cards.clear()

    async def stop(self) -> None:
        async with self.lock:
            if self.stopped:
                return
            self.stopped = True
            # Preserve the encounter and timeline for retained final-upload snapshots.
            await self._finish_encounter()
            self.tracker = Tracker()
