from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class BoundingBox:
    probability: float
    x_min: int
    y_min: int
    x_max: int
    y_max: int


@dataclass(frozen=True)
class FaceRecognitionResult:
    subject: str | None
    similarity: float | None
    face_probability: float
    box: BoundingBox


@dataclass(frozen=True)
class FaceEnrollmentResult:
    image_id: str
    subject: str


class CompreFaceClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._http = http

    # CompreFace signals "no detectable face" with HTTP 400 + code 28 — that
    # is its normal "nothing to recognize" response, not a transport error.
    _NO_FACE_FOUND_CODE = 28

    async def recognize(
        self,
        image_bytes: bytes,
        *,
        filename: str = "frame.jpg",
    ) -> list[FaceRecognitionResult]:
        try:
            response = await self._request(
                "POST",
                "/api/v1/recognition/recognize",
                files={"file": (filename, image_bytes, "image/jpeg")},
            )
        except httpx.HTTPStatusError as exc:
            body: dict = {}
            try:
                body = exc.response.json()
            except ValueError:
                pass
            if exc.response.status_code == 400 and body.get("code") == self._NO_FACE_FOUND_CODE:
                return []
            raise

        payload = response.json()
        return [self._map_recognition(item) for item in payload.get("result", [])]

    async def add_face_example(
        self,
        *,
        subject: str,
        image_bytes: bytes,
        filename: str = "face.jpg",
        det_prob_threshold: float | None = None,
    ) -> FaceEnrollmentResult:
        params: dict[str, str | float] = {"subject": subject}
        if det_prob_threshold is not None:
            params["det_prob_threshold"] = det_prob_threshold
        response = await self._request(
            "POST",
            "/api/v1/recognition/faces",
            params=params,
            files={"file": (filename, image_bytes, "image/jpeg")},
        )
        data = response.json()
        return FaceEnrollmentResult(image_id=data["image_id"], subject=data["subject"])

    async def delete_subject(self, subject: str) -> None:
        await self._request("DELETE", "/api/v1/recognition/faces", params={"subject": subject})

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        incoming_headers = kwargs.pop("headers", None) or {}
        headers: dict[str, str] = {**incoming_headers, "x-api-key": self.api_key}
        if self._http is not None:
            response = await self._http.request(method, path, headers=headers, **kwargs)
        else:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as http:
                response = await http.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    def _map_recognition(self, item: dict) -> FaceRecognitionResult:
        box_payload = item["box"]
        box = BoundingBox(
            probability=float(box_payload["probability"]),
            x_min=int(box_payload["x_min"]),
            y_min=int(box_payload["y_min"]),
            x_max=int(box_payload["x_max"]),
            y_max=int(box_payload["y_max"]),
        )
        subject_payload = (item.get("subjects") or [{}])[0]
        return FaceRecognitionResult(
            subject=subject_payload.get("subject"),
            similarity=(
                float(subject_payload["similarity"])
                if subject_payload.get("similarity") is not None
                else None
            ),
            face_probability=box.probability,
            box=box,
        )
