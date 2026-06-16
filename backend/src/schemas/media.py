from schemas.common import TimestampedResponse


class MediaAssetResponse(TimestampedResponse):
    patient_id: str
    interaction_id: str | None
    asset_type: str
    storage_path: str
    content_type: str
    sha256: str
    size_bytes: int
    retention_expires_at: str | None
    status: str
