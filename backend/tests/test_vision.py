import hashlib
import io

import numpy as np
import pytest

from remind.vision.candidate import Candidate
from remind.vision.gallery import FaceGallery
from remind.vision.models import MANIFEST, ModelRegistry
from remind.vision.quality import usable_face


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


def test_single_candidate_uses_current_appearance_and_expires():
    candidate = Candidate([0.1, 0.1, 0.2, 0.3], 0, 0)
    candidate.observe(obs(0.1, vector()), 0)
    assert candidate.continues(obs(0.2, vector()), 100)
    assert not candidate.continues(obs(0.1, vector(1)), 100)
    assert not candidate.continues(obs(0.1, vector()), 501)
    candidate.person_id = "known"
    candidate.observe(obs(0.1, None, False), 100)
    assert candidate.person_id == "known"
    assert len(candidate.samples) == 1


def test_candidate_samples_are_bounded_current_and_consistent():
    candidate = Candidate([0.1, 0.1, 0.2, 0.3], 0, 0)
    for stamp in range(0, 9000, 100):
        candidate.observe(obs(0.1, vector()), stamp)
    assert len(candidate.samples) == 16
    assert candidate.samples[0][0] >= 3900
    assert len(candidate.enrollment_samples(0.55)) == 8
    candidate.observe(obs(0.1, vector(1)), 9200)
    assert candidate.enrollment_samples(0.55) == []


def test_corrupt_models_are_rejected(tmp_path):
    registry = ModelRegistry(tmp_path)
    with pytest.raises(FileNotFoundError):
        registry.verify("yunet")
    (tmp_path / "face_detection_yunet_2023mar.onnx").write_bytes(b"not a model")
    with pytest.raises(ValueError):
        registry.verify("yunet")


@pytest.mark.parametrize("model_id,license_name", [("yunet", "YuNet"), ("sface", "SFace")])
def test_face_model_bundle_has_pinned_downloads_and_license(tmp_path, model_id, license_name):
    model = ModelRegistry(tmp_path).models[model_id]
    assert model["file"].endswith(".onnx")
    assert model["size"] > 0
    assert len(model["sha256"]) == 64
    assert len(bytes.fromhex(model["sha256"])) == 32
    assert model["url"].startswith("https://media.githubusercontent.com/media/opencv/opencv_zoo/")
    assert (MANIFEST.parent / "licenses" / f"{license_name}.txt").read_text().strip()


def test_dark_and_small_crops_are_not_enrollment_evidence():
    assert not usable_face(np.zeros((100, 100, 3), dtype=np.uint8), 0.99)
    assert not usable_face(np.ones((10, 10, 3), dtype=np.uint8) * 120, 0.99)


def test_failed_model_download_does_not_leave_partial_files(tmp_path, monkeypatch):
    registry = ModelRegistry(tmp_path)
    registry.models = {
        "example": {
            "file": "example.onnx",
            "size": 4,
            "sha256": hashlib.sha256(b"good").hexdigest(),
            "url": "https://example.com/model",
        }
    }
    monkeypatch.setattr("remind.vision.models.urlopen", lambda *args, **kwargs: io.BytesIO(b"bad"))
    with pytest.raises(ValueError, match="Invalid downloaded example"):
        registry.install()
    assert not (tmp_path / "example.onnx").exists()
    assert not (tmp_path / "example.onnx.part").exists()
