from dataclasses import dataclass
from typing import Protocol


class AudioFormatError(ValueError):
    pass


class SpeechDetector(Protocol):
    def is_speech(self, frame: bytes, sample_rate_hz: int) -> bool:
        ...


class WebRtcSpeechDetector:
    def __init__(self, *, mode: int = 2) -> None:
        import webrtcvad

        self._vad = webrtcvad.Vad(mode)

    def is_speech(self, frame: bytes, sample_rate_hz: int) -> bool:
        return bool(self._vad.is_speech(frame, sample_rate_hz))


@dataclass(frozen=True)
class UtteranceWindow:
    data: bytes
    started_at_ms: int
    ended_at_ms: int
    speech_ms: int


class AudioWindowBuffer:
    def __init__(
        self,
        *,
        speech_detector: SpeechDetector,
        frame_duration_ms: int = 20,
        trailing_silence_ms: int = 700,
        max_utterance_ms: int = 12000,
        expected_sample_rate_hz: int = 16000,
    ) -> None:
        self.speech_detector = speech_detector
        self.frame_duration_ms = frame_duration_ms
        self.trailing_silence_ms = trailing_silence_ms
        self.max_utterance_ms = max_utterance_ms
        self.expected_sample_rate_hz = expected_sample_rate_hz
        self._pending = b""
        self._next_frame_at_ms: int | None = None
        self._active_data = bytearray()
        self._active_started_at_ms: int | None = None
        self._last_speech_end_ms: int | None = None
        self._speech_ms = 0
        self._silence_ms = 0

    def accept(
        self,
        *,
        data: bytes,
        content_type: str,
        sample_rate_hz: int,
        channels: int,
        sample_width_bits: int,
        captured_at_ms: int,
    ) -> list[UtteranceWindow]:
        self._validate_format(
            content_type=content_type,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
            sample_width_bits=sample_width_bits,
        )
        bytes_per_frame = int(
            sample_rate_hz * (sample_width_bits // 8) * self.frame_duration_ms / 1000
        )
        self._pending += data
        if self._next_frame_at_ms is None:
            self._next_frame_at_ms = captured_at_ms

        windows: list[UtteranceWindow] = []
        while len(self._pending) >= bytes_per_frame:
            frame = self._pending[:bytes_per_frame]
            self._pending = self._pending[bytes_per_frame:]
            frame_started_at_ms = self._next_frame_at_ms
            self._next_frame_at_ms += self.frame_duration_ms
            emitted = self._accept_frame(frame, frame_started_at_ms, sample_rate_hz)
            if emitted is not None:
                windows.append(emitted)
        return windows

    def _validate_format(
        self,
        *,
        content_type: str,
        sample_rate_hz: int,
        channels: int,
        sample_width_bits: int,
    ) -> None:
        if content_type != "audio/pcm":
            raise AudioFormatError("Live audio must use content_type audio/pcm.")
        if sample_rate_hz != self.expected_sample_rate_hz:
            raise AudioFormatError(f"Live audio must use {self.expected_sample_rate_hz} Hz.")
        if channels != 1:
            raise AudioFormatError("Live audio must be mono.")
        if sample_width_bits != 16:
            raise AudioFormatError("Live audio must be signed 16-bit PCM.")

    def _accept_frame(
        self,
        frame: bytes,
        frame_started_at_ms: int,
        sample_rate_hz: int,
    ) -> UtteranceWindow | None:
        frame_ended_at_ms = frame_started_at_ms + self.frame_duration_ms
        is_speech = self.speech_detector.is_speech(frame, sample_rate_hz)

        if is_speech and self._active_started_at_ms is None:
            self._active_started_at_ms = frame_started_at_ms

        if self._active_started_at_ms is None:
            return None

        self._active_data.extend(frame)
        if is_speech:
            self._last_speech_end_ms = frame_ended_at_ms
            self._speech_ms += self.frame_duration_ms
            self._silence_ms = 0
        else:
            self._silence_ms += self.frame_duration_ms

        active_duration = frame_ended_at_ms - self._active_started_at_ms
        if self._silence_ms >= self.trailing_silence_ms or active_duration >= self.max_utterance_ms:
            return self._finish_window()
        return None

    def _finish_window(self) -> UtteranceWindow | None:
        if self._active_started_at_ms is None or self._last_speech_end_ms is None:
            self._reset_active()
            return None
        window = UtteranceWindow(
            data=bytes(self._active_data),
            started_at_ms=self._active_started_at_ms,
            ended_at_ms=self._last_speech_end_ms,
            speech_ms=self._speech_ms,
        )
        self._reset_active()
        return window

    def _reset_active(self) -> None:
        self._active_data = bytearray()
        self._active_started_at_ms = None
        self._last_speech_end_ms = None
        self._speech_ms = 0
        self._silence_ms = 0
