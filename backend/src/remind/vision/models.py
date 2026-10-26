import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

MANIFEST = Path(__file__).resolve().parents[1] / "assets" / "manifest.json"


class ModelRegistry:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.models = json.loads(MANIFEST.read_text())

    def _verify_file(self, model_id, model):
        path = self.directory / model["file"]
        if not path.is_file():
            raise FileNotFoundError(f"Missing {model_id}: run python -m remind.cli models install")
        if path.stat().st_size != model["size"] or self._sha256(path) != model["sha256"]:
            raise ValueError(f"Corrupt {model_id} model; reinstall models")
        return path

    @staticmethod
    def _sha256(path):
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
        return digest.hexdigest()

    def verify(self, model_id):
        model = self.models[model_id]
        if "files" in model:
            for item in model["files"]:
                self._verify_file(model_id, item)
            return self.directory / model["directory"]
        return self._verify_file(model_id, model)

    def install(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        for name, model in self.models.items():
            for item in model.get("files", [model]):
                self._install_file(name, item)

    def _install_file(self, name, model):
        try:
            self._verify_file(name, model)
            return
        except (FileNotFoundError, ValueError):
            pass
        partial = self.directory / (model["file"] + ".part")
        partial.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(model["url"], timeout=120) as response, partial.open("wb") as target:
            while block := response.read(1024 * 1024):
                target.write(block)
        if partial.stat().st_size != model["size"] or self._sha256(partial) != model["sha256"]:
            partial.unlink(missing_ok=True)
            raise ValueError(f"Invalid downloaded {name}")
        partial.replace(self.directory / model["file"])
