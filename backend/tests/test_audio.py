import io
import wave

import av
import numpy as np
import pytest

from remind.audio.media import (
    VAD_FRAME_SAMPLES,
    audio_is_continuous,
    decode_audio,
    has_speech,
    wav_bytes,
)
from remind.audio.speaker import MODEL, UserVoiceVerifier
from remind.config import Settings
from remind.vision.models import ModelRegistry


def vector(score=1.0):
    value = np.zeros(192, dtype=np.float32)
    value[:2] = [score, np.sqrt(max(0, 1 - score**2))]
    return value


def pcm(seconds=3):
    return np.ones(round(16000 * seconds), dtype=np.int16) * 1000


def segment(sid="s", speaker="A", start=0, end=3000):
    return {"id": sid, "speaker": speaker, "start_ms": start, "end_ms": end, "text": "Hello"}


@pytest.fixture
def verifier(tmp_path, monkeypatch):
    result = UserVoiceVerifier(Settings(), ModelRegistry(tmp_path))
    monkeypatch.setattr(result, "_speech", lambda chunk: (chunk, len(chunk) / 16000))
    monkeypatch.setattr(result, "_embedding", lambda _: vector())
    return result


def profile():
    return {"model": MODEL, "embeddings": [vector().tolist()] * 3, "version": 1}


def test_speech_detection_rejects_empty_audio_and_digital_silence():
    assert not has_speech(np.zeros(0, dtype=np.int16))
    assert not has_speech(np.zeros(48000, dtype=np.int16))


def test_speech_detection_uses_complete_frames_and_stops_at_speech(monkeypatch):
    frames = []

    class Vad:
        def is_speech(self, frame, sample_rate):
            frames.append(frame)
            assert sample_rate == 16000
            assert len(frame) == VAD_FRAME_SAMPLES * 2
            return len(frames) == 2

    monkeypatch.setattr("webrtcvad.Vad", lambda _: Vad())
    assert not has_speech(np.zeros(VAD_FRAME_SAMPLES - 1, dtype=np.int16))
    assert not frames
    assert has_speech(pcm())
    assert len(frames) == 2


def test_enrollment_requires_three_distinct_usable_samples(verifier):
    enrolled = verifier.enroll([pcm(), pcm(), pcm()])
    assert enrolled["model"] == MODEL
    assert np.asarray(enrolled["embeddings"]).shape == (3, 192)
    with pytest.raises(ValueError, match="three"):
        verifier.enroll([pcm()])
    with pytest.raises(ValueError, match="five"):
        verifier.enroll([pcm()] * 6)
    with pytest.raises(ValueError, match="between 3 and 20"):
        verifier.enroll([pcm(1), pcm(), pcm()])
    with pytest.raises(ValueError, match="PCM16"):
        verifier.enroll([np.full(48000, np.nan), pcm(), pcm()])
    with pytest.raises(ValueError, match="clipped"):
        verifier.enroll([np.full(48000, -32768, dtype=np.int16), pcm(), pcm()])


def test_enrollment_rejects_silence_and_inconsistent_voices(verifier, monkeypatch):
    monkeypatch.setattr(verifier, "_speech", lambda chunk: (chunk, 0.2))
    with pytest.raises(ValueError, match="too little"):
        verifier.enroll([pcm(), pcm(), pcm()])
    monkeypatch.setattr(verifier, "_speech", lambda chunk: (chunk, 3))
    embeddings = iter([vector(), vector(), vector(0)])
    monkeypatch.setattr(verifier, "_embedding", lambda _: next(embeddings))
    with pytest.raises(ValueError, match="inconsistent"):
        verifier.enroll([pcm(), pcm(), pcm()])


@pytest.mark.parametrize("score,role", [(0.9, "user"), (0.5, "uncertain"), (0.1, "visitor")])
def test_cosine_user_visitor_and_abstention_band(verifier, monkeypatch, score, role):
    monkeypatch.setattr(verifier, "_embedding", lambda _: vector(score))
    original = segment()
    result = verifier.classify(pcm(), [original], profile())
    assert result[0]["role"] == role
    assert result[0]["voice_score"] == pytest.approx(score)
    assert "role" not in original


