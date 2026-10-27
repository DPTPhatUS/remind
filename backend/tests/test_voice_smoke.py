import hashlib
import io

import av
import numpy as np
import pytest

from remind.audio.media import SAMPLE_RATE, decode_audio
from remind.benchmark.voice_smoke import (
    FIXTURES,
    add_noise,
    build_cases,
    encode_webm,
    fetch_fixtures,
    summarize_cases,
)


def speech_wave(seconds=1):
    time = np.arange(round(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return np.rint(3000 * np.sin(2 * np.pi * 220 * time)).astype(np.int16)


def test_webm_uses_stereo_opus_and_decodes_continuously_at_16khz():
    original = speech_wave()
    encoded = encode_webm(original)
    with av.open(io.BytesIO(encoded)) as container:
        stream = container.streams.audio[0]
        assert stream.codec_context.name == "opus"
        assert stream.codec_context.sample_rate == 48000
        assert stream.codec_context.layout.name == "stereo"
    decoded = decode_audio(encoded)
    assert decoded["continuous"]
    assert decoded["pcm"].dtype == np.int16
    assert len(decoded["pcm"]) == len(original)
    assert np.corrcoef(original, decoded["pcm"])[0, 1] > 0.95


def test_noise_is_reproducible_and_has_the_reported_signal_to_noise_ratio():
    original = speech_wave()
    noisy = add_noise(original)
    np.testing.assert_array_equal(noisy, add_noise(original))
    assert noisy.dtype == np.int16
    signal = original.astype(np.float64)
    error = noisy.astype(np.float64) - signal
    measured_snr = 10 * np.log10(np.mean(signal**2) / np.mean(error**2))
    assert measured_snr == pytest.approx(20, abs=0.3)
    np.testing.assert_array_equal(original, speech_wave())


def test_voice_cases_keep_enrollment_separate_and_annotate_speaker_intervals():
    recordings = {name: speech_wave(3) for name in FIXTURES}
    cases = build_cases(recordings)
    enrollment = {"spk1_snt1.wav", "spk1_snt2.wav", "spk1_snt3.wav"}
    assert all(not enrollment.intersection(case.source_files) for case in cases)
    assert len({case.name for case in cases}) == len(cases)
    sequential = next(case for case in cases if case.name == "two_speakers_sequential")
    assert sequential.expected_roles == ["user", "visitor"]
    assert sequential.segments[1]["start_ms"] - sequential.segments[0]["end_ms"] == 300
    overlap = next(case for case in cases if case.name == "overlapping_human_speech")
    assert overlap.expected_roles == ["uncertain", "uncertain"]
    assert overlap.segments[0]["start_ms"] == overlap.segments[1]["start_ms"]
    missing = next(case for case in cases if case.name == "missing_voice_reference")
    assert not missing.reference_available


def test_summary_separates_abstentions_from_wrong_roles_and_guard_failures():
    cases = [
        {
            "expectations_met": False,
            "turns": [
                {"expected": "user", "role": "user"},
                {"expected": "visitor", "role": "uncertain"},
                {"expected": "visitor", "role": "user"},
            ],
        },
        {
            "expectations_met": False,
            "turns": [
                {"expected": "uncertain", "role": "uncertain"},
                {"expected": "uncertain", "role": "visitor"},
            ],
        },
    ]
    assert summarize_cases(cases) == {
        "case_count": 2,
        "cases_meeting_all_expectations": 0,
        "speech_turns": 3,
        "correct_roles": 1,
        "abstentions": 1,
        "wrong_assignments": 1,
        "guard_turns": 2,
        "correct_guard_abstentions": 1,
        "unsafe_guard_assignments": 1,
    }


def test_cached_public_audio_requires_the_pinned_checksum(tmp_path, monkeypatch):
    payload = b"cached fixture"
    monkeypatch.setattr(
        "remind.benchmark.voice_smoke.FIXTURES",
        {
            "sample.wav": hashlib.sha256(payload).hexdigest(),
        },
    )
    with pytest.raises(FileNotFoundError, match="repeat with --download"):
        fetch_fixtures(tmp_path, download=False)
    path = tmp_path / "sample.wav"
    path.write_bytes(payload)
    fetch_fixtures(tmp_path, download=False)
    path.write_bytes(b"corrupted fixture")
    with pytest.raises(ValueError, match="checksum mismatch"):
        fetch_fixtures(tmp_path, download=False)
