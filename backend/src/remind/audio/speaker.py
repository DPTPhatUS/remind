from collections import defaultdict


def assign_speakers(segments, evidence, threshold=0.8):
    by_segment = defaultdict(list)
    for e in evidence:
        if e["score"] >= threshold and e["coverage"] >= 0.8:
            by_segment[e["segment_id"]].append(e)
    votes = defaultdict(set)
    invalid = set()
    for a in segments:
        for b in segments:
            if a["speaker"] != b["speaker"] and min(a["end_ms"], b["end_ms"]) > max(
                a["start_ms"], b["start_ms"]
            ):
                invalid.update((a["speaker"], b["speaker"]))
    for segment in segments:
        matches = by_segment[segment["id"]]
        if len(matches) != 1:
            invalid.add(segment["speaker"])
        else:
            votes[segment["speaker"]].add(matches[0]["person_id"])
    candidates = {
        speaker: next(iter(people))
        for speaker, people in votes.items()
        if len(people) == 1 and speaker not in invalid
    }
    return {
        speaker: pid
        for speaker, pid in candidates.items()
        if list(candidates.values()).count(pid) == 1
    }


def timeline_supports(timeline, stamp_ms, pid, box):
    if not timeline:
        return False
    entry = min(timeline, key=lambda t: abs(t["ms"] - stamp_ms))
    if abs(entry["ms"] - stamp_ms) > 150:
        return False
    from remind.vision.tracking import iou

    matches = [p for p in entry["people"] if p["person_id"] == pid]
    return len(matches) == 1 and iou(matches[0]["box"], box) >= 0.4


class LightSpeaker:
    """Pinned Light-ASD inference. Scores are model scores, not calibrated truth."""

    def __init__(self, registry, device="cpu"):
        import torch

        from remind.audio.light_asd.Model import ASD_Model

        torch.set_num_threads(2)
        self.torch = torch
        self.device = device
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise ValueError("Requested CUDA speaker inference is unavailable")
        state = torch.load(registry.verify("light-asd"), map_location="cpu", weights_only=True)
        self.model = ASD_Model().to(device).eval()
        self.model.load_state_dict(
            {k.removeprefix("model."): v for k, v in state.items() if k.startswith("model.")}
        )
        self.fc = torch.nn.Linear(128, 2).to(device).eval()
        self.fc.load_state_dict(
            {
                k.removeprefix("lossAV.FC."): v
                for k, v in state.items()
                if k.startswith("lossAV.FC.")
            }
        )

    def score(self, pcm, faces):
        import numpy as np
        from python_speech_features import mfcc

        torch = self.torch
        audio = mfcc(pcm, 16000, numcep=13, winlen=0.025, winstep=0.010)
        count = min(len(faces), len(audio) // 4)
        if count < 10:
            return np.empty(0)
        scores = []
        with torch.inference_mode():
            for start in range(0, count, 50):
                end = min(count, start + 50)
                a = torch.tensor(
                    audio[start * 4 : end * 4], dtype=torch.float32, device=self.device
                )[None]
                v = torch.tensor(
                    np.asarray(faces[start:end]), dtype=torch.float32, device=self.device
                )[None]
                out, _ = self.model(a, v)
                # Use normalized class score; operating threshold requires calibration.
                scores.extend(torch.softmax(self.fc(out), dim=-1)[:, 1].cpu().numpy().tolist())
        return np.array(scores)

    def evidence(self, media, segments, vision, gallery, timeline, start_ms):
        import cv2
        import numpy as np

        if not media["continuous"]:
            return []
        grid = np.arange(0, min(media["times"][-1], len(media["pcm"]) / 16000), 0.04)
        crops = {}
        valid = {}
        last = []
        for index, stamp in enumerate(grid):
            source = int(np.argmin(abs(media["times"] - stamp)))
            image = media["frames"][source]
            if index % 3 == 0:
                last = []
                for observation in vision.detect_image(image):
                    if observation["embedding"] is None:
                        continue
                    match = gallery.match(observation["embedding"])
                    if match.person_id:
                        last.append((match.person_id, observation["box"]))
            # Two matching faces for one identity are ambiguous; accept neither.
            unique = {pid: box for pid, box in last if sum(other == pid for other, _ in last) == 1}
            for pid in unique:
                if not timeline_supports(timeline, start_ms + stamp * 1000, pid, unique[pid]):
                    continue
                if pid not in crops:
                    crops[pid] = [np.zeros((112, 112), np.uint8) for _ in grid]
                    valid[pid] = np.zeros(len(grid), bool)
                x, y, w, h = unique[pid]
                ih, iw = image.shape[:2]
                cx, cy = (x + w / 2) * iw, (y + h / 2) * ih
                size = max(w * iw, h * ih) / 2
                # Reference cropScale=.4, followed by the reference center crop.
                pad = int(size * 1.8) + 1
                padded = cv2.copyMakeBorder(
                    image, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(110, 110, 110)
                )
                cx, cy = cx + pad, cy + pad
                crop = padded[
                    int(cy - size) : int(cy + size * 1.8),
                    int(cx - size * 1.4) : int(cx + size * 1.4),
                ]
                if crop.size:
                    gray = cv2.cvtColor(cv2.resize(crop, (224, 224)), cv2.COLOR_BGR2GRAY)
                    crops[pid][index] = gray[56:168, 56:168]
                    valid[pid][index] = abs(media["times"][source] - stamp) <= 0.025
        evidence = []
        for pid, faces in crops.items():
            scores = self.score(media["pcm"], faces)
            for segment in segments:
                a = max(0, int(segment["start_ms"] / 40))
                b = min(len(scores), int(segment["end_ms"] / 40))
                if b <= a:
                    continue
                coverage = float(valid[pid][a:b].mean())
                evidence.append(
                    {
                        "segment_id": segment["id"],
                        "person_id": pid,
                        "score": float(np.median(scores[a:b])),
                        "coverage": coverage,
                    }
                )
        return evidence
