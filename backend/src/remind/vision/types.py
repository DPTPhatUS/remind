from typing import TypedDict

import numpy as np
from numpy.typing import NDArray

type FaceEmbedding = NDArray[np.float32]
type CameraImage = NDArray[np.uint8]


class FaceObservation(TypedDict):
    box: list[float]
    embedding: FaceEmbedding | None
    quality: bool
    thumbnail: bytes | None
