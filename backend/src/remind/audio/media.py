import io
import wave

import av
import cv2
import numpy as np


def audio_is_continuous(stamps):
    return bool(stamps) and all(
        abs(current[0] - (previous[0] + previous[1])) <= 0.005 and current[2:] == previous[2:]
        for previous, current in zip(stamps, stamps[1:], strict=False)
    )


def decode_clip(path):
    frames = []
    audio = []
    audio_start = None
    audio_stamps = []
    with av.open(str(path)) as container:
        if not container.streams.video or not container.streams.audio:
            raise ValueError("Clip requires synchronized video and audio")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for packet in container.demux():
            for frame in packet.decode():
                if frame.pts is None:
                    continue
                stamp = float(frame.pts * frame.time_base)
                if isinstance(frame, av.VideoFrame):
                    if len(frames) >= 310:
                        raise ValueError("Clip too long")
                    image = frame.to_ndarray(format="bgr24")
                    h, w = image.shape[:2]
                    image = cv2.resize(image, (640, round(640 * h / w)))
                    frames.append((stamp, image))
                else:
                    audio_stamps.append(
                        (
                            stamp,
                            frame.samples / frame.sample_rate,
                            frame.sample_rate,
                            frame.layout.name,
                        )
                    )
                    if audio_start is None:
                        audio_start = stamp
                    for chunk in resampler.resample(frame):
                        audio.append(chunk.to_ndarray().reshape(-1))
        for chunk in resampler.resample(None):
            audio.append(chunk.to_ndarray().reshape(-1))
    if len(frames) < 5 or not audio:
        raise ValueError("Clip has insufficient media")
    origin = frames[0][0]
    pcm = np.concatenate(audio).astype(np.int16)
    offset = round(((audio_start or 0) - origin) * 16000)
    pcm = np.pad(pcm, (max(0, offset), 0))[max(0, -offset) :]
    times = np.array([stamp - origin for stamp, _ in frames])
    if times[-1] > 10 or len(pcm) > 16000 * 11:
        raise ValueError("Clip too long")
    continuous = bool(
        np.all(np.diff(times) > 0)
        and np.max(np.diff(times)) < 0.09
        and abs(offset) < 1600
        and audio_is_continuous(audio_stamps)
    )
    return {"frames": [f for _, f in frames], "times": times, "pcm": pcm, "continuous": continuous}


def wav_bytes(pcm):
    target = io.BytesIO()
    with wave.open(target, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm.astype(np.int16).tobytes())
    return target.getvalue()
