import cv2


def usable_face(crop, probability):
    if probability < 0.9 or min(crop.shape[:2]) < 55:
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return 35 < gray.mean() < 225 and cv2.Laplacian(gray, cv2.CV_64F).var() >= 35
