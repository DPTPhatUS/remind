from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MediaAsset


class MediaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, values: dict) -> MediaAsset:
        asset = MediaAsset(**values)
        self.session.add(asset)
        await self.session.commit()
        await self.session.refresh(asset)
        return asset

    async def list_expired_active(self, now_iso: str) -> list[MediaAsset]:
        result = await self.session.execute(
            select(MediaAsset)
            .where(MediaAsset.status == "active")
            .where(MediaAsset.retention_expires_at.is_not(None))
            .where(MediaAsset.retention_expires_at <= now_iso)
        )
        return list(result.scalars())

    async def mark_deleted(self, media_id: str) -> None:
        asset = await self.session.get(MediaAsset, media_id)
        if asset is None:
            return
        asset.status = "deleted"
        await self.session.commit()
