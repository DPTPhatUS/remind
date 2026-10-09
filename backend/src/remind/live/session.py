import asyncio
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
                if track.person_id:
                    if self.encounter is None:
                        self.encounter = await self.store.start_encounter(self.generation)
                    # Fill only this continuous track's pre-enrollment evidence, so its
                    # first introduction can be assigned after identity stabilizes.
                    for entry in self.timeline:
                        if entry["ms"] < track.first_ms:
                            continue
                        for person in entry["people"]:
                            if person["track_id"] == track.id and not person["person_id"]:
                                person["person_id"] = track.person_id
                                entry["encounter"] = self.encounter
                    key = (track.id, track.person_id)
                    if key not in self.seen:
                        await self.store.add_participant(
                            self.encounter, track.person_id, track.id, capture_ms
                        )
                    self.seen[key] = capture_ms
                    self.last_presence = capture_ms
                    if track.person_id not in self.cards:
                        self.cards[track.person_id] = await self.store.person_memory(
                            track.person_id, exclude_encounter_id=self.encounter
                        )
                result.append(
                    {
                        "track_id": track.id,
                        "person_id": track.person_id,
                        "state": track.state,
                        "box": track.box,
                        "last_seen_ms": capture_ms,
                        "memory": self.cards.get(track.person_id),
                    }
                )
            for (tid, pid), last in list(self.seen.items()):
                if capture_ms - last > 2000:
                    await self.store.end_participant(self.encounter, tid, last)
                    del self.seen[(tid, pid)]
            if self.encounter and capture_ms - self.last_presence > 8000:
                await self.store.close_encounter(self.encounter)
                self.encounter = None
                self.seen = {}
                self.cards = {}
            self.timeline.append(
                {
                    "ms": capture_ms,
                    "encounter": self.encounter,
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
            ids = {p["person_id"] for t in timeline for p in t["people"] if p["person_id"]}
            versions = {}
            for pid in ids:
                person = await self.store.get_person(pid)
                if person:
                    versions[pid] = person["version"]
            return {
                "encounter": encounter,
                "versions": versions,
                "timeline": timeline,
                "start_ms": start_ms,
                "end_ms": end_ms,
            }

    async def stop(self):
        async with self.lock:
            if self.stopped:
                return
            self.stopped = True
            if self.encounter:
                await self.store.close_encounter(self.encounter)
            self.tracker = Tracker()
