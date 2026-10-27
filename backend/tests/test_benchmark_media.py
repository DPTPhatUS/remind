from fractions import Fraction

import av
import cv2
import numpy as np
import pytest

from remind.audio.media import decode_audio
from remind.benchmark.inputs import Media
from remind.benchmark.media import (
    iter_video_frames,
    prepare_enrollment,
    prepare_media,
)


def excerpt(path, duration_ms):
    return Media(
        id="excerpt",
        path=path,
        sha256="0" * 64,
        source_id="source",
        source_start_ms=1000,
        source_end_ms=1000 + duration_ms,
    )


def recording(path, *, seconds=1.0, audio_offset=0.0, video_offset=0.0, jump=0.0):
    """Lossless source whose timestamps and stereo samples are known exactly."""
    rate = 48000
    count = round((seconds - audio_offset) * rate)
    phase = np.arange(count) / rate
    tone = (np.sin(phase * 440 * 2 * np.pi) * 4000).astype(np.int16)
    stereo = np.column_stack((tone, tone)).reshape(-1)
    with av.open(str(path), "w") as output:
        video = output.add_stream("ffv1", rate=10)
        video.width, video.height, video.pix_fmt = 800, 400, "yuv420p"
        audio = output.add_stream("pcm_s16le", rate=rate)
        audio.layout = "stereo"
        for index in range(round((seconds - video_offset) * 10)):
            frame = av.VideoFrame.from_ndarray(np.zeros((400, 800, 3), np.uint8), format="rgb24")
            frame.pts = round((index / 10 + video_offset) * 1000)
            frame.time_base = Fraction(1, 1000)
            output.mux(video.encode(frame))
        for start in range(0, count, 4800):
            frame_audio = av.AudioFrame.from_ndarray(
                stereo[start * 2 : (start + 4800) * 2].reshape(1, -1),
                format="s16",
                layout="stereo",
            )
            frame_audio.sample_rate = rate
            shift = jump if start >= count // 2 else 0
            frame_audio.pts = start + round((audio_offset + shift) * rate)
            frame_audio.time_base = Fraction(1, rate)
            output.mux(audio.encode(frame_audio))
        output.mux(video.encode(None))
        output.mux(audio.encode(None))


def test_stereo_resampling_produces_clean_eight_second_clips_and_partial_tail(tmp_path):
    path = tmp_path / "source.mkv"
    recording(path, seconds=9.2)
    prepared = prepare_media(excerpt(path, 9200), tmp_path / "clips", require_video=True)
    assert [(clip["start_ms"], clip["end_ms"]) for clip in prepared["clips"]] == [
        (0, 8000),
        (8000, 9200),
    ]
    assert prepared["metadata"]["audio_samples"] == 147200
    assert prepared["metadata"]["sample_rate"] == 16000
    assert prepared["metadata"]["video_frames"] == 92
    decoded = [decode_audio(clip["path"]) for clip in prepared["clips"]]
    assert all(clip["continuous"] for clip in decoded)
    assert [len(clip["pcm"]) for clip in decoded] == [128000, 19200]
    # Preserve the 440 Hz tone while converting stereo 48 kHz to mono 16 kHz.
    samples = np.concatenate([clip["pcm"] for clip in decoded])
    frequencies = np.fft.rfftfreq(len(samples), 1 / 16000)
    assert frequencies[np.argmax(abs(np.fft.rfft(samples)))] == pytest.approx(440)


def test_known_audio_leading_offset_is_preserved_and_reported(tmp_path):
    path = tmp_path / "delayed-audio.mkv"
    recording(path, audio_offset=0.04)
    prepared = prepare_media(excerpt(path, 1000), tmp_path / "clips", require_video=True)
    metadata = prepared["metadata"]
    assert metadata["audio_start_ms"] == pytest.approx(40)
    assert metadata["leading_silence_ms"] == pytest.approx(40)
    assert metadata["audio_end_ms"] == pytest.approx(1000)
    pcm = decode_audio(prepared["clips"][0]["path"])["pcm"]
    assert not pcm[:640].any()
    assert np.abs(pcm[640:]).max() > 1000
    assert next(iter_video_frames(path, include_audio=True))[0] == 0


