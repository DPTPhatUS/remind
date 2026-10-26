import cv2

from remind.vision.types import CameraImage


def usable_face(crop: CameraImage, probability: float) -> bool:
    if probability < 0.9 or min(crop.shape[:2]) < 55:
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return bool(35 < gray.mean() < 225 and cv2.Laplacian(gray, cv2.CV_64F).var() >= 35)
