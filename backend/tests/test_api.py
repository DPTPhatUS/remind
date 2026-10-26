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

    monkeypatch.setattr("remind.runtime.OpenCVVision", Vision)
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
        empty = client.post(
            f"/api/live/{generation}/clips",
            params={"metadata": json.dumps({"window_id": "last", "start_ms": 0, "end_ms": 2100})},
            content=b"",
        )
        assert empty.status_code == 422
        assert empty.json()["detail"] == "Clip is empty"
        assert list((tmp_path / "spool").iterdir()) == []
        response = client.post(
            f"/api/live/{generation}/clips",
            params={"metadata": json.dumps({"window_id": "last", "start_ms": 0, "end_ms": 2100})},
            content=b"injected clip",
        )
        assert response.status_code == 200
        assert response.json()["status"] == "queued"


def test_only_one_live_session_and_stale_generation_cannot_upload(tmp_path, monkeypatch):
    class Vision:
        def __init__(self, *args):
            pass

    monkeypatch.setattr("remind.runtime.OpenCVVision", Vision)
    with TestClient(create_app(Settings(data_dir=tmp_path, openai_api_key="test"))) as client:
        first = client.post("/api/session").json()["generation"]
        assert client.post("/api/session").status_code == 409
        assert client.post(f"/api/session/{first}/stop").status_code == 200
        second = client.post("/api/session").json()["generation"]
        assert first != second
        assert client.post(f"/api/live/{first}/clips", content=b"stale").status_code == 409


def test_helper_voice_enrollment_replacement_and_removal(tmp_path, monkeypatch):
    import base64

    import numpy as np

    class Verifier:
        def readiness(self):
            return {"available": True, "error": None}

        def enroll(self, samples):
            assert len(samples) == 3
            return {"model": "fixture-voice", "embeddings": [[1.0, 0.0]] * 3}

    monkeypatch.setattr(
        "remind.app.decode_audio",
        lambda *args, **kwargs: {"pcm": np.ones(48000, dtype=np.int16), "continuous": True},
    )
    with TestClient(
        create_app(Settings(data_dir=tmp_path, openai_api_key=""), voice_verifier=Verifier())
    ) as client:
        initial = client.get("/api/user/voice").json()
        assert initial["ready"] is False
        assert client.get("/api/health").json()["memory"]["profile_learning_available"] is False
        assert client.post("/api/user/voice", json={"samples": ["bad"]}).status_code == 422
        encoded = base64.b64encode(b"fixture media").decode()
        response = client.post("/api/user/voice", json={"samples": [encoded] * 3})
        assert response.status_code == 200
        enrolled = response.json()
        assert enrolled["ready"] is True
        assert enrolled["sample_count"] == 3
        assert "embeddings" not in enrolled
        replacement = client.post("/api/user/voice", json={"samples": [encoded] * 3}).json()
        assert replacement["version"] > enrolled["version"]
        removed = client.delete("/api/user/voice").json()
        assert removed["ready"] is False
        assert removed["version"] > replacement["version"]


def test_failed_voice_replacement_preserves_existing_reference(tmp_path, monkeypatch):
    import base64

    import numpy as np

    class Verifier:
        fail = False

        def readiness(self):
            return {"available": True, "error": None}

        def enroll(self, samples):
            if self.fail:
                raise ValueError("Samples contain different speakers")
            return {"model": "fixture", "embeddings": [[1.0, 0.0]] * 3}

    verifier = Verifier()
    monkeypatch.setattr(
        "remind.app.decode_audio",
        lambda *args, **kwargs: {"pcm": np.ones(48000, dtype=np.int16), "continuous": True},
    )
    with TestClient(
        create_app(Settings(data_dir=tmp_path, openai_api_key=""), voice_verifier=verifier)
    ) as client:
        data = {"samples": [base64.b64encode(b"fixture").decode()] * 3}
        original = client.post("/api/user/voice", json=data).json()
        verifier.fail = True
        response = client.post("/api/user/voice", json=data)
        assert response.status_code == 422
        current = client.get("/api/user/voice").json()
        assert current["ready"] is True
        assert current["version"] == original["version"]
