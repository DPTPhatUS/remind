"""Repeatable, opt-in real-model check; this is not a Remind accuracy benchmark.

Run from backend: python -m remind.audio.smoke --download
Public SpeechBrain utterances are pinned and checksum verified. Enrollment uses
three distinct utterances; tests use separate same-speaker and different-speaker
utterances. Nothing is sent to a transcription or extraction service.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.request import urlopen

import numpy as np

from remind.audio.media import decode_audio
from remind.audio.speaker import MODEL, UserVoiceVerifier
from remind.config import Settings
from remind.vision.models import ModelRegistry

REVISION = "c0241278f93ef02cd5191f03caf4e5f8e1292bf6"
FIXTURES = {
    "spk1_snt1.wav": "2f7315ccf543b6368528b098cd895098c154f222cd55ff7b5f66b50feb383c56",
    "spk1_snt2.wav": "e1f125a318f4026991bf78f5c41481be0fbcf9b3b2fd72284f9824cb851c3034",
    "spk1_snt3.wav": "dc85f251ecb6f89652e8e3add9f35a39e86cb64a48384c89255437fd0f1bbc69",
    "spk1_snt4.wav": "719e441a93a3ec220dfc4337c30944aa1774847739ae9d461c3280b612cf869d",
    "spk1_snt5.wav": "6972d80554dfb14e5ad23c7b355a870e9beb18ab2331fbd4b12ff1777e6ed277",
    "spk2_snt1.wav": "5f3f534ba99f159358c6ee2e4fb5e42b3b9399f37f4e290651405c76095f26f0",
    "spk2_snt2.wav": "589bcda06796c124544138d7ff40562c146be5e06c1765f2fb4d27c22d19ea8a",
}


def fetch_fixtures(directory, download):
    directory.mkdir(parents=True, exist_ok=True)
    for name, digest in FIXTURES.items():
        path = directory / name
        if not path.is_file() and download:
            url = (
                f"https://raw.githubusercontent.com/speechbrain/speechbrain/{REVISION}"
                f"/tests/samples/ASR/{name}"
            )
            with urlopen(url, timeout=30) as response:
                payload = response.read(2 * 1024 * 1024)
            if hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError(f"Fixture checksum mismatch: {name}")
            path.write_bytes(payload)
        if not path.is_file():
            raise FileNotFoundError(f"Missing {name}; repeat with --download")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Fixture checksum mismatch: {name}")


def run_smoke(settings, download=False):
    root = settings.data_dir / "voice-smoke"
    fetch_fixtures(root, download)
    verifier = UserVoiceVerifier(settings, ModelRegistry(settings.data_dir / "models"))
    recordings = {name: decode_audio(root / name)["pcm"] for name in FIXTURES}
    enrollment_files = ["spk1_snt1.wav", "spk1_snt2.wav", "spk1_snt3.wav"]
    # Public utterances are slightly shorter than the helper UI's recordings.
    # Silence padding meets the input duration limit without adding speech.
    samples = [
        np.pad(recordings[name], (0, max(0, 48000 - len(recordings[name]))))
        for name in enrollment_files
    ]
    started = time.perf_counter()
    reference = verifier.enroll(samples)
    enrollment_seconds = time.perf_counter() - started
    rows = []
    for name, expected in [
        ("spk1_snt4.wav", "user"),
        ("spk1_snt5.wav", "user"),
        ("spk2_snt1.wav", "visitor"),
        ("spk2_snt2.wav", "visitor"),
    ]:
        pcm = recordings[name]
        segment = {
            "id": "test",
            "speaker": "A",  # Same anonymous label deliberately reused between calls.
            "start_ms": 0,
            "end_ms": len(pcm) / 16,
            "text": "Public fixture; text is not used by voice classification.",
        }
        started = time.perf_counter()
        result = verifier.classify(pcm, [segment], reference)[0]
        rows.append(
            {
                "fixture": name,
                "expected": expected,
                "role": result["role"],
                "voice_score": result.get("voice_score"),
                "audio_seconds": len(pcm) / 16000,
                "processing_seconds": time.perf_counter() - started,
            }
        )
    correct = sum(row["role"] == row["expected"] for row in rows)
    return {
        "model": MODEL,
        "fixture_source": f"https://github.com/speechbrain/speechbrain/tree/{REVISION}/tests/samples/ASR",
        "enrollment_files": enrollment_files,
        "enrollment_silence_padded_to_seconds": 3,
        "enrollment_seconds": enrollment_seconds,
        "user_threshold": settings.voice_user_threshold,
        "visitor_threshold": settings.voice_visitor_threshold,
        "correct": correct,
        "total": len(rows),
        "abstentions": sum(row["role"] == "uncertain" for row in rows),
        "wrong_assignments": sum(row["role"] not in (row["expected"], "uncertain") for row in rows),
        "rows": rows,
        "limitations": (
            "Four clean public utterances from two speakers; verifies installation and "
            "held-out inference only. No real-world Remind accuracy or threshold calibration "
            "is established. No fact extraction is exercised."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = Settings() if args.data_dir is None else Settings(data_dir=args.data_dir)
    report = run_smoke(settings, args.download)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered)
    if report["correct"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