def test_missing_bad_reference_or_nonfinite_audio_abstains(verifier):
    for reference in [None, {}, {"model": "wrong"}, {**profile(), "embeddings": [[float("nan")]]}]:
        assert verifier.classify(pcm(), [segment()], reference)[0]["role"] == "uncertain"
    assert (
        verifier.classify(np.full(48000, np.nan), [segment()], profile())[0]["role"] == "uncertain"
    )


def test_short_speech_and_silence_abstain(verifier, monkeypatch):
    assert verifier.classify(pcm(1), [segment(end=1000)], profile())[0]["role"] == "uncertain"
    monkeypatch.setattr(verifier, "_speech", lambda chunk: (chunk[:0], 0))
    assert verifier.classify(pcm(), [segment()], profile())[0]["role"] == "uncertain"


def test_overlap_rejects_only_affected_segments(verifier):
    segments = [
        segment("a", "A", 0, 1000),
        segment("b", "B", 500, 1500),
        segment("c", "A", 1500, 3500),
        segment("d", "B", 3500, 5500),
    ]
    result = verifier.classify(pcm(6), segments, profile())
    assert [part["role"] for part in result] == ["uncertain", "uncertain", "user", "user"]


@pytest.mark.parametrize("label", [None, "unknown", ["A"]])
def test_unknown_speaker_still_makes_overlapping_speech_uncertain(verifier, label):
    segments = [segment("a", "A", 0, 2000), segment("b", label, 1000, 3000)]
    result = verifier.classify(pcm(), segments, profile())
    assert [part["role"] for part in result] == ["uncertain", "uncertain"]


def test_overflowing_reference_norm_cannot_establish_a_visitor_role(verifier):
    reference = {**profile(), "embeddings": [[1e30] * 192] * 3}
    with np.errstate(over="ignore"):
        result = verifier.classify(pcm(), [segment()], reference)
    assert result[0]["role"] == "uncertain"


def test_speaker_labels_are_local_to_each_clip(verifier, monkeypatch):
    first = verifier.classify(pcm(), [segment(speaker="A")], profile())
    monkeypatch.setattr(verifier, "_embedding", lambda _: vector(0.1))
    second = verifier.classify(pcm(), [segment(speaker="A")], profile())
    assert first[0]["role"] == "user"
    assert second[0]["role"] == "visitor"


@pytest.mark.parametrize("label", [None, "", "unknown", "None", ["A"]])
def test_missing_or_invalid_speaker_label_abstains(verifier, label):
    result = verifier.classify(pcm(), [segment(speaker=label)], profile())
    assert result[0]["role"] == "uncertain"


def test_short_turn_can_use_clear_speech_from_same_speaker(verifier):
    segments = [segment("a", "A", 0, 400), segment("b", "A", 1000, 3000)]
    assert all(part["role"] == "user" for part in verifier.classify(pcm(), segments, profile()))


@pytest.mark.parametrize("start,end", [(-1, 1000), (0, 4000), (float("nan"), 1000), (500, 500)])
def test_bad_timestamps_cannot_become_voice_evidence(verifier, start, end):
    result = verifier.classify(pcm(), [segment(start=start, end=end)], profile())
    assert result[0]["role"] == "uncertain"


def test_real_vad_rejects_digital_silence(tmp_path):
    verifier = UserVoiceVerifier(Settings(), ModelRegistry(tmp_path))
    with pytest.raises(ValueError, match="too little"):
        verifier.enroll([np.zeros(48000, dtype=np.int16)] * 3)


def test_thresholds_require_uncertainty_band():
    with pytest.raises(ValueError, match="below"):
        Settings(voice_user_threshold=0.3, voice_visitor_threshold=0.5)


