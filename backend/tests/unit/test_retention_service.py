import pytest

from services.retention_service import cleanup_expired_media


class FakeMediaRepository:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def list_expired_active(self, now_iso: str):
        assert now_iso == "2026-06-16T00:00:00+00:00"
        return [
            type("MediaAsset", (), {"id": "media-1", "storage_path": "/tmp/evidence-1.jpg"})(),
            type("MediaAsset", (), {"id": "media-2", "storage_path": "/tmp/evidence-2.jpg"})(),
        ]

    async def mark_deleted(self, media_id: str):
        self.deleted.append(media_id)


class FakeStorage:
    def __init__(self) -> None:
        self.deleted_paths: list[str] = []

    async def delete(self, path: str) -> None:
        self.deleted_paths.append(path)


@pytest.mark.asyncio
async def test_cleanup_expired_media_deletes_files_and_marks_assets_deleted() -> None:
    repository = FakeMediaRepository()
    storage = FakeStorage()

    count = await cleanup_expired_media(
        media_repository=repository,
        storage=storage,
        now_iso="2026-06-16T00:00:00+00:00",
    )

    assert count == 2
    assert storage.deleted_paths == ["/tmp/evidence-1.jpg", "/tmp/evidence-2.jpg"]
    assert repository.deleted == ["media-1", "media-2"]
