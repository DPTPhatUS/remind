import io
import wave
from pathlib import Path
from typing import TypedDict

import av
import numpy as np
from numpy.typing import NDArray

SAMPLE_RATE = 16000
VAD_FRAME_SAMPLES = 320  # WebRTC VAD accepts 20 ms PCM16 frames.

PCM = NDArray[np.int16]
AudioStamp = tuple[float, float, int, str]


class DecodedAudio(TypedDict):
    pcm: PCM
    continuous: bool


def has_speech(pcm: PCM) -> bool:
    """Check a decoded clip without buffering or creating recording windows."""
    import webrtcvad

    vad = webrtcvad.Vad(2)
    for start in range(0, len(pcm) - VAD_FRAME_SAMPLES + 1, VAD_FRAME_SAMPLES):
        frame = pcm[start : start + VAD_FRAME_SAMPLES]
        if vad.is_speech(frame.tobytes(), SAMPLE_RATE):
            return True
    return False


def audio_is_continuous(stamps: list[AudioStamp]) -> bool:
    return bool(stamps) and all(
        abs(current[0] - (previous[0] + previous[1])) <= 0.005 and current[2:] == previous[2:]
        for previous, current in zip(stamps, stamps[1:], strict=False)
    )


def decode_audio(source: Path | str | bytes, max_seconds: float = 30) -> DecodedAudio:
    """Decode only audio from WebM/WAV to mono PCM16 at 16 kHz.

    Gaps or changes of input format are exposed rather than concealed by the
    resampler. Timestamps are rebased to the beginning of the audio recording.
    No video frames are decoded, even when the container includes a camera track.
    """
    if not 0 < max_seconds <= 120:
        raise ValueError("Invalid audio duration limit")
    audio = []
    stamps: list[AudioStamp] = []
    missing_timestamp = False
    origin = None
    size = 0
    target = io.BytesIO(source) if isinstance(source, bytes) else str(source)
    try:
        with av.open(target, mode="r") as container:
            if not container.streams.audio:
                raise ValueError("Recording has no audio track")
            if container.streams.video:
                starts = [
                    float(item.start_time * item.time_base)
                    for item in container.streams
                    if item.start_time is not None and item.time_base is not None
                ]
                origin = min(starts) if starts else None
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(stream):
                if frame.pts is None:
                    missing_timestamp = True
                else:
                    stamps.append(
                        (
                            float(frame.pts * frame.time_base),
                            frame.samples / frame.sample_rate,
                            frame.sample_rate,
                            frame.layout.name,
                        )
                    )
                    if stamps[-1][0] + stamps[-1][1] - stamps[0][0] > max_seconds + 0.1:
                        raise ValueError("Recording is too long")
                for chunk in resampler.resample(frame):
                    data = chunk.to_ndarray().reshape(-1)
                    size += len(data)
                    if size > SAMPLE_RATE * max_seconds:
                        raise ValueError("Recording is too long")
                    audio.append(data)
            for chunk in resampler.resample(None):
                audio.append(chunk.to_ndarray().reshape(-1))
    except av.FFmpegError as exc:
        raise ValueError("Recording could not be decoded") from exc
    if not audio:
        raise ValueError("Recording has insufficient audio")
    pcm = np.concatenate(audio).astype(np.int16)
    # Preserve the small audio/video start offset using stream metadata alone.
    # A large unknown lead-in cannot safely be related to the capture timeline.
    offset = round((stamps[0][0] - origin) * SAMPLE_RATE) if stamps and origin is not None else 0
    aligned = abs(offset) <= 1600
    if aligned and offset:
        pcm = np.pad(pcm, (max(0, offset), 0))[max(0, -offset) :]
    if len(pcm) > SAMPLE_RATE * max_seconds:
        raise ValueError("Recording is too long")
    return {
        "pcm": pcm,
        "continuous": aligned and not missing_timestamp and audio_is_continuous(stamps),
    }


def wav_bytes(pcm: PCM) -> bytes:
    target = io.BytesIO()
    with wave.open(target, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.astype(np.int16).tobytes())
    return target.getvalue()
