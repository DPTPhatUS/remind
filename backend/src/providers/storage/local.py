import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import aiofiles


@dataclass(frozen=True)
class StoredAsset:
    storage_path: str
    sha256: str
    size_bytes: int


class LocalEvidenceStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    async def save(self, *, patient_id: str, data: bytes, extension: str) -> StoredAsset:
        digest = hashlib.sha256(data).hexdigest()
        directory = self.root / patient_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{uuid4()}.{extension.lstrip('.')}"
        async with aiofiles.open(path, "wb") as file:
            await file.write(data)
        return StoredAsset(storage_path=str(path), sha256=digest, size_bytes=len(data))
