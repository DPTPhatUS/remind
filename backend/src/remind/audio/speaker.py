"""Local user-voice verification for the single-visitor conversation model.

Cosine operating points are deliberately separated by an abstention band. They
are engineering defaults, not accuracy estimates or calibrated probabilities.
Anonymous diarization labels are used only within one call to ``classify``.
"""

from collections import defaultdict
from importlib.util import find_spec
from itertools import combinations

import numpy as np

MODEL = "speechbrain/spkrec-ecapa-voxceleb@0f99f2d0ebe89ac095bcc5903c4dd8f72b367286"
SAMPLE_RATE = 16000
EMBEDDING_SIZE = 192


class UserVoiceVerifier:
    def __init__(self, settings, registry):
        self.settings = settings
        self.registry = registry
        self._encoder = None
        self._vad = None

    def readiness(self):
        try:
            for name in ("torch", "torchaudio", "speechbrain"):
                if find_spec(name) is None:
                    raise ImportError("Install voice dependencies with uv sync --extra speaker")
            self.registry.verify("ecapa")
            return {"available": True, "error": None}
        except (FileNotFoundError, ValueError, ImportError) as exc:
            return {"available": False, "error": str(exc)}

    def _load(self):
        if self._encoder is None:
            # Assets must already be installed and checksum verified. Local source
            # and pretrained_path prevent any runtime download from the hub.
            directory = self.registry.verify("ecapa").resolve()
            import torch
            from speechbrain.inference.classifiers import EncoderClassifier

            torch.set_num_threads(self.settings.voice_threads)
            self._encoder = EncoderClassifier.from_hparams(
                source=str(directory),
                savedir=str(directory),
                overrides={"pretrained_path": str(directory)},
                run_opts={"device": "cpu"},
            )
        return self._encoder

    @staticmethod
    def _validate_pcm(pcm):
        if not isinstance(pcm, np.ndarray) or pcm.ndim != 1 or pcm.dtype != np.int16:
            raise ValueError("Expected finite mono 16 kHz PCM16 audio")
        if not len(pcm):
            raise ValueError("Audio is empty")
        # int16 cannot contain NaNs; widening avoids abs(-32768) overflow.
        if np.mean(np.abs(pcm.astype(np.int32)) >= 32700) > 0.01:
            raise ValueError("Audio is clipped; move the microphone farther away")

    def _speech(self, pcm):
        """Return trimmed audio and the seconds of usable WebRTC-VAD speech."""
        if self._vad is None:
            import webrtcvad

            self._vad = webrtcvad.Vad(2)
        count = len(pcm) // 320
        voiced = []
        for i in range(count):
            frame = pcm[i * 320 : (i + 1) * 320]
            rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
            if rms >= 80 and self._vad.is_speech(frame.tobytes(), SAMPLE_RATE):
                voiced.append(i)
        if not voiced:
            return pcm[:0], 0.0
        start = max(0, voiced[0] - 5) * 320
        end = min(len(pcm), (voiced[-1] + 6) * 320)
        return pcm[start:end], len(voiced) * 0.02

    def _embedding(self, pcm):
        import torch

        encoder = self._load()
        waveform = torch.from_numpy(pcm.astype(np.float32) / 32768.0).unsqueeze(0)
        with torch.inference_mode():
            embedding = encoder.encode_batch(waveform).detach().cpu().numpy().reshape(-1)
        if embedding.size != EMBEDDING_SIZE or not np.isfinite(embedding).all():
            raise ValueError("Voice model produced an invalid embedding")
        norm = float(np.linalg.norm(embedding))
        if norm < 1e-8:
            raise ValueError("Voice model produced an empty embedding")
        return embedding / norm

    def enroll(self, samples):
        if not 3 <= len(samples) <= 6:
            raise ValueError("Record between three and six separate voice samples")
        prepared = []
        for index, pcm in enumerate(samples, 1):
            self._validate_pcm(pcm)
            if not 3 * SAMPLE_RATE <= len(pcm) <= 20 * SAMPLE_RATE:
                raise ValueError(f"Sample {index} must last between 3 and 20 seconds")
            speech, seconds = self._speech(pcm)
            if seconds < self.settings.voice_min_speech_seconds:
                raise ValueError(f"Sample {index} has too little clear speech; record it again")
            prepared.append(speech)
        embeddings = [self._embedding(pcm) for pcm in prepared]
        if any(
            float(np.dot(left, right)) < self.settings.voice_enrollment_threshold
            for left, right in combinations(embeddings, 2)
        ):
            raise ValueError("Voice samples are inconsistent; record only the user's voice")
        return {"model": MODEL, "embeddings": [item.tolist() for item in embeddings]}

    @staticmethod
    def _references(profile):
        if not profile or profile.get("model") != MODEL:
            return None
        try:
            references = np.asarray(profile["embeddings"], dtype=np.float32)
        except (KeyError, ValueError, TypeError):
            return None
        if (
            references.ndim != 2
            or not 3 <= len(references) <= 6
            or references.shape[1] != EMBEDDING_SIZE
            or not np.isfinite(references).all()
        ):
            return None
        norms = np.linalg.norm(references, axis=1)
        if np.any(norms < 1e-8):
            return None
        return references / norms[:, None]

    def classify(self, pcm, segments, profile):
        result = [{**segment, "role": "uncertain"} for segment in segments]
        references = self._references(profile)
        if references is None:
            return result
        try:
            self._validate_pcm(pcm)
        except ValueError:
            return result

        # Never clamp out-of-range intervals into apparently valid evidence.
        intervals = {}
        for index, segment in enumerate(result):
            try:
                start, end = float(segment["start_ms"]), float(segment["end_ms"])
                speaker = segment.get("speaker")
                if (
                    not np.isfinite([start, end]).all()
                    or not isinstance(speaker, str)
                    or speaker.strip().lower() in {"", "unknown", "none", "null"}
                ):
                    continue
                if not 0 <= start < end <= len(pcm) / 16 + 1:
                    continue
                intervals[index] = (round(start * 16), min(len(pcm), round(end * 16)))
            except (KeyError, TypeError, ValueError):
                continue
        overlapping = set()
        for (left, (a, b)), (right, (c, d)) in combinations(intervals.items(), 2):
            if min(b, d) > max(a, c):
                overlapping.update((left, right))

        groups = defaultdict(list)
        for index, (start, end) in intervals.items():
            if index in overlapping or end - start < SAMPLE_RATE // 4:
                continue
            chunk, seconds = self._speech(pcm[start:end])
            if seconds >= 0.12:
                groups[result[index]["speaker"]].append((index, chunk, seconds))
        for chunks in groups.values():
            if sum(seconds for _, _, seconds in chunks) < self.settings.voice_min_speech_seconds:
                continue
            # Bound CPU work independently of malformed or very long transcripts.
            voice = np.concatenate([chunk for _, chunk, _ in chunks])[: SAMPLE_RATE * 20]
            embedding = self._embedding(voice)
            score = float(np.median(references @ embedding))
            role = "uncertain"
            if score >= self.settings.voice_user_threshold:
                role = "user"
            elif score <= self.settings.voice_visitor_threshold:
                role = "visitor"
            for index, _, _ in chunks:
                result[index].update(role=role, voice_score=score)
        return result
