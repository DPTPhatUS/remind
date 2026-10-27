"""Repeatable local voice-verification checks, separate from conversation evaluation.

Run from backend: python -m remind.benchmark.voice_smoke --download
Public SpeechBrain utterances are pinned and checksum verified. Enrollment uses
three distinct utterances. Held-out speech is tested clean, encoded as WebM,
combined into two-speaker clips, and with reproducible noise. Conservative guards
are also exercised. Speaker labels and times are fixture annotations, not cloud
diarization results. Nothing is sent to a transcription or extraction service.
"""

import argparse
import hashlib
import io
import json
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import av
import numpy as np

from remind.audio.media import PCM, SAMPLE_RATE, decode_audio
from remind.audio.speaker import MODEL, UserVoiceVerifier
from remind.benchmark.report import write_json
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


@dataclass
class VoiceCase:
    name: str
    pcm: PCM
    segments: list[dict[str, Any]]
    expected_roles: list[str]
    source_files: tuple[str, ...]
    condition: str
    reference_available: bool = True
    media_format: str = "PCM16 mono at 16 kHz"
    decode_seconds: float = 0
    continuous: bool = True


def annotated_segment(
    pcm: PCM, speaker: str = "A", start_ms: float = 0, ident: str = "test"
) -> dict[str, Any]:
    return {
        "id": ident,
        "speaker": speaker,
        "start_ms": start_ms,
        "end_ms": start_ms + len(pcm) * 1000 / SAMPLE_RATE,
        "text": "Public fixture; text is not used by voice classification.",
    }


def encode_webm(pcm: PCM) -> bytes:
    """Encode 16 kHz mono speech as 48 kHz stereo Opus for a real decode check."""
    target = io.BytesIO()
    with av.open(target, mode="w", format="webm") as output:
        stream = output.add_stream("libopus", rate=48000)
        stream.layout = "stereo"
        stream.bit_rate = 64000
        resampler = av.AudioResampler(format="flt", layout="stereo", rate=48000)
        frame = av.AudioFrame.from_ndarray(pcm[None, :], format="s16", layout="mono")
        frame.sample_rate = SAMPLE_RATE
        frame.time_base = Fraction(1, SAMPLE_RATE)
        frame.pts = 0
        for converted in [*resampler.resample(frame), *resampler.resample(None)]:
            output.mux(stream.encode(converted))
        output.mux(stream.encode(None))
    return target.getvalue()


def add_noise(pcm: PCM, snr_db: float = 20, seed: int = 20261027) -> PCM:
    """Add repeatable white noise at a stated signal-to-noise ratio."""
    signal = pcm.astype(np.float64)
    rms = float(np.sqrt(np.mean(signal**2)))
    noise = np.random.default_rng(seed).normal(0, rms / 10 ** (snr_db / 20), len(pcm))
    return np.clip(np.rint(signal + noise), -32768, 32767).astype(np.int16)


