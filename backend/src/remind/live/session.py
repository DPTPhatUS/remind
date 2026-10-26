import asyncio
import copy
import time

import numpy as np

from remind.vision.gallery import FaceGallery
from remind.vision.tracking import Tracker


class LiveSession:
    def __init__(self, generation, store, settings):
        self.generation, self.store, self.settings = generation, store, settings
        self.tracker = Tracker()
        self.gallery = FaceGallery(settings.match_threshold, settings.match_margin)
        self.revision = -1
        self.encounter = None
        self.visitor_id = None
        self.last_presence = 0
        self.seen = {}
        self.cards = {}
        self.stopped = False
        self.lock = asyncio.Lock()
        self.last_heartbeat = time.monotonic()
        self.timeline = []

    async def refresh(self):
        if self.revision != self.store.db.revision:
            entries = await self.store.templates()
            self.gallery.replace(
                [
                    (e["person_id"], np.frombuffer(e["embedding"], np.float32))
                    for e in entries
                    if e["model"] == "sface-2021dec"
                ]
            )
            self.cards = {}
            self.revision = self.store.db.revision

    async def observe(self, observations, capture_ms):
        async with self.lock:
            if self.stopped:
                return []
            await self.refresh()
            tracks = self.tracker.update(observations, capture_ms)
            result = []
            for track in tracks:
                if not track.quality:
                    continue
                match = self.gallery.match(track.feature)
                if match.person_id:
                    if track.candidate == match.person_id:
                        track.votes += 1
                    else:
                        track.candidate, track.votes = match.person_id, 1
                    track.person_id = match.person_id if track.votes >= 3 else None
                    track.state = "remembered" if track.person_id else "observing"
                else:
                    track.person_id, track.candidate, track.votes = None, None, 0
                    track.state = "ambiguous" if match.ambiguous else "unknown"
                    eligible = (
                        not match.ambiguous
                        and capture_ms - track.first_ms >= self.settings.enrollment_ms
                        and track.usable_count >= self.settings.min_observations
                        and track.box[2] >= 0.12
                    )
                    if eligible:
                        # This session lock serializes final gallery check and enrollment.
                        await self.refresh()
                        recheck = self.gallery.match(track.feature)
                        if not recheck.person_id and not recheck.ambiguous:
                            person = await self.store.create_person(thumbnail=track.thumbnail)
                            track.person_id = person["id"]
                            for sample in track.samples:
                                await self.store.add_template(person["id"], sample)
                            track.state = "remembered"
                            track.candidate, track.votes = person["id"], 3
                            await self.refresh()
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

            # One visible face is a product assumption, not a speaker-model result.
            # Count all detections, including unusable/unknown faces, before accepting it.
            single = result[0] if len(observations) == 1 and len(result) == 1 else None
            visitor = single["person_id"] if single else None
            if visitor:
                if self.encounter and self.visitor_id != visitor:
                    await self.close_encounter(capture_ms)
                if self.encounter is None:
                    self.encounter = await self.store.start_encounter(self.generation)
                    self.visitor_id = visitor
                    # Permit the first introduction after a continuous face stabilizes.
                    track = next(t for t in tracks if t.id == single["track_id"])
                    for entry in self.timeline:
                        if (
                            entry["ms"] < track.first_ms
                            or entry["face_count"] != 1
                            or entry["encounter"] not in (None, self.encounter)
                        ):
                            continue
                        for person in entry["people"]:
                            if person["track_id"] == track.id and person["person_id"] in (
                                None, visitor
                            ):
                                person["person_id"] = visitor
                                entry.update(
                                    encounter=self.encounter, visitor_id=visitor, eligible=True
                                )
                key = (single["track_id"], visitor)
                if key not in self.seen:
                    await self.store.add_participant(
                        self.encounter, visitor, single["track_id"], capture_ms
                    )
                self.seen[key] = capture_ms
                self.last_presence = capture_ms

            for (tid, pid), last in list(self.seen.items()):
                if capture_ms - last > 2000:
                    await self.store.end_participant(self.encounter, tid, last)
                    del self.seen[(tid, pid)]
            if self.encounter and capture_ms - self.last_presence > 8000:
                await self.close_encounter(capture_ms)

            for item in result:
                pid = item["person_id"]
                if pid:
                    if pid not in self.cards:
                        self.cards[pid] = await self.store.person_memory(
                            pid, exclude_encounter_id=self.encounter
                        )
                    item["memory"] = self.cards[pid]
            self.timeline.append(
                {
                    "ms": capture_ms,
                    "encounter": self.encounter,
                    "visitor_id": self.visitor_id,
                    "eligible": bool(visitor and visitor == self.visitor_id),
                    "face_count": len(observations),
                    "people": [
                        {"person_id": r["person_id"], "track_id": r["track_id"], "box": r["box"]}
                        for r in result
                    ],
                }
            )
            self.timeline = [t for t in self.timeline if capture_ms - t["ms"] < 120000]
            return result

    async def snapshot(self, start_ms, end_ms):
        async with self.lock:
            timeline = [t for t in self.timeline if start_ms <= t["ms"] <= end_ms]
            encounters = {t["encounter"] for t in timeline if t["encounter"]}
            if len(encounters) != 1:
                # Never attach a mixed or expired capture to whichever encounter is current.
                return None
            encounter = next(iter(encounters))
            ids = {t["visitor_id"] for t in timeline if t["visitor_id"]}
            if len(ids) != 1:
                return None
            visitor_id = next(iter(ids))
            versions = {}
            for pid in ids:
                person = await self.store.get_person(pid)
                if person:
                    versions[pid] = person["version"]
            return {
                "encounter": encounter,
                "visitor_id": visitor_id,
                "voice_version": (await self.store.voice_status())["version"],
                "versions": versions,
                "timeline": copy.deepcopy(timeline),
                "start_ms": start_ms,
                "end_ms": end_ms,
            }

    async def close_encounter(self, capture_ms):
        if self.encounter:
            for (tid, _), last in self.seen.items():
                await self.store.end_participant(self.encounter, tid, min(last, capture_ms))
            await self.store.close_encounter(self.encounter)
        self.encounter = None
        self.visitor_id = None
        self.seen = {}
        self.cards = {}

    async def stop(self):
        async with self.lock:
            if self.stopped:
                return
            self.stopped = True
            # Keep the completed encounter ID for retained final-upload snapshots.
            if self.encounter:
                for (tid, _), last in self.seen.items():
                    await self.store.end_participant(self.encounter, tid, last)
                await self.store.close_encounter(self.encounter)
            self.tracker = Tracker()
