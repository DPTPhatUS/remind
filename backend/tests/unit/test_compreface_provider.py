import httpx
import pytest

from providers.compreface.client import CompreFaceClient


@pytest.mark.asyncio
async def test_recognize_maps_compreface_result_to_internal_shape() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/recognition/recognize"
        assert request.headers["x-api-key"] == "secret"
        return httpx.Response(
            200,
            json={
                "result": [
                    {
                        "box": {
                            "probability": 0.99,
                            "x_min": 10,
                            "y_min": 20,
                            "x_max": 30,
                            "y_max": 40,
                        },
                        "subjects": [
                            {"subject": "person-uuid", "similarity": 0.93},
                        ],
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://compreface") as http:
        client = CompreFaceClient(base_url="http://compreface", api_key="secret", http=http)
        results = await client.recognize(b"image-bytes", filename="frame.jpg")

    assert len(results) == 1
    assert results[0].subject == "person-uuid"
    assert results[0].similarity == 0.93
    assert results[0].face_probability == 0.99
    assert results[0].box.x_min == 10


@pytest.mark.asyncio
async def test_recognize_returns_empty_when_compreface_signals_no_face() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"message": "No face is found in the given image", "code": 28},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://compreface") as http:
        client = CompreFaceClient(base_url="http://compreface", api_key="secret", http=http)
        results = await client.recognize(b"image-bytes", filename="frame.jpg")

    assert results == []


@pytest.mark.asyncio
async def test_recognize_raises_on_unrelated_400() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "Bad image format", "code": 7})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://compreface") as http:
        client = CompreFaceClient(base_url="http://compreface", api_key="secret", http=http)
        with pytest.raises(httpx.HTTPStatusError):
            await client.recognize(b"image-bytes", filename="frame.jpg")


@pytest.mark.asyncio
async def test_add_face_example_returns_image_id_and_subject() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/recognition/faces"
        assert request.url.params["subject"] == "opaque-subject-id"
        return httpx.Response(
            200,
            json={"image_id": "image-uuid", "subject": "opaque-subject-id"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://compreface") as http:
        client = CompreFaceClient(base_url="http://compreface", api_key="secret", http=http)
        result = await client.add_face_example(
            subject="opaque-subject-id",
            image_bytes=b"image-bytes",
            filename="face.jpg",
        )

    assert result.image_id == "image-uuid"
    assert result.subject == "opaque-subject-id"
