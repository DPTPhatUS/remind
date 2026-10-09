import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

MANIFEST = Path(__file__).resolve().parents[1] / "assets" / "manifest.json"


class ModelRegistry:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.models = json.loads(MANIFEST.read_text())

    def verify(self, model_id):
        model = self.models[model_id]
        path = self.directory / model["file"]
        if not path.is_file():
            raise FileNotFoundError(f"Missing {model_id}: run python -m remind.cli models install")
        if (
            path.stat().st_size != model["size"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != model["sha256"]
        ):
            raise ValueError(f"Corrupt {model_id} model; reinstall models")
        return path

    def install(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        for name, model in self.models.items():
            try:
                self.verify(name)
                continue
            except (FileNotFoundError, ValueError):
                pass
            partial = self.directory / (model["file"] + ".part")
            with urlopen(model["url"], timeout=120) as response, partial.open("wb") as target:
                while block := response.read(1024 * 1024):
                    target.write(block)
            if (
                partial.stat().st_size != model["size"]
                or hashlib.sha256(partial.read_bytes()).hexdigest() != model["sha256"]
            ):
                partial.unlink(missing_ok=True)
                raise ValueError(f"Invalid downloaded {name}")
            partial.replace(self.directory / model["file"])
