"""One visible candidate and the capture-time state of a visitor encounter."""

import asyncio
import copy
import time

import numpy as np

from remind.config import Settings
from remind.database import Record
from remind.memory.association import slice_timeline
from remind.memory.capture import CaptureStore
from remind.memory.contracts import TimelinePoint
from remind.memory.store import MemoryStore, now
from remind.vision.candidate import Candidate
from remind.vision.gallery import FaceGallery
from remind.vision.types import FaceObservation


class LiveSession:
    def __init__(
        self, generation: str, store: MemoryStore, settings: Settings, captures: CaptureStore
    ):
        self.generation = generation
        self.store = store
        self.settings = settings
        self.captures = captures
        self.candidate: Candidate | None = None
        self.candidate_versions: dict[str, int] = {}
        self.initial_candidate = False
        self.had_encounter = False
        self.gallery = FaceGallery(settings.match_threshold, settings.match_margin)
        self.revision = -1
        self.encounter: str | None = None
        self.visitor_id: str | None = None
        self.visitor_version: int | None = None
        self.last_presence = float("-inf")
        self.last_capture_ms = float("-inf")
        self.last_observed = time.monotonic()
        self.last_heartbeat = time.monotonic()
        self.timeline: list[TimelinePoint] = []
        self.stopped = False
        self.forgotten = False
        self.lock = asyncio.Lock()
        self.cards: dict[str, Record] = {}
        self.reason = "no_visitor"
        self.eligible = False

    async def _refresh_gallery(self) -> None:
        revision = self.store.db.revision
        if revision == self.revision:
            return
        entries = await self.store.templates()
        self.gallery.replace(
            [
                (r["person_id"], np.frombuffer(r["embedding"], np.float32))
                for r in entries
                if r["model"] == "sface-2021dec"
            ]
        )
        self.cards.clear()
        self.revision = revision

    def _abandon_candidate(self) -> None:
        if self.candidate:
            for point in self.timeline:
                if (
                    point.get("candidate_id") == self.candidate.id
                    and point["reason"] == "initial_candidate"
                ):
                    point["reason"] = "candidate_discontinuity"
        self.candidate = None
        self.initial_candidate = False

    async def _recognize(self, candidate: Candidate, stamp: float) -> tuple[str | None, bool]:
        assert candidate.feature is not None
        match = self.gallery.match(candidate.feature)
        conflict = match.ambiguous or bool(
            match.person_id and candidate.person_id and match.person_id != candidate.person_id
        )
        if match.person_id:
            if candidate.match_id == match.person_id:
                candidate.votes += 1
            else:
                candidate.match_id = match.person_id
                candidate.votes = 1
                if conflict:
                    candidate.samples.clear()
            if candidate.votes < 3:
                return None, conflict
            candidate.person_id = match.person_id
            if stamp - candidate.last_template_ms >= 2000:
                await self.store.update_templates(match.person_id, candidate.feature)
                candidate.last_template_ms = stamp
            return match.person_id, False
        candidate.match_id = None
        candidate.votes = 0
        if candidate.enrolled or candidate.person_id or match.ambiguous:
            return None, conflict
        samples = candidate.enrollment_samples(self.settings.match_threshold)
        if (
            stamp - candidate.first_ms < self.settings.enrollment_ms
            or len(candidate.samples) < self.settings.min_observations
            or candidate.samples[-1][0] - candidate.samples[0][0] < self.settings.enrollment_ms
            or candidate.box[2] < 0.12
            or not samples
        ):
            return None, conflict
        await self._refresh_gallery()
        recheck = self.gallery.match(candidate.feature)
        if recheck.person_id or recheck.ambiguous:
            return None, recheck.ambiguous
        person = await self.store.enroll_person(candidate.thumbnail, samples)
        candidate.enrolled = True
        candidate.person_id = person["id"]
        candidate.match_id = person["id"]
        candidate.votes = 3
        candidate.last_template_ms = stamp
        await self._refresh_gallery()
        return person["id"], False

    async def _close_encounter(self, stamp: float) -> None:
        if self.encounter:
            await self.store.close_encounter(self.encounter, stamp)
        self.encounter = None
        self.visitor_id = None
        self.visitor_version = None
        self.cards.clear()

    async def _confirm(self, person_id: str, stamp: float) -> None:
        person = await self.store.get_person(person_id)
        if person is None:
            return
        if self.encounter and self.visitor_id != person_id:
            await self._close_encounter(stamp)
        if self.encounter is None:
            start_ms = (
                self.candidate.first_ms if self.initial_candidate and self.candidate else stamp
            )
            self.encounter = await self.store.start_encounter(self.generation, person_id, start_ms)
            self.visitor_id = person_id
            self.visitor_version = person["version"]
            if self.initial_candidate and self.candidate:
                version = self.candidate_versions.get(person_id, person["version"])
                for point in self.timeline:
                    if (
                        point.get("candidate_id") == self.candidate.id
                        and point["reason"] == "initial_candidate"
                    ):
                        point.update(
                            {
                                "eligible": True,
                                "encounter_id": self.encounter,
                                "visitor_id": person_id,
                                "person_version": version,
                                "reason": "initial_candidate_backfill",
                            }
                        )
            self.had_encounter = True
        self.visitor_version = person["version"]
        self.last_presence = stamp

    async def observe(self, observations: list[FaceObservation], capture_ms: float) -> Record:
        async with self.lock:
            if self.stopped:
                return self._view(observations)
            # Increasing packet sequence does not guarantee increasing source time.
            if capture_ms <= self.last_capture_ms:
                raise ValueError("Frame timestamp must increase")
            self.last_capture_ms = capture_ms
            self.last_observed = time.monotonic()
            await self.store.start_session(self.generation)
            await self._refresh_gallery()
            if (
                self.encounter
                and capture_ms - self.last_presence >= self.settings.visitor_absence_ms
            ):
                await self._close_encounter(self.last_presence + self.settings.visitor_absence_ms)
            confirmed = None
            conflict = False
            continuous = False
            if len(observations) != 1:
                self._abandon_candidate()
            else:
                observation = observations[0]
                continuous = bool(
                    self.candidate and self.candidate.continues(observation, capture_ms)
                )
                if not continuous:
                    self._abandon_candidate()
                    self.candidate = Candidate(observation["box"], capture_ms, capture_ms)
                    self.candidate_versions = {
                        p["id"]: p["version"] for p in await self.store.list_people()
                    }
                    self.initial_candidate = not self.had_encounter
                assert self.candidate is not None
                self.candidate.observe(observation, capture_ms)
                if self.candidate.quality:
                    confirmed, conflict = await self._recognize(self.candidate, capture_ms)
                if confirmed:
                    await self._confirm(confirmed, capture_ms)
            self.reason, self.eligible = self._learning_state(
                observations,
                capture_ms,
                confirmed=confirmed,
                conflict=conflict,
                continuous=continuous,
            )
            voice = await self.store.voice_status()
            self.timeline.append(
                {
                    "ms": capture_ms,
                    "candidate_id": self.candidate.id if self.candidate else None,
                    "encounter_id": self.encounter,
                    "visitor_id": self.visitor_id,
                    "person_version": self.visitor_version,
                    "voice_version": voice["version"],
                    "eligible": self.eligible,
                    "face_count": len(observations),
                    "reason": self.reason,
                    "eligible_until": self.last_presence + self.settings.visitor_absence_ms
                    if self.visitor_id
                    else capture_ms + 500,
                }
            )
            self.timeline = [p for p in self.timeline if capture_ms - p["ms"] <= 120000]
            await self.captures.update_timeline(self.generation, self.timeline)
            if self.visitor_id and self.visitor_id not in self.cards:
                memory = await self.store.person_memory(self.visitor_id, self.encounter)
                if memory:
                    self.cards[self.visitor_id] = memory
            return self._view(observations)

    def _learning_state(
        self,
        observations: list[FaceObservation],
        capture_ms: float,
        *,
        confirmed: str | None,
        conflict: bool,
        continuous: bool,
    ) -> tuple[str, bool]:
        if len(observations) > 1:
            return "multiple_faces", False
        if conflict:
            return "identity_conflict", False
        if confirmed and self.visitor_id == confirmed:
            return "direct_confirmation", True
        if (
            self.visitor_id
            and (
                not observations
                or (continuous and self.candidate and self.candidate.person_id == self.visitor_id)
            )
            and capture_ms < self.last_presence + self.settings.visitor_absence_ms
            # Ambiguity stays paused until the visitor is confirmed again.
            and self.reason not in ("multiple_faces", "identity_conflict", "new_candidate")
        ):
            return "absence_allowance", True
        if self.visitor_id:
            return "new_candidate", False
        if self.candidate and self.initial_candidate:
            return "initial_candidate", False
        return "no_visitor", False

    def _encounter_view(self) -> Record:
        if self.reason == "direct_confirmation":
            state = "confirmed"
        elif self.reason == "absence_allowance":
            state = "absent"
        else:
            state = "paused" if self.visitor_id else "identifying"
        return {
            "id": self.encounter,
            "visitor_id": self.visitor_id,
            "state": state,
            "learning_available": self.eligible,
            "reason": self.reason,
            "absence_deadline_ms": self.last_presence + self.settings.visitor_absence_ms
            if self.visitor_id
            else None,
            "memory": self.cards.get(self.visitor_id or ""),
        }

    def _view(self, observations: list[FaceObservation]) -> Record:
        candidate = self.candidate
        return {
            "detections": [{"box": o["box"], "quality": o["quality"]} for o in observations],
            "candidate": {
                "id": candidate.id,
                "box": candidate.box,
                "person_id": candidate.person_id,
                "confirmed": candidate.votes >= 3,
                "quality": candidate.quality,
            }
            if candidate
            else None,
            "encounter": self._encounter_view(),
        }

    async def snapshot(self, start_ms: float, end_ms: float) -> Record:
        async with self.lock:
            timeline = slice_timeline(self.timeline, start_ms, end_ms)
            voice = await self.store.voice_status()
            return {
                "timeline": copy.deepcopy(timeline),
                "voice_version": timeline[0]["voice_version"] if timeline else voice["version"],
            }

    async def maintain(self) -> None:
        async with self.lock:
            if not self.stopped:
                await self.captures.update_timeline(self.generation, self.timeline)

    async def stop(self, *, forgetting: bool = False) -> None:
        async with self.lock:
            if self.stopped and not forgetting:
                return
            self.stopped = True
            self.forgotten = self.forgotten or forgetting
            await self.captures.update_timeline(
                self.generation, self.timeline, final=True, cancel_unresolved=forgetting
            )
            await self._close_encounter(max(0, self.last_capture_ms))
            async with self.store.db.transaction() as db:
                await db.execute(
                    "UPDATE capture_sessions SET ended_at=?,cancelled=? WHERE generation=?",
                    (now(), int(self.forgotten), self.generation),
                )
            self.candidate = None
