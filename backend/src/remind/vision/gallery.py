from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

from remind.vision.types import FaceEmbedding


@dataclass
class IdentityMatch:
    person_id: str | None = None
    score: float = 0
    margin: float = 0
    ambiguous: bool = False


def normalize_embedding(feature: ArrayLike) -> FaceEmbedding:
    array = np.asarray(feature, dtype=np.float32).reshape(-1)
    norm = np.linalg.norm(array)
    if array.size != 128 or not np.isfinite(array).all() or norm < 1e-8:
        raise ValueError("Invalid embedding")
    return array / norm


class FaceGallery:
    def __init__(self, threshold: float = 0.55, margin: float = 0.08):
        self.threshold = threshold
        self.margin = margin
        self.ids: list[str] = []
        self.matrix = np.empty((0, 128), dtype=np.float32)

    def replace(self, entries: Sequence[tuple[str, ArrayLike]]) -> None:
        self.ids = [person_id for person_id, _ in entries]
        self.matrix = (
            np.stack([normalize_embedding(feature) for _, feature in entries])
            if entries
            else np.empty((0, 128), dtype=np.float32)
        )

    def match(self, feature: ArrayLike) -> IdentityMatch:
        feature = normalize_embedding(feature)
        if not self.ids:
            return IdentityMatch()
        scores: dict[str, float] = {}
        for person_id, score in zip(self.ids, self.matrix @ feature, strict=True):
            scores[person_id] = max(scores.get(person_id, -1), float(score))
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        person_id, score = ranked[0]
        margin = score - (ranked[1][1] if len(ranked) > 1 else -1)
        accepted = score >= self.threshold and margin >= self.margin
        return IdentityMatch(
            person_id if accepted else None,
            score,
            margin,
            score >= self.threshold - 0.10 and not accepted,
        )