def test_memory_timezone_validates_iana_identifier():
    assert Settings().memory_timezone == "Asia/Ho_Chi_Minh"
    assert Settings(memory_timezone="Europe/Paris").memory_timezone == "Europe/Paris"
    with pytest.raises(ValueError, match="valid IANA"):
        Settings(memory_timezone="not/a-timezone")


def test_audio_timestamp_gaps_and_format_changes_abstain():
    assert audio_is_continuous([(0, 0.02, 48000, "stereo"), (0.02, 0.02, 48000, "stereo")])
    assert not audio_is_continuous([(0, 0.02, 48000, "stereo"), (0.12, 0.02, 48000, "stereo")])
    assert not audio_is_continuous([(0, 0.02, 48000, "stereo"), (0.02, 0.02, 16000, "mono")])


def test_decode_wav_bytes_and_path(tmp_path):
    data = wav_bytes(pcm())
    path = tmp_path / "speech.wav"
    path.write_bytes(data)
    for source in (path, data):
        result = decode_audio(source)
        np.testing.assert_array_equal(result["pcm"], pcm())
        assert result["continuous"]
        assert set(result) == {"pcm", "continuous"}
    with pytest.raises(ValueError, match="too long"):
        decode_audio(data, max_seconds=2)
    with pytest.raises(ValueError, match="decoded"):
        decode_audio(b"not audio")


@pytest.mark.parametrize("audio_delay,continuous", [(0, True), (24000, False)])
def test_decode_resamples_stereo_and_ignores_video(tmp_path, audio_delay, continuous):
    target = io.BytesIO()
    with wave.open(target, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(np.ones(48000 * 2, dtype=np.int16).tobytes())
    assert len(decode_audio(target.getvalue())["pcm"]) == 16000
    path = tmp_path / "camera.webm"
    with av.open(str(path), "w") as output:
        video = output.add_stream("libvpx", rate=10)
        video.width, video.height, video.pix_fmt = 64, 64, "yuv420p"
        audio = output.add_stream("libopus", rate=48000)
        audio.layout = "mono"
        for i in range(10):
            frame = av.VideoFrame.from_ndarray(np.zeros((64, 64, 3), np.uint8), format="rgb24")
            frame.pts = i
            output.mux(video.encode(frame))
            frame_audio = av.AudioFrame.from_ndarray(
                np.zeros((1, 4800), np.int16), format="s16", layout="mono"
            )
            frame_audio.sample_rate, frame_audio.pts = 48000, i * 4800 + audio_delay
            output.mux(audio.encode(frame_audio))
        output.mux(video.encode(None))
        output.mux(audio.encode(None))
    decoded = decode_audio(path)
    assert 16000 <= len(decoded["pcm"]) <= 16200
    assert decoded["continuous"] is continuous
    assert "frames" not in decoded


def test_bundle_checksums_detect_each_corrupt_asset(tmp_path):
    registry = ModelRegistry(tmp_path)
    payload = b"valid asset"
    import hashlib

    item = {
        "file": "bundle/weights",
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    registry.models = {"ecapa": {"directory": "bundle", "files": [item]}}
    path = tmp_path / "bundle/weights"
    path.parent.mkdir()
    path.write_bytes(payload)
    assert registry.verify("ecapa") == path.parent
    path.write_bytes(b"wrong asset")
    with pytest.raises(ValueError, match="Corrupt"):
        registry.verify("ecapa")
    path.unlink()
    with pytest.raises(FileNotFoundError):
        registry.verify("ecapa")


def test_readiness_reports_missing_models_without_loading(tmp_path):
    verifier = UserVoiceVerifier(Settings(), ModelRegistry(tmp_path))
    result = verifier.readiness()
    assert not result["available"]
    assert result["error"]
    assert verifier._encoder is None


def test_voice_bundle_matches_the_pinned_model():
    registry = ModelRegistry("unused")
    bundle = registry.models["ecapa"]
    assert bundle["source"] == MODEL
    revision = MODEL.split("@")[1]
    assert bundle["files"]
    assert all(f"/resolve/{revision}/" in item["url"] for item in bundle["files"])
