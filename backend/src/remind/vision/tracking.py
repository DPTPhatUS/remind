from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

import numpy as np
from scipy.optimize import linear_sum_assignment

from remind.vision.gallery import normalize_embedding
from remind.vision.types import FaceEmbedding, FaceObservation


def intersection_over_union(a: list[float], b: list[float]) -> float:
    x, y = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    intersection = max(0, right - x) * max(0, bottom - y)
    return intersection / max(1e-9, a[2] * a[3] + b[2] * b[3] - intersection)


@dataclass
class Track:
    id: str
    box: list[float]
    feature: FaceEmbedding | None
    first_ms: float
    last_ms: float
    usable_count: int = 0
    person_id: str | None = None
    state: Literal["observing", "remembered", "ambiguous", "unknown"] = "observing"
    candidate: str | None = None
    votes: int = 0
    quality: bool = False
    thumbnail: bytes | None = None
    samples: list[FaceEmbedding] = field(default_factory=list)


class Tracker:
    def __init__(self):
        self.tracks: list[Track] = []

    def update(self, observations: list[FaceObservation], now_ms: float) -> list[Track]:
        self.tracks = [track for track in self.tracks if now_ms - track.last_ms <= 500]
        costs = np.full((len(self.tracks), len(observations)), 10.0)
        for i, track in enumerate(self.tracks):
            for j, obs in enumerate(observations):
                feature = obs.get("embedding")
                if track.feature is not None and feature is not None:
                    similarity = float(track.feature @ normalize_embedding(feature))
                    if similarity >= 0.45:
                        overlap = intersection_over_union(track.box, obs["box"])
                        costs[i, j] = 1 - similarity + 0.08 * (1 - overlap)
                elif intersection_over_union(track.box, obs["box"]) > 0.3:
                    costs[i, j] = 1.5
        assigned: dict[int, Track] = {}
        if costs.size:
            for i, j in zip(*linear_sum_assignment(costs), strict=True):
                if costs[i, j] < 2:
                    # Similar competing appearances are unsafe to carry through a crossing.
                    competitors = sorted(costs[:, j])
                    if len(competitors) > 1 and competitors[1] - competitors[0] < 0.04:
                        self.tracks[i].person_id = None
                        self.tracks[i].votes = 0
                        continue
                    assigned[j] = self.tracks[i]
        visible = []
        for j, obs in enumerate(observations):
            current_track = assigned.get(j)
            if current_track is None:
                current_track = Track(str(uuid4()), obs["box"], None, now_ms, now_ms)
                self.tracks.append(current_track)
            feature = obs.get("embedding")
            current_track.quality = obs["quality"] and feature is not None
            current_track.box = obs["box"]
            current_track.last_ms = now_ms
            if feature is not None:
                current_track.feature = normalize_embedding(feature)
            if current_track.quality and current_track.feature is not None:
                current_track.usable_count += 1
                current_track.thumbnail = obs.get("thumbnail")
                if len(current_track.samples) < 8:
                    current_track.samples.append(current_track.feature.copy())
            else:
                current_track.person_id = None
                current_track.candidate = None
                current_track.votes = 0
                current_track.state = "observing"
            visible.append(current_track)
        return visible
