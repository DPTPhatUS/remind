"""Follow one visible candidate long enough to recognize or enroll them."""

from dataclasses import dataclass, field
from uuid import uuid4

import numpy as np

from remind.vision.gallery import normalize_embedding
from remind.vision.types import FaceEmbedding, FaceObservation


def intersection_over_union(a: list[float], b: list[float]) -> float:
    x, y = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    intersection = max(0, right - x) * max(0, bottom - y)
    return intersection / max(1e-9, a[2] * a[3] + b[2] * b[3] - intersection)


@dataclass
class Candidate:
    box: list[float]
    first_ms: float
    last_ms: float
    id: str = field(default_factory=lambda: str(uuid4()))
    feature: FaceEmbedding | None = None
    quality: bool = False
    person_id: str | None = None
    match_id: str | None = None
    votes: int = 0
    enrolled: bool = False
    thumbnail: bytes | None = None
    samples: list[tuple[float, FaceEmbedding]] = field(default_factory=list)
    last_template_ms: float = float("-inf")

    def continues(self, observation: FaceObservation, stamp: float) -> bool:
        if stamp - self.last_ms > 500:
            return False
        feature = observation.get("embedding")
        if self.feature is not None and feature is not None:
            return float(self.feature @ normalize_embedding(feature)) >= 0.45
        return intersection_over_union(self.box, observation["box"]) > 0.3

    def observe(self, observation: FaceObservation, stamp: float) -> None:
        self.box = observation["box"]
        self.last_ms = stamp
        feature = observation.get("embedding")
        self.quality = observation["quality"] and feature is not None
        if self.quality:
            assert feature is not None
            self.feature = normalize_embedding(feature)
            self.thumbnail = observation.get("thumbnail")
            self.samples = [(t, f) for t, f in self.samples if stamp - t <= 5000]
            if not self.samples or stamp - self.samples[-1][0] >= 200:
                self.samples.append((stamp, self.feature.copy()))
                self.samples = self.samples[-16:]
        else:
            self.match_id = None
            self.votes = 0

    def enrollment_samples(self, threshold: float) -> list[FaceEmbedding]:
        if not self.samples or self.feature is None:
            return []
        vectors = np.stack([f for _, f in self.samples])
        similarities = vectors @ vectors.T
        medoid = int(np.argmax(similarities.mean(axis=1)))
        if np.any(similarities[medoid] < threshold):
            return []
        # The newest view must agree with previous evidence, not just with itself.
        if len(vectors) < 2 or float(np.max(vectors[:-1] @ self.feature)) < threshold:
            return []
        chosen = [len(vectors) - 1]
        while len(chosen) < min(8, len(vectors)):
            distances = np.max(vectors @ vectors[chosen].T, axis=1)
            distances[chosen] = np.inf
            chosen.append(int(np.argmin(distances)))
        return [vectors[i].copy() for i in chosen]
