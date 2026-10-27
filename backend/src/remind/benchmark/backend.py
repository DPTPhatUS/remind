"""Isolated backend processes and read-only result snapshots for visual benchmarks."""

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import httpx

from remind.config import Settings

ROOT = Path(__file__).resolve().parents[4]


@contextmanager
def isolated_backend(settings: Settings, output: Path, *, cloud: bool):
    data = output / "data"
    data.mkdir()
    models = (settings.data_dir / "models").resolve()
    if not models.is_dir():
        raise ValueError(f"Model directory is missing: {models}")
    (data / "models").symlink_to(models, target_is_directory=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        **{
            f"REMIND_{key.upper()}": json.dumps(value) if isinstance(value, list) else str(value)
            for key, value in settings.model_dump(mode="json").items()
            if key not in {"data_dir", "openai_api_key", "origins"}
        },
        "REMIND_DATA_DIR": str(data),
        "REMIND_OPENAI_API_KEY": settings.openai_api_key if cloud else "",
        "REMIND_ORIGINS": json.dumps([base_url]),
    }
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "remind.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    with (output / "backend.log").open("w") as log:
        process = subprocess.Popen(command, cwd=ROOT / "backend", env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 120
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Backend exited before readiness; inspect backend.log")
                try:
                    with urlopen(f"{base_url}/api/health", timeout=2) as response:
                        health = json.loads(response.read())
                    break
                except (URLError, TimeoutError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "Backend did not become ready within 120 seconds"
                        ) from None
                    time.sleep(0.2)
            if not health["vision"]["available"]:
                raise RuntimeError("Face models are unavailable; inspect backend.log")
            yield base_url, data / "remind.sqlite3", health
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def enroll_voice(base_url: str, samples: list[Path]) -> dict:
    import base64

    with httpx.Client(base_url=base_url, timeout=120, headers={"Origin": base_url}) as client:
        response = client.post(
            "/api/user/voice",
            json={
                "samples": [base64.b64encode(path.read_bytes()).decode("ascii") for path in samples]
            },
        )
        return {"status": response.status_code, "response": response.json()}


def snapshot(path: Path) -> dict:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        result = {}
        for table in ("jobs", "transcripts", "job_metrics"):
            records = [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
            for row in records:
                for key in ("data", "payload"):
                    if key in row:
                        row[key] = json.loads(row[key])
            result[table] = records
        return result
