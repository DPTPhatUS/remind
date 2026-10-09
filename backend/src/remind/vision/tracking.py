from dataclasses import dataclass, field
from uuid import uuid4

import numpy as np
from scipy.optimize import linear_sum_assignment

from remind.vision.gallery import normalize


def iou(a, b):
    x, y = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    intersection = max(0, right - x) * max(0, bottom - y)
    return intersection / max(1e-9, a[2] * a[3] + b[2] * b[3] - intersection)


@dataclass
class Track:
    id: str
    box: list
    feature: np.ndarray | None
    first_ms: float
    last_ms: float
    usable_count: int = 0
    person_id: str | None = None
    state: str = "observing"
    candidate: str | None = None
    votes: int = 0
    quality: bool = False
    thumbnail: bytes | None = None
    samples: list = field(default_factory=list)


class Tracker:
    def __init__(self):
        self.tracks: list[Track] = []

    def update(self, observations, now_ms):
        self.tracks = [t for t in self.tracks if now_ms - t.last_ms <= 500]
        costs = np.full((len(self.tracks), len(observations)), 10.0)
        for i, track in enumerate(self.tracks):
            for j, obs in enumerate(observations):
                feature = obs.get("embedding")
                if track.feature is not None and feature is not None:
                    similarity = float(track.feature @ normalize(feature))
                    if similarity >= 0.45:
                        costs[i, j] = 1 - similarity + 0.08 * (1 - iou(track.box, obs["box"]))
                elif iou(track.box, obs["box"]) > 0.3:
                    costs[i, j] = 1.5
        assigned = {}
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
            track = assigned.get(j)
            if track is None:
                track = Track(str(uuid4()), obs["box"], None, now_ms, now_ms)
                self.tracks.append(track)
            feature = obs.get("embedding")
            track.quality = obs["quality"] and feature is not None
            track.box, track.last_ms = obs["box"], now_ms
            if feature is not None:
                track.feature = normalize(feature)
            if track.quality:
                track.usable_count += 1
                track.thumbnail = obs.get("thumbnail")
                if len(track.samples) < 8:
                    track.samples.append(track.feature.copy())
            else:
                track.person_id, track.candidate, track.votes = None, None, 0
                track.state = "observing"
            visible.append(track)
        return visible
