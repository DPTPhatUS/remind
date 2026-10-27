"""Prepare original media for replay without browser recording or retiming."""

from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict, cast

import av
import cv2
import numpy as np

from remind.audio.media import PCM, SAMPLE_RATE, wav_bytes
from remind.benchmark.inputs import Media

TIMESTAMP_TOLERANCE_MS = 5.0
EDGE_TOLERANCE_MS = 150.0
CLIP_MS = 8_000


class AudioClip(TypedDict):
    path: Path
    start_ms: float
    end_ms: float


class MediaTiming(TypedDict):
    origin_ms: float
    video_start_ms: float | None
    video_end_ms: float | None
    video_frames: int
    audio_start_ms: float
    audio_end_ms: float
    source_duration_ms: float
    expected_duration_ms: float
    leading_silence_ms: float
    trailing_silence_ms: float
    trimmed_audio_tail_ms: float
    max_audio_timestamp_error_ms: float
    audio_duration_error_ms: float
    sample_rate: int
    audio_samples: int


class PreparedMedia(TypedDict):
    metadata: MediaTiming
    clips: list[AudioClip]


def _timestamp_ms(frame: av.AudioFrame | av.VideoFrame) -> float:
    if frame.pts is None or frame.time_base is None:
        raise ValueError("Source media contains a frame without a timestamp")
    timestamp = float(frame.pts * frame.time_base) * 1000
    if not np.isfinite(timestamp) or timestamp < 0:
        raise ValueError("Source media contains a negative or invalid frame timestamp")
    return timestamp


def _decode_excerpt(excerpt: Media, *, require_video: bool) -> tuple[PCM, MediaTiming]:
    audio_chunks = []
    audio_start = audio_end = video_start = video_end = None
    previous_video = None
    audio_format = None
    source_audio_ms = 0.0
    max_error = 0.0
    video_frames = 0
    first_timestamp = None
    try:
        with av.open(str(excerpt.path)) as container:
            if not container.streams.audio:
                raise ValueError("Source media has no audio track")
            if require_video and not container.streams.video:
                raise ValueError("Conversation media has no video track")
            audio_stream = container.streams.audio[0]
            video_stream = container.streams.video[0] if container.streams.video else None
            streams = [audio_stream, *([video_stream] if video_stream is not None else [])]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for decoded in container.decode(*streams):
                frame = cast(av.AudioFrame | av.VideoFrame, decoded)
                timestamp = _timestamp_ms(frame)
                first_timestamp = (
                    timestamp if first_timestamp is None else min(first_timestamp, timestamp)
                )
                if timestamp - first_timestamp > excerpt.duration_ms + EDGE_TOLERANCE_MS:
                    raise ValueError("Decoded source duration exceeds the manifest excerpt")
                if isinstance(frame, av.VideoFrame):
                    if previous_video is not None and timestamp <= previous_video:
                        raise ValueError("Source video timestamps are not strictly increasing")
                    duration = float(frame.duration * frame.time_base) * 1000
                    if duration <= 0 and video_stream is not None and video_stream.average_rate:
                        duration = float(1000 / video_stream.average_rate)
                    if duration <= 0:
                        raise ValueError("Source video has an unknown frame duration")
                    video_start = timestamp if video_start is None else video_start
                    previous_video, video_end = timestamp, timestamp + duration
                    video_frames += 1
                    continue
                if frame.sample_rate <= 0 or frame.samples <= 0:
                    raise ValueError("Source audio has an invalid sample rate or empty frame")
                current_format = (frame.sample_rate, frame.layout.name)
                if audio_format is not None and audio_format != current_format:
                    raise ValueError("Source audio changes sample rate or channel layout")
                audio_format = current_format
                if audio_end is not None:
                    error = abs(timestamp - audio_end)
                    max_error = max(max_error, error)
                    if error > TIMESTAMP_TOLERANCE_MS:
                        raise ValueError(
                            "Source audio has a timestamp gap or overlap "
                            f"of {error:.3f} ms at {timestamp:.3f} ms"
                        )
                audio_start = timestamp if audio_start is None else audio_start
                duration = frame.samples / frame.sample_rate * 1000
                audio_end = timestamp + duration
                source_audio_ms += duration
                for chunk in resampler.resample(frame):
                    audio_chunks.append(chunk.to_ndarray().reshape(-1))
            for chunk in resampler.resample(None):
                audio_chunks.append(chunk.to_ndarray().reshape(-1))
    except av.FFmpegError as exc:
        raise ValueError("Source media could not be decoded") from exc
    if audio_start is None or audio_end is None or not audio_chunks:
        raise ValueError("Source media has insufficient audio")
    if require_video and video_start is None:
        raise ValueError("Conversation media has no decoded video frames")

    # Work from decoded frame PTS, not container duration or independent A/V rebasing.
    origin = min(audio_start, video_start) if video_start is not None else audio_start
    source_duration = max(audio_end, video_end or audio_end) - origin
    if abs(source_duration - excerpt.duration_ms) > EDGE_TOLERANCE_MS:
        raise ValueError(
            "Decoded source duration does not match the manifest: "
            f"{source_duration:.3f} ms versus {excerpt.duration_ms:.3f} ms"
        )
    duration_error = audio_end - audio_start - source_audio_ms
    if abs(duration_error) > TIMESTAMP_TOLERANCE_MS:
        raise ValueError("Source audio timestamps drift from their decoded sample duration")
    offset = audio_start - origin
    if offset > EDGE_TOLERANCE_MS:
        raise ValueError(f"Source audio starts {offset:.3f} ms after the media origin")
    tail = excerpt.duration_ms - (audio_end - origin)
    if abs(tail) > EDGE_TOLERANCE_MS:
        raise ValueError(f"Source audio ends {abs(tail):.3f} ms away from the excerpt end")

    pcm = np.concatenate(audio_chunks).astype(np.int16)
    resampled_ms = len(pcm) / SAMPLE_RATE * 1000
    if abs(resampled_ms - source_audio_ms) > TIMESTAMP_TOLERANCE_MS:
        raise ValueError("Resampled audio duration differs from decoded source samples")
    leading_samples = round(offset * SAMPLE_RATE / 1000)
    target_samples = round(excerpt.duration_ms * SAMPLE_RATE / 1000)
    aligned = np.pad(pcm, (leading_samples, 0))
    if len(aligned) < target_samples:
        aligned = np.pad(aligned, (0, target_samples - len(aligned)))
    else:
        aligned = aligned[:target_samples]
    metadata: MediaTiming = {
        "origin_ms": origin,
        "video_start_ms": video_start - origin if video_start is not None else None,
        "video_end_ms": video_end - origin if video_end is not None else None,
        "video_frames": video_frames,
        "audio_start_ms": offset,
        "audio_end_ms": audio_end - origin,
        "source_duration_ms": source_duration,
        "expected_duration_ms": excerpt.duration_ms,
        "leading_silence_ms": leading_samples / SAMPLE_RATE * 1000,
        "trailing_silence_ms": max(0.0, tail),
        "trimmed_audio_tail_ms": max(0.0, -tail),
        "max_audio_timestamp_error_ms": max_error,
        "audio_duration_error_ms": duration_error,
        "sample_rate": SAMPLE_RATE,
        "audio_samples": len(aligned),
    }
    return aligned, metadata


