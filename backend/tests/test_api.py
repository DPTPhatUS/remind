from fastapi.testclient import TestClient

from remind.app import create_app
from remind.config import Settings


def test_readiness_people_and_single_capture_owner(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        health = client.get("/api/health").json()
        assert health["vision"]["available"] is False
        assert client.get("/api/people").json() == []
        assert (
            client.post("/api/session", headers={"Origin": "https://evil.example"}).status_code
            == 403
        )
        # Missing models must not pretend a live session is functioning.
        assert client.post("/api/session").status_code == 503


def test_retained_final_clip_can_retry_after_stop(tmp_path, monkeypatch):
    import json
    import struct

    import numpy as np

    class Vision:
        def __init__(self, *args):
            pass

        def detect(self, data):
            return [
                {
                    "box": [0.3, 0.2, 0.3, 0.4],
                    "embedding": np.eye(128, dtype=np.float32)[0],
                    "quality": True,
                    "thumbnail": b"x",
                }
            ]

    monkeypatch.setattr("remind.app.OpenCVVision", Vision)
    with TestClient(create_app(Settings(data_dir=tmp_path, openai_api_key="test"))) as client:
        generation = client.post("/api/session").json()["generation"]
        with client.websocket_connect(
            f"/api/live/{generation}/vision", headers={"origin": "http://127.0.0.1:5173"}
        ) as socket:
            for sequence in range(22):
                header = json.dumps(
                    {
                        "version": 1,
                        "generation": generation,
                        "sequence": sequence,
                        "capture_ms": sequence * 100,
                    }
                ).encode()
                socket.send_bytes(struct.pack(">I", len(header)) + header + b"jpeg")
                socket.receive_json()
        client.post(f"/api/session/{generation}/stop")
        response = client.post(
            f"/api/live/{generation}/clips",
            params={"metadata": json.dumps({"window_id": "last", "start_ms": 0, "end_ms": 2100})},
            content=b"injected clip",
        )
        assert response.status_code == 200
        assert response.json()["status"] == "queued"
