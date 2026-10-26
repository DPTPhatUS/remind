import hashlib
import json
import math
import platform
import time
from pathlib import Path
from typing import Any, Literal, cast

import cv2

from remind.benchmark.metrics import identification_metrics, summarize
from remind.config import Settings
from remind.vision.engine import OpenCVVision
from remind.vision.gallery import FaceGallery
from remind.vision.models import ModelRegistry
from remind.vision.types import CameraImage


def replay(
    path: str | Path, settings: Settings, mode: Literal["realtime", "throughput"]
) -> dict[str, Any]:
    if mode not in ("realtime", "throughput"):
        raise ValueError("Replay mode must be realtime or throughput")
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text())
    video = (manifest_path.parent / manifest["video"]).resolve()
    with video.open("rb") as source:
        checksum = hashlib.file_digest(source, "sha256").hexdigest()
    if checksum != manifest["sha256"]:
        raise ValueError("Video checksum does not match manifest")

    registry = ModelRegistry(settings.data_dir / "models")
    vision = OpenCVVision(registry, settings.vision_threads)
    gallery = FaceGallery(settings.match_threshold, settings.match_margin)
    entries = []
    for person in manifest.get("gallery", []):
        for image in person["images"]:
            observed = vision.detect((manifest_path.parent / image).read_bytes())
            usable = [observation for observation in observed if observation["quality"]]
            if len(usable) != 1:
                raise ValueError("Gallery image must contain one usable face")
            embedding = usable[0]["embedding"]
            if embedding is None:
                raise ValueError("Gallery image must contain a usable face embedding")
            entries.append((person["id"], embedding))
    gallery.replace(entries)

    events = []
    predictions = []
    truth = []
    capture = cv2.VideoCapture(str(video))
    try:
        rate = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError("Video must have a valid frame rate")
        started = time.perf_counter()
        sequence = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if mode == "realtime":
                due = sequence / rate
                delay = due - (time.perf_counter() - started)
                if delay > 0:
                    time.sleep(delay)
                elif delay < -0.1:
                    sequence += 1
                    continue
            before = time.perf_counter()
            observed = vision.detect_image(cast(CameraImage, frame))
            events.append(
                {
                    "sequence": sequence,
                    "capture_ms": (time.perf_counter() - started) * 1000,
                    "processing_ms": (time.perf_counter() - before) * 1000,
                    "faces": len(observed),
                    "usable_faces": sum(bool(observation["quality"]) for observation in observed),
                }
            )
            labels = manifest.get("single_face_labels", {})
            if str(sequence) in labels:
                prediction = None
                if len(observed) == 1 and observed[0]["quality"]:
                    embedding = observed[0]["embedding"]
                    if embedding is not None:
                        prediction = gallery.match(embedding).person_id
                truth.append(labels[str(sequence)])
                predictions.append(prediction)
            sequence += 1
    finally:
        capture.release()

    identification = identification_metrics(truth, predictions)
    identification["zero_error_upper_95"] = None
    identification["note"] = (
        "Frame-level diagnostic; neighboring frames are not independent trials."
    )
    model_hashes = {}
    for name, model in registry.models.items():
        model_hashes[name] = (
            {item["file"]: item["sha256"] for item in model["files"]}
            if "files" in model
            else model["sha256"]
        )
    expected_faces = manifest.get("expected_faces")
    return {
        **summarize(events),
        "mode": mode,
        "model_backend": "real OpenCV CPU",
        "hardware": platform.platform(),
        "model_hashes": model_hashes,
        "identification": identification,
        "dataset_sha256": manifest["sha256"],
        "vision_threads": settings.vision_threads,
        "opencv_version": cv2.__version__,
        "gallery_people": len(manifest.get("gallery", [])),
        "events": events,
        "threshold": settings.match_threshold,
        "margin": settings.match_margin,
        "expected_faces": expected_faces,
        "workload_matching_frames": (
            sum(event["usable_faces"] == expected_faces for event in events)
            if expected_faces is not None
            else None
        ),
    }
