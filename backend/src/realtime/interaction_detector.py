from dataclasses import dataclass


@dataclass(frozen=True)
class InteractionDetectorConfig:
    candidate_score: float = 0.45
    active_score: float = 0.70
    min_candidate_ms: int = 2000
    end_silence_ms: int = 8000
    signal_fresh_ms: int = 1500


@dataclass(frozen=True)
class DetectionEvent:
    type: str
    payload: dict


class InteractionDetector:
    def __init__(self, config: InteractionDetectorConfig) -> None:
        self.config = config
        self.state = "idle"
        self._candidate_started_at_ms: int | None = None
        self._active_started_at_ms: int | None = None
        self._last_activity_at_ms: int | None = None
        self._last_face_at_ms: int | None = None
        self._last_speech_at_ms: int | None = None
        self._last_recognized_at_ms: int | None = None

    def observe_face(
        self,
        *,
        now_ms: int,
        face_present: bool,
        recognized: bool,
        opted_out: bool,
    ) -> None:
        if not face_present:
            return
        self._last_face_at_ms = now_ms
        self._last_activity_at_ms = now_ms
        if recognized and not opted_out:
            self._last_recognized_at_ms = now_ms

    def observe_speech(self, *, now_ms: int) -> None:
        self._last_speech_at_ms = now_ms
        self._last_activity_at_ms = now_ms

    def evaluate(self, *, now_ms: int) -> list[DetectionEvent]:
        score = self._score(now_ms)
        if self.state == "active":
            ended = self._maybe_end(now_ms=now_ms, score=score)
            return [ended] if ended is not None else []
        if self.state == "cooldown":
            if score >= self.config.candidate_score:
                self.state = "active"
                return []
            ended = self._maybe_end(now_ms=now_ms, score=score)
            return [ended] if ended is not None else []
        if self.state == "idle":
            if score >= self.config.candidate_score:
                self.state = "candidate"
                self._candidate_started_at_ms = now_ms
                return [
                    DetectionEvent(
                        type="interaction.candidate",
                        payload={
                            "confidence": round(score, 3),
                            "reason": "face_and_speech_detected",
                        },
                    )
                ]
            return []
        if self.state == "candidate":
            if score < self.config.candidate_score:
                self.state = "idle"
                self._candidate_started_at_ms = None
                return []
            if self._candidate_started_at_ms is None:
                self._candidate_started_at_ms = now_ms
            candidate_ms = now_ms - self._candidate_started_at_ms
            if candidate_ms >= self.config.min_candidate_ms and score >= self.config.active_score:
                self.state = "active"
                self._active_started_at_ms = self._candidate_started_at_ms
                return [
                    DetectionEvent(
                        type="interaction.started",
                        payload={
                            "confidence": round(score, 3),
                            "reason": "stable_face_and_speech",
                            "candidate_ms": candidate_ms,
                        },
                    )
                ]
        return []

    def _score(self, now_ms: int) -> float:
        score = 0.0
        face_recent = self._is_recent(self._last_face_at_ms, now_ms)
        speech_recent = self._is_recent(self._last_speech_at_ms, now_ms)
        if face_recent:
            score += 0.35
        if speech_recent:
            score += 0.25
        if face_recent and speech_recent and self._is_recent(self._last_recognized_at_ms, now_ms):
            score += 0.10
        if self.state == "candidate" and self._candidate_started_at_ms is not None:
            if now_ms - self._candidate_started_at_ms >= self.config.min_candidate_ms:
                score += 0.10
        return min(score, 1.0)

    def _maybe_end(self, *, now_ms: int, score: float) -> DetectionEvent | None:
        if score >= self.config.candidate_score:
            if self.state == "cooldown":
                self.state = "active"
            return None
        self.state = "cooldown"
        last_activity = self._last_activity_at_ms or now_ms
        if now_ms - last_activity < self.config.end_silence_ms:
            return None
        started_at = self._active_started_at_ms or last_activity
        duration_ms = now_ms - started_at
        self.state = "idle"
        self._candidate_started_at_ms = None
        self._active_started_at_ms = None
        return DetectionEvent(
            type="interaction.ended",
            payload={
                "confidence": round(score, 3),
                "duration_ms": duration_ms,
                "reason": "no_recent_face_or_speech",
            },
        )

    def _is_recent(self, timestamp_ms: int | None, now_ms: int) -> bool:
        return timestamp_ms is not None and now_ms - timestamp_ms <= self.config.signal_fresh_ms
