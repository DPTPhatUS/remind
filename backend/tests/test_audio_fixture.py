import hashlib
import json
import shutil
import subprocess

import av
import pytest

from remind.audio.media import SAMPLE_RATE, decode_audio
from remind.benchmark.audio_fixture import generate_fixture
from remind.benchmark.conversation_metrics import score_facts


def test_generated_conversations_have_decodable_clips_and_independent_labels(tmp_path):
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("Synthetic audio generation requires FFmpeg")
    filters = subprocess.run(
        [executable, "-hide_banner", "-filters"], capture_output=True, text=True, check=True
    ).stdout
    if " flite " not in filters:
        pytest.skip("Synthetic audio generation requires FFmpeg's Flite filter")

    manifest = json.loads(generate_fixture(tmp_path).read_text())
    assert manifest["source_kind"] == "synthetic"
    assert manifest["voices"] == {"user": "rms", "visitor": "slt"}
    assert len(manifest["enrollment"]) == 3
    assert len({sample["sha256"] for sample in manifest["enrollment"]}) == 3
    enrollment_texts = {sample["text"] for sample in manifest["enrollment"]}
    for sample in manifest["enrollment"]:
        path = tmp_path / sample["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sample["sha256"]
        decoded = decode_audio(path)
        assert decoded["continuous"]
        assert 4 <= len(decoded["pcm"]) / SAMPLE_RATE <= 8

    assert len(manifest["scenarios"]) == 6
    for scenario in manifest["scenarios"]:
        for clip in scenario["clips"]:
            path = tmp_path / clip["path"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == clip["sha256"]
            with av.open(str(path)) as recording:
                stream = recording.streams.audio[0]
                assert stream.codec_context.name == "opus"
                assert stream.codec_context.sample_rate == 48000
            decoded = decode_audio(path)
            assert decoded["continuous"]
            assert len(decoded["pcm"]) == 8 * SAMPLE_RATE
            previous_end = 0
            for turn in clip["turns"]:
                assert previous_end <= turn["start_ms"] < turn["end_ms"] <= 8000
                assert turn["role"] in {"user", "visitor"}
                assert turn["text"] not in enrollment_texts
                previous_end = turn["end_ms"]

    hard_case = next(item for item in manifest["scenarios"] if item["id"] == "short_confirmation")
    reply = hard_case["clips"][1]["turns"][0]
    assert reply["role"] == "visitor"
    assert reply["expected_abstention"]
    assert reply["end_ms"] - reply["start_ms"] < 1500
    coverage = score_facts(hard_case["expected_facts"], [])["fact_coverage"]
    assert coverage == {"numerator": 0, "denominator": 3, "rate": 0}
