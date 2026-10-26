from typing import cast

import cv2
import numpy as np

from remind.vision.gallery import normalize_embedding
from remind.vision.models import ModelRegistry
from remind.vision.quality import usable_face
from remind.vision.types import CameraImage, FaceObservation


class OpenCVVision:
    def __init__(self, registry: ModelRegistry, threads: int = 4):
        cv2.setNumThreads(threads)
        self.detector = cv2.FaceDetectorYN.create(
            str(registry.verify("yunet")), "", (640, 360), 0.9
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(registry.verify("sface")), "")
        self.detect_image(np.zeros((360, 640, 3), dtype=np.uint8))

    def detect(self, data: bytes) -> list[FaceObservation]:
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("Frame too large")
        image = cast(
            CameraImage | None, cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        )
        if image is None or image.shape[0] > 2160 or image.shape[1] > 3840:
            raise ValueError("Invalid camera frame")
        return self.detect_image(image)

    def detect_image(self, image: CameraImage) -> list[FaceObservation]:
        height, width = image.shape[:2]
        scale = min(1.0, 640 / width)
        small = cv2.resize(image, (round(width * scale), round(height * scale)))
        self.detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self.detector.detect(small)
        observations: list[FaceObservation] = []
        if faces is None:
            return observations
        for face in faces:
            face = face.astype(np.float32, copy=True)
            face[:14] /= scale
            x, y, w, h = face[:4]
            left, top = max(0, int(x)), max(0, int(y))
            crop = image[top : min(height, int(y + h)), left : min(width, int(x + w))]
            if crop.size == 0:
                continue
            quality = usable_face(crop, float(face[14]))
            feature = None
            thumbnail = None
            if quality:
                aligned = self.recognizer.alignCrop(image, face)
                feature = normalize_embedding(self.recognizer.feature(aligned))
                _, encoded = cv2.imencode(".jpg", cv2.resize(crop, (160, 160)))
                thumbnail = encoded.tobytes()
            observations.append(
                {
                    "box": [
                        float(x / width),
                        float(y / height),
                        float(w / width),
                        float(h / height),
                    ],
                    "embedding": feature,
                    "quality": quality,
                    "thumbnail": thumbnail,
                }
            )
        return observations