def prepare_media(excerpt: Media, output_dir: Path, *, require_video: bool) -> PreparedMedia:
    pcm, metadata = _decode_excerpt(excerpt, require_video=require_video)
    output_dir.mkdir(parents=True, exist_ok=True)
    clips: list[AudioClip] = []
    clip_samples = SAMPLE_RATE * CLIP_MS // 1000
    for index, start in enumerate(range(0, len(pcm), clip_samples)):
        end = min(len(pcm), start + clip_samples)
        path = output_dir / f"clip-{index:04d}.wav"
        path.write_bytes(wav_bytes(pcm[start:end]))
        clips.append(
            {
                "path": path,
                "start_ms": start / SAMPLE_RATE * 1000,
                "end_ms": end / SAMPLE_RATE * 1000,
            }
        )
    return {"metadata": metadata, "clips": clips}


def prepare_enrollment(excerpt: Media, destination: Path) -> MediaTiming:
    pcm, metadata = _decode_excerpt(excerpt, require_video=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(wav_bytes(pcm))
    return metadata


def iter_video_frames(path: Path, *, include_audio: bool) -> Iterator[tuple[float, bytes]]:
    """Yield frames on their original A/V timeline, holding only one JPEG at a time."""
    try:
        with av.open(str(path)) as container:
            if not container.streams.video:
                raise ValueError("Source media has no video track")
            if include_audio and not container.streams.audio:
                raise ValueError("Source media has no audio track")
            audio = container.streams.audio[0] if include_audio else None
            video = container.streams.video[0]
            # Discover the common decoded origin in a separate bounded pass: decoding
            # either stream to EOF first would consume packets from the other stream.
            first_audio = first_video = None
            for frame in container.decode(*([audio, video] if audio is not None else [video])):
                if isinstance(frame, av.AudioFrame) and first_audio is None:
                    first_audio = _timestamp_ms(frame)
                elif isinstance(frame, av.VideoFrame) and first_video is None:
                    first_video = _timestamp_ms(frame)
                if first_video is not None and (audio is None or first_audio is not None):
                    break
            if first_video is None or (audio is not None and first_audio is None):
                raise ValueError("Source media is missing decoded frames")
            origin = min(first_audio, first_video) if first_audio is not None else first_video
        with av.open(str(path)) as container:
            previous = None
            for frame in container.decode(video=0):
                timestamp = _timestamp_ms(frame) - origin
                if previous is not None and timestamp <= previous:
                    raise ValueError("Source video timestamps are not strictly increasing")
                previous = timestamp
                image = frame.to_ndarray(format="bgr24")
                height, width = image.shape[:2]
                resized = cv2.resize(image, (640, round(height * 640 / width)))
                ok, encoded = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not ok:
                    raise ValueError("Source video frame could not be encoded as JPEG")
                yield timestamp, encoded.tobytes()
    except av.FFmpegError as exc:
        raise ValueError("Source video could not be decoded") from exc


def inspect_video(excerpt: Media) -> dict:
    previous = None
    count = 0
    end_ms = 0.0
    with av.open(str(excerpt.path)) as container:
        if not container.streams.video:
            raise ValueError("Source media has no video track")
        stream = container.streams.video[0]
        origin = None
        for frame in container.decode(stream):
            timestamp = _timestamp_ms(frame)
            if previous is not None and timestamp <= previous:
                raise ValueError("Source video timestamps are not strictly increasing")
            previous = timestamp
            origin = timestamp if origin is None else origin
            duration = float(frame.duration * frame.time_base) * 1000
            if duration <= 0 and stream.average_rate:
                duration = float(1000 / stream.average_rate)
            if duration <= 0:
                raise ValueError("Source video has an unknown frame duration")
            end_ms = timestamp - origin + duration
            count += 1
            if end_ms > excerpt.duration_ms + EDGE_TOLERANCE_MS:
                raise ValueError("Decoded video exceeds the manifest duration")
    if not count or abs(end_ms - excerpt.duration_ms) > EDGE_TOLERANCE_MS:
        raise ValueError("Decoded video duration does not match the manifest")
    return {"video_frames": count, "source_duration_ms": end_ms}
