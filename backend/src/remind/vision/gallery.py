from dataclasses import dataclass

import numpy as np


@dataclass
class IdentityMatch:
    person_id: str | None = None
    score: float = 0
    margin: float = 0
    ambiguous: bool = False


def normalize(feature):
    array = np.asarray(feature, dtype=np.float32).reshape(-1)
    norm = np.linalg.norm(array)
    if array.size != 128 or not np.isfinite(array).all() or norm < 1e-8:
        raise ValueError("Invalid embedding")
    return array / norm


class FaceGallery:
    def __init__(self, threshold=0.55, margin=0.08):
        self.threshold, self.margin = threshold, margin
        self.ids = []
        self.matrix = np.empty((0, 128), dtype=np.float32)

    def replace(self, entries):
        self.ids = [pid for pid, _ in entries]
        self.matrix = (
            np.stack([normalize(v) for _, v in entries])
            if entries
            else np.empty((0, 128), dtype=np.float32)
        )

    def match(self, feature):
        feature = normalize(feature)
        if not self.ids:
            return IdentityMatch()
        scores = {}
        for pid, score in zip(self.ids, self.matrix @ feature, strict=True):
            scores[pid] = max(scores.get(pid, -1), float(score))
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        pid, score = ranked[0]
        margin = score - (ranked[1][1] if len(ranked) > 1 else -1)
        accepted = score >= self.threshold and margin >= self.margin
        return IdentityMatch(
            pid if accepted else None,
            score,
            margin,
            score >= self.threshold - 0.10 and not accepted,
        )
