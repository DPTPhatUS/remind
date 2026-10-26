import hashlib
import json
import platform
import time
from pathlib import Path

import cv2

from remind.benchmark.metrics import identification_metrics, summarize
from remind.vision.engine import OpenCVVision
from remind.vision.gallery import FaceGallery
from remind.vision.models import ModelRegistry


def replay(path, settings, mode):
    manifest = json.loads(Path(path).read_text())
    video = (Path(path).parent / manifest["video"]).resolve()
    if hashlib.sha256(video.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("Video checksum does not match manifest")
    registry = ModelRegistry(settings.data_dir / "models")
    vision = OpenCVVision(registry, settings.vision_threads)
    gallery = FaceGallery(settings.match_threshold, settings.match_margin)
    entries = []
    for person in manifest.get("gallery", []):
        for image in person["images"]:
            observed = vision.detect((Path(path).parent / image).read_bytes())
            usable = [o for o in observed if o["quality"]]
            if len(usable) != 1:
                raise ValueError("Gallery image must contain one usable face")
            entries.append((person["id"], usable[0]["embedding"]))
    gallery.replace(entries)
    capture = cv2.VideoCapture(str(video))
    rate = capture.get(cv2.CAP_PROP_FPS)
    if rate <= 0:
        raise ValueError("Video must have a valid frame rate")
    events = []
    predictions = []
    truth = []
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
        observed = vision.detect_image(frame)
        events.append(
            {
                "sequence": sequence,
                "capture_ms": (time.perf_counter() - started) * 1000,
                "processing_ms": (time.perf_counter() - before) * 1000,
                "faces": len(observed),
                "usable_faces": sum(bool(o["quality"]) for o in observed),
            }
        )
        label = manifest.get("single_face_labels", {}).get(str(sequence), "unlabeled")
        if label != "unlabeled":
            prediction = (
                gallery.match(observed[0]["embedding"]).person_id
                if len(observed) == 1 and observed[0]["quality"]
                else None
            )
            truth.append(label)
            predictions.append(prediction)
        sequence += 1
    capture.release()
    identification = identification_metrics(truth, predictions)
    identification["zero_error_upper_95"] = None
    identification["note"] = (
        "Frame-level diagnostic; neighboring frames are not independent trials."
    )
    return {
        **summarize(events),
        "mode": mode,
        "model_backend": "real OpenCV CPU",
        "hardware": platform.platform(),
        "model_hashes": {
            name: (
                {item["file"]: item["sha256"] for item in model["files"]}
                if "files" in model else model["sha256"]
            )
            for name, model in registry.models.items()
        },
        "identification": identification,
        "dataset_sha256": manifest["sha256"],
        "vision_threads": settings.vision_threads,
        "opencv_version": cv2.__version__,
        "gallery_people": len(manifest.get("gallery", [])),
        "events": events,
        "threshold": settings.match_threshold,
        "margin": settings.match_margin,
        "expected_faces": manifest.get("expected_faces"),
        "workload_matching_frames": sum(
            e["usable_faces"] == manifest["expected_faces"] for e in events
        )
        if "expected_faces" in manifest
        else None,
    }
