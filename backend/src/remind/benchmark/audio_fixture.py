"""Generate labelled synthetic conversations without calling cloud services.

Run with python -m remind.benchmark.audio_fixture --output-dir /tmp/remind-audio.
FFmpeg must include the Flite speech-synthesis filter and the libopus encoder.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

SAMPLE_RATE = 48000
CLIP_MS = 8000
VOICES = {"user": "rms", "visitor": "slt"}
ENROLLMENT_TEXTS = [
    "Today I am recording my voice for this memory assistant. I am speaking by myself.",
    "Please listen to this sample of my voice. The room is quiet and I am speaking clearly.",
    "This is another recording for the helper setup. I can speak at a calm and steady pace.",
]


@dataclass(frozen=True)
class ScriptTurn:
    role: Literal["user", "visitor"]
    text: str
    expected_abstention: bool = False


@dataclass(frozen=True)
class Scenario:
    id: str
    clips: list[list[ScriptTurn]]
    expected_facts: list[dict[str, Any]]
    note: str = ""


def expected_fact(subject: str, predicate: str, value: str, present: bool = True) -> dict[str, Any]:
    return {
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "temporal_status": "current",
        "present": present,
    }


SCENARIOS = [
    Scenario(
        id="identity",
        clips=[
            [
                ScriptTurn("user", "Please remind me of your name."),
                ScriptTurn("visitor", "My name is Anna. I am your daughter. I am thirty two."),
            ]
        ],
        expected_facts=[
            expected_fact("visitor", "name", "Anna"),
            expected_fact("visitor", "relationship", "daughter"),
            expected_fact("visitor", "age", "32"),
        ],
    ),
    Scenario(
        id="confirmation_across_clips",
        clips=[
            [
                ScriptTurn(
                    "user",
                    "Your name is Anna, you are thirty two, and you are my daughter, right?",
                )
            ],
            [
                ScriptTurn(
                    "visitor",
                    "Yes, that is right. You remembered all of those details correctly.",
                )
            ],
        ],
        expected_facts=[
            expected_fact("visitor", "name", "Anna"),
            expected_fact("visitor", "relationship", "daughter"),
            expected_fact("visitor", "age", "32"),
        ],
    ),
    Scenario(
        id="unconfirmed_user_claims",
        clips=[
            [
                ScriptTurn(
                    "user",
                    "Your name is Ben, you are forty eight, and you are my brother, right?",
                )
            ],
            [
                ScriptTurn(
                    "visitor",
                    "No, that is not correct. Please do not assume any of those things about me.",
                )
            ],
        ],
        expected_facts=[
            expected_fact("visitor", "name", "Ben", present=False),
            expected_fact("visitor", "relationship", "brother", present=False),
            expected_fact("visitor", "age", "48", present=False),
        ],
    ),
    Scenario(
        id="related_person_subject",
        clips=[
            [
                ScriptTurn(
                    "visitor",
                    "My brother's name is Daniel. He is forty eight years old. I am thirty two.",
                )
            ]
        ],
        expected_facts=[
            expected_fact("brother", "name", "Daniel"),
            expected_fact("brother", "age", "48"),
            expected_fact("visitor", "age", "32"),
            expected_fact("visitor", "name", "Daniel", present=False),
            expected_fact("visitor", "age", "48", present=False),
        ],
    ),
    Scenario(
        id="explicit_age_correction",
        clips=[
            [ScriptTurn("visitor", "I am forty two years old. I am telling you my own age.")],
            [
                ScriptTurn(
                    "visitor",
                    "Sorry, I misspoke about my age earlier. I am thirty two, not forty two.",
                )
            ],
        ],
        expected_facts=[
            expected_fact("visitor", "age", "32"),
            expected_fact("visitor", "age", "42", present=False),
        ],
        note="The earlier age should remain in history but leave established current facts.",
    ),
    Scenario(
        id="short_confirmation",
        clips=[
            [
                ScriptTurn(
                    "user", "Do you work as a nurse at the hospital, and do you enjoy gardening?"
                )
            ],
            [ScriptTurn("visitor", "Yes.", expected_abstention=True)],
        ],
        expected_facts=[
            expected_fact("visitor", "occupation", "nurse"),
            expected_fact("visitor", "workplace", "hospital"),
            expected_fact("visitor", "interest", "gardening"),
        ],
        note=(
            "The visitor really says yes, so speaker truth remains visitor. The isolated "
            "reply is deliberately too short for reliable verification. Expected abstention "
            "describes the current safety behavior, not successful speaker recognition or "
            "useful-fact coverage. The three confirmed facts remain in the useful-fact coverage "
            "denominator even when verification abstains. The system should not learn them "
            "from uncertain speech, and that safe abstention still counts as missed useful "
            "information. Equivalent predicates or values need manual review."
        ),
    ),
]


def run_ffmpeg(executable: str, arguments: list[str], pcm: bytes | None = None) -> None:
    try:
        subprocess.run(
            [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments],
            input=pcm,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"FFmpeg failed: {detail}") from exc


def synthesize(executable: str, text: str, voice: str, work: Path) -> NDArray[np.int16]:
    text_path = work / "utterance.txt"
    wav_path = work / "utterance.wav"
    text_path.write_text(text)
    run_ffmpeg(
        executable,
        [
            "-f",
            "lavfi",
            "-i",
            f"flite=textfile={text_path}:voice={voice}",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ],
    )
    with wave.open(str(wav_path), "rb") as source:
        pcm = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").copy()
    active = np.flatnonzero(np.abs(pcm.astype(np.int32)) >= 120)
    if not len(active):
        raise ValueError("Speech synthesis produced no usable signal")
    margin = SAMPLE_RATE // 20
    return pcm[max(0, int(active[0]) - margin) : int(active[-1]) + margin + 1]


def file_reference(path: Path, output_dir: Path) -> dict[str, str]:
    with path.open("rb") as source:
        checksum = hashlib.file_digest(source, "sha256").hexdigest()
    return {"path": path.relative_to(output_dir).as_posix(), "sha256": checksum}


def write_enrollment(path: Path, pcm: NDArray[np.int16]) -> None:
    duration = len(pcm) / SAMPLE_RATE
    if not 4 <= duration <= 8:
        raise ValueError(f"Enrollment utterance lasts {duration:.2f}s; expected four to eight")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm.astype("<i2").tobytes())


def generate_fixture(output_dir: Path) -> Path:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise FileNotFoundError("Install FFmpeg with the Flite filter and libopus encoder")
    output_dir.mkdir(parents=True, exist_ok=True)
    enrollment_dir = output_dir / "enrollment"
    enrollment_dir.mkdir(exist_ok=True)
    enrollment = []
    scenarios = []
    with tempfile.TemporaryDirectory(prefix="remind-speech-", dir="/tmp") as temporary:
        work = Path(temporary)
        for index, text in enumerate(ENROLLMENT_TEXTS, start=1):
            pcm = synthesize(executable, text, VOICES["user"], work)
            path = enrollment_dir / f"user-{index}.wav"
            write_enrollment(path, pcm)
            enrollment.append(
                {
                    **file_reference(path, output_dir),
                    "text": text,
                    "duration_ms": len(pcm) * 1000 / SAMPLE_RATE,
                }
            )

        for scenario in SCENARIOS:
            directory = output_dir / scenario.id
            directory.mkdir(exist_ok=True)
            clips = []
            for index, script in enumerate(scenario.clips):
                recording = np.zeros(SAMPLE_RATE * CLIP_MS // 1000, dtype=np.int16)
                cursor = SAMPLE_RATE // 2
                turns = []
                for turn in script:
                    pcm = synthesize(executable, turn.text, VOICES[turn.role], work)
                    end = cursor + len(pcm)
                    if end > len(recording) - SAMPLE_RATE // 4:
                        raise ValueError(
                            f"{scenario.id} clip {index + 1} exceeds its eight-second window; "
                            "shorten its script instead of cutting speech"
                        )
                    recording[cursor:end] = pcm
                    turns.append(
                        {
                            "start_ms": cursor * 1000 / SAMPLE_RATE,
                            "end_ms": end * 1000 / SAMPLE_RATE,
                            "role": turn.role,
                            "text": turn.text,
                            "expected_abstention": turn.expected_abstention,
                        }
                    )
                    cursor = end + SAMPLE_RATE // 3
                path = directory / f"clip-{index + 1:02d}.webm"
                run_ffmpeg(
                    executable,
                    [
                        "-f",
                        "s16le",
                        "-ar",
                        str(SAMPLE_RATE),
                        "-ac",
                        "1",
                        "-i",
                        "pipe:0",
                        "-c:a",
                        "libopus",
                        "-b:a",
                        "64k",
                        "-ar",
                        str(SAMPLE_RATE),
                        "-t",
                        "8",
                        "-f",
                        "webm",
                        str(path),
                    ],
                    recording.astype("<i2").tobytes(),
                )
                clips.append({**file_reference(path, output_dir), "turns": turns})
            scenarios.append(
                {
                    "id": scenario.id,
                    "clips": clips,
                    "expected_facts": scenario.expected_facts,
                    "note": scenario.note,
                }
            )

    manifest = {
        "source_kind": "synthetic",
        "source_description": (
            "Locally scripted English speech synthesized with FFmpeg Flite. Expected facts "
            "and speaker roles come from the scripts before model inference. Enrollment "
            "uses three separate user utterances that do not appear in the conversations."
        ),
        "voices": VOICES,
        "sample_rate": SAMPLE_RATE,
        "clip_duration_ms": CLIP_MS,
        "enrollment": enrollment,
        "scenarios": scenarios,
        "limitations": [
            "Synthetic speech does not establish natural-human conversation accuracy.",
            "Recordings contain no real microphone, room noise, overlap, or video capture.",
            "Turn times describe synthesized audio placement, including brief silence margins.",
            "Short confirmation intentionally exposes the current verification coverage limit.",
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = generate_fixture(args.output_dir)
    print(manifest)


if __name__ == "__main__":
    main()