def test_video_delay_and_jpeg_dimensions_preserve_common_av_timeline(tmp_path):
    path = tmp_path / "delayed-video.mkv"
    recording(path, video_offset=0.1)
    prepared = prepare_media(excerpt(path, 1000), tmp_path / "clips", require_video=True)
    assert prepared["metadata"]["video_start_ms"] == pytest.approx(100)
    assert prepared["metadata"]["audio_start_ms"] == 0
    frames = list(iter_video_frames(path, include_audio=True))
    assert [timestamp for timestamp, _ in frames] == pytest.approx(list(range(100, 1000, 100)))
    jpeg = np.frombuffer(frames[0][1], dtype=np.uint8)
    assert cv2.imdecode(jpeg, cv2.IMREAD_COLOR).shape == (320, 640, 3)


@pytest.mark.parametrize("jump", [0.05, -0.03])
def test_actual_source_audio_gaps_and_overlaps_are_rejected(tmp_path, jump):
    path = tmp_path / "broken.mkv"
    recording(path, jump=jump)
    with pytest.raises(ValueError, match="timestamp gap or overlap"):
        prepare_media(excerpt(path, 1000), tmp_path / "clips", require_video=True)
    assert not (tmp_path / "clips").exists()


def test_large_audio_offset_and_wrong_manifest_duration_are_rejected(tmp_path):
    path = tmp_path / "late-audio.mkv"
    recording(path, audio_offset=0.3)
    with pytest.raises(ValueError, match="starts 300"):
        prepare_media(excerpt(path, 1000), tmp_path / "clips", require_video=True)
    with pytest.raises(ValueError, match="duration"):
        prepare_media(excerpt(path, 1500), tmp_path / "clips", require_video=True)


def test_enrollment_wav_is_accepted_by_unchanged_backend_decoder(tmp_path):
    path = tmp_path / "enrollment.mkv"
    recording(path, seconds=8)
    destination = tmp_path / "enrollment" / "sample.wav"
    metadata = prepare_enrollment(excerpt(path, 8000), destination)
    result = decode_audio(destination)
    assert result["continuous"]
    assert len(result["pcm"]) == 128000
    assert metadata["max_audio_timestamp_error_ms"] < 0.001
    assert metadata["leading_silence_ms"] == 0
    assert metadata["trailing_silence_ms"] == 0


def test_audio_only_enrollment_uses_original_samples(tmp_path):
    from remind.audio.media import wav_bytes

    path = tmp_path / "sample.wav"
    samples = np.arange(128000, dtype=np.int16)
    path.write_bytes(wav_bytes(samples))
    destination = tmp_path / "prepared.wav"
    metadata = prepare_enrollment(excerpt(path, 8000), destination)
    np.testing.assert_array_equal(decode_audio(destination)["pcm"], samples)
    assert metadata["video_start_ms"] is None
    with pytest.raises(ValueError, match="no video"):
        prepare_media(excerpt(path, 8000), tmp_path / "clips", require_video=True)


def test_invalid_media_fails_before_writing_prepared_audio(tmp_path):
    path = tmp_path / "invalid.mp4"
    path.write_bytes(b"not a recording")
    with pytest.raises(ValueError, match="could not be decoded"):
        prepare_enrollment(excerpt(path, 8000), tmp_path / "sample.wav")
    assert not (tmp_path / "sample.wav").exists()


def test_face_replay_accepts_video_without_audio(tmp_path):
    from remind.benchmark.media import inspect_video

    path = tmp_path / "face.mkv"
    with av.open(str(path), "w") as output:
        stream = output.add_stream("ffv1", rate=10)
        stream.width, stream.height, stream.pix_fmt = 320, 160, "yuv420p"
        for index in range(10):
            frame = av.VideoFrame.from_ndarray(np.zeros((160, 320, 3), np.uint8), format="rgb24")
            frame.pts = index
            frame.time_base = Fraction(1, 10)
            output.mux(stream.encode(frame))
        output.mux(stream.encode(None))
    assert inspect_video(excerpt(path, 1000))["video_frames"] == 10
    frames = list(iter_video_frames(path, include_audio=False))
    assert len(frames) == 10
    assert frames[0][0] == 0
    with pytest.raises(ValueError, match="audio track"):
        list(iter_video_frames(path, include_audio=True))
