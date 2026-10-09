import numpy as np
import pytest

from remind.vision.gallery import FaceGallery
from remind.vision.models import ModelRegistry
from remind.vision.quality import usable_face
from remind.vision.tracking import Tracker


def vector(index=0):
    v = np.zeros(128, dtype=np.float32)
    v[index] = 1
    return v


def obs(x, feature, quality=True):
    return {"box": [x, 0.1, 0.2, 0.3], "embedding": feature, "quality": quality, "thumbnail": b"x"}


def test_gallery_margin_is_between_people_not_templates():
    gallery = FaceGallery(0.55, 0.08)
    gallery.replace([("a", vector()), ("a", vector())])
    assert gallery.match(vector()).person_id == "a"
    gallery.replace([("a", vector()), ("b", vector())])
    assert gallery.match(vector()).person_id is None
    assert gallery.match(vector()).ambiguous
    with pytest.raises(ValueError):
        gallery.match(np.full(128, np.nan))


def test_crossing_uses_appearance_and_bad_observations_cannot_enroll():
    tracker = Tracker()
    initial = tracker.update([obs(0.1, vector()), obs(0.6, vector(1))], 0)
    later = tracker.update([obs(0.6, vector()), obs(0.1, vector(1))], 100)
    assert later[0].id == initial[0].id
    assert later[1].id == initial[1].id
    for time in range(200, 2500, 100):
        tracks = tracker.update([obs(0.6, vector(), False)], time)
    assert tracks[0].usable_count < 5


def test_corrupt_models_are_rejected(tmp_path):
    registry = ModelRegistry(tmp_path)
    with pytest.raises(FileNotFoundError):
        registry.verify("yunet")
    (tmp_path / "face_detection_yunet_2023mar.onnx").write_bytes(b"not a model")
    with pytest.raises(ValueError):
        registry.verify("yunet")


def test_dark_and_small_crops_are_not_enrollment_evidence():
    assert not usable_face(np.zeros((100, 100, 3), dtype=np.uint8), 0.99)
    assert not usable_face(np.ones((10, 10, 3), dtype=np.uint8) * 120, 0.99)