def build_cases(recordings: dict[str, PCM]) -> list[VoiceCase]:
    held_out = [
        ("spk1_snt4.wav", "user"),
        ("spk1_snt5.wav", "user"),
        ("spk2_snt1.wav", "visitor"),
        ("spk2_snt2.wav", "visitor"),
    ]
    cases = [
        VoiceCase(
            f"clean_{name}",
            recordings[name],
            [annotated_segment(recordings[name])],
            [role],
            (name,),
            "Held-out clean speech; anonymous A label reused across clips.",
        )
        for name, role in held_out
    ]
    user = recordings["spk1_snt4.wav"]
    visitor = recordings["spk2_snt1.wav"]
    for name, role in (held_out[0], held_out[2]):
        encoded = encode_webm(recordings[name])
        started = time.perf_counter()
        decoded = decode_audio(encoded)
        cases.append(
            VoiceCase(
                f"webm_{name}",
                decoded["pcm"],
                [annotated_segment(decoded["pcm"])],
                [role],
                (name,),
                "Opus round-trip plus stereo downmix and 48-to-16 kHz resampling.",
                media_format="WebM Opus stereo at 48 kHz, decoded to mono PCM16 at 16 kHz",
                decode_seconds=time.perf_counter() - started,
                continuous=decoded["continuous"],
            )
        )
    gap = np.zeros(round(0.3 * SAMPLE_RATE), dtype=np.int16)
    sequential = np.concatenate([user, gap, visitor])
    cases.append(
        VoiceCase(
            "two_speakers_sequential",
            sequential,
            [
                annotated_segment(user, "A", ident="user"),
                annotated_segment(
                    visitor, "B", (len(user) + len(gap)) * 1000 / SAMPLE_RATE, "visitor"
                ),
            ],
            ["user", "visitor"],
            (held_out[0][0], held_out[2][0]),
            "Two held-out human speakers in one clip, separated by 300 ms of silence.",
        )
    )
    silence = np.zeros(3 * SAMPLE_RATE, dtype=np.int16)
    cases.append(
        VoiceCase(
            "silence",
            silence,
            [annotated_segment(silence)],
            ["uncertain"],
            (),
            "Digital silence must not establish a speaker role.",
        )
    )
    for name, role in (held_out[0], held_out[2]):
        short = recordings[name][: SAMPLE_RATE // 2]
        cases.append(
            VoiceCase(
                f"short_{role}",
                short,
                [annotated_segment(short)],
                ["uncertain"],
                (name,),
                "A 500 ms turn alone has insufficient usable speech for verification.",
            )
        )
    size = min(len(user), len(visitor))
    overlap = np.rint((user[:size].astype(np.float64) + visitor[:size]) / 2).astype(np.int16)
    cases.append(
        VoiceCase(
            "overlapping_human_speech",
            overlap,
            [
                annotated_segment(overlap, "A", ident="user"),
                annotated_segment(overlap, "B", ident="visitor"),
            ],
            ["uncertain", "uncertain"],
            (held_out[0][0], held_out[2][0]),
            "Actual mixed voices with annotated overlapping intervals; both must abstain.",
        )
    )
    cases.append(
        VoiceCase(
            "unknown_speaker_label",
            user,
            [annotated_segment(user, "unknown")],
            ["uncertain"],
            (held_out[0][0],),
            "An unknown label cannot establish voice evidence.",
        )
    )
    cases.append(
        VoiceCase(
            "missing_voice_reference",
            user,
            [annotated_segment(user)],
            ["uncertain"],
            (held_out[0][0],),
            "A missing user reference must disable role assignment.",
            reference_available=False,
        )
    )
    for name, role in (held_out[0], held_out[2]):
        noisy = add_noise(recordings[name])
        cases.append(
            VoiceCase(
                f"noise_20db_{role}",
                noisy,
                [annotated_segment(noisy)],
                [role],
                (name,),
                "Deterministic 20 dB SNR white noise, seed 20261027; thresholds unchanged.",
            )
        )
    return cases


def summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    speech = [turn for case in cases for turn in case["turns"] if turn["expected"] != "uncertain"]
    guards = [turn for case in cases for turn in case["turns"] if turn["expected"] == "uncertain"]
    return {
        "case_count": len(cases),
        "cases_meeting_all_expectations": sum(case["expectations_met"] for case in cases),
        "speech_turns": len(speech),
        "correct_roles": sum(turn["role"] == turn["expected"] for turn in speech),
        "abstentions": sum(turn["role"] == "uncertain" for turn in speech),
        "wrong_assignments": sum(
            turn["role"] not in {turn["expected"], "uncertain"} for turn in speech
        ),
        "guard_turns": len(guards),
        "correct_guard_abstentions": sum(turn["role"] == "uncertain" for turn in guards),
        "unsafe_guard_assignments": sum(turn["role"] != "uncertain" for turn in guards),
    }


def fetch_fixtures(directory: Path, download: bool) -> None:
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


def run_smoke(settings: Settings, download: bool = False) -> dict[str, Any]:
    root = settings.data_dir / "voice-smoke"
    fetch_fixtures(root, download)
    verifier = UserVoiceVerifier(settings, ModelRegistry(settings.data_dir / "models"))
    recordings = {name: decode_audio(root / name)["pcm"] for name in FIXTURES}
    enrollment_files = ["spk1_snt1.wav", "spk1_snt2.wav", "spk1_snt3.wav"]
    # Public utterances are slightly shorter than the helper UI's recordings.
    # Silence padding meets the input duration limit without adding speech.
    samples = [
        np.pad(recordings[name], (0, max(0, 3 * SAMPLE_RATE - len(recordings[name]))))
        for name in enrollment_files
    ]
    started = time.perf_counter()
    reference = verifier.enroll(samples)
    enrollment_seconds = time.perf_counter() - started
    different_speaker = recordings["spk2_snt1.wav"]
    different_speaker = np.pad(
        different_speaker, (0, max(0, 3 * SAMPLE_RATE - len(different_speaker)))
    )
    enrollment_rejections = []
    for name, invalid_samples in [
        ("silence", [np.zeros(3 * SAMPLE_RATE, dtype=np.int16)] * 3),
        ("inconsistent_human_speakers", [samples[0], samples[1], different_speaker]),
    ]:
        started = time.perf_counter()
        reason = None
        try:
            verifier.enroll(invalid_samples)
        except ValueError as exc:
            reason = str(exc)
        enrollment_rejections.append(
            {
                "name": name,
                "expected": "rejected",
                "rejected": reason is not None,
                "reason": reason,
                "processing_seconds": time.perf_counter() - started,
            }
        )
    cases = []
    for case in build_cases(recordings):
        started = time.perf_counter()
        result = verifier.classify(
            case.pcm, case.segments, reference if case.reference_available else None
        )
        classification_seconds = time.perf_counter() - started
        turns = [
            {
                "segment_id": actual["id"],
                "expected": expected,
                "role": actual["role"],
                "voice_score": actual.get("voice_score"),
            }
            for actual, expected in zip(result, case.expected_roles, strict=True)
        ]
        cases.append(
            {
                "name": case.name,
                "source_files": case.source_files,
                "condition": case.condition,
                "media_format": case.media_format,
                "audio_seconds": len(case.pcm) / SAMPLE_RATE,
                "continuous": case.continuous,
                "decode_seconds": case.decode_seconds,
                "classification_seconds": classification_seconds,
                "turns": turns,
                "expectations_met": case.continuous
                and all(turn["role"] == turn["expected"] for turn in turns),
            }
        )
    summary = summarize_cases(cases)
    return {
        "model": MODEL,
        "fixture_source": f"https://github.com/speechbrain/speechbrain/tree/{REVISION}/tests/samples/ASR",
        "enrollment_files": enrollment_files,
        "enrollment_silence_padded_to_seconds": 3,
        "enrollment_seconds": enrollment_seconds,
        "enrollment_rejections": enrollment_rejections,
        "user_threshold": settings.voice_user_threshold,
        "visitor_threshold": settings.voice_visitor_threshold,
        "speaker_annotations": (
            "Manually supplied fixture labels and intervals, not diarization output"
        ),
        "summary": summary,
        "cases": cases,
        "limitations": (
            "Two clean public speakers with reused held-out utterances under controlled "
            "transformations. Overlap rejection depends on supplied interval annotations; "
            "this does not measure automatic overlap detection or diarization. White noise "
            "does not represent room acoustics, TV speech, accents or microphone variation. "
            "No real-world Remind accuracy or threshold calibration is established. "
            "No transcription or fact extraction is exercised."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = Settings() if args.data_dir is None else Settings(data_dir=args.data_dir)
    report = run_smoke(settings, args.download)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        write_json(report, args.output)
    print(rendered)
    summary = report["summary"]
    if summary["cases_meeting_all_expectations"] != summary["case_count"] or not all(
        check["rejected"] for check in report["enrollment_rejections"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
