from datetime import UTC, datetime, timedelta
from typing import Protocol


class ExpiredMediaRepository(Protocol):
    async def list_expired_active(self, now_iso: str) -> list["ExpiredMediaAsset"]:
        ...

    async def mark_deleted(self, media_id: str) -> None:
        ...


class EvidenceStorage(Protocol):
    async def delete(self, path: str) -> None:
        ...


class ExpiredMediaAsset(Protocol):
    id: str
    storage_path: str


def retention_expiration(days: int, now: datetime | None = None) -> str:
    base = now or datetime.now(UTC)
    return (base + timedelta(days=days)).isoformat()


async def cleanup_expired_media(
    *,
    media_repository: ExpiredMediaRepository,
    storage: EvidenceStorage,
    now_iso: str | None = None,
) -> int:
    cutoff = now_iso or datetime.now(UTC).isoformat()
    expired_assets = await media_repository.list_expired_active(cutoff)
    for asset in expired_assets:
        await storage.delete(asset.storage_path)
        await media_repository.mark_deleted(asset.id)
    return len(expired_assets)
