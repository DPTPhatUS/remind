from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from api.deps import PatientDep, SessionDep, SettingsDep
from db.repositories.media import MediaRepository
from providers.storage import LocalEvidenceStorage
from schemas.media import MediaAssetResponse
from services.retention_service import cleanup_expired_media, retention_expiration

router = APIRouter()


@router.post("/evidence", response_model=MediaAssetResponse)
async def upload_evidence(
    patient: PatientDep,
    session: SessionDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    asset_type: Annotated[str, Form()],
    interaction_id: Annotated[str | None, Form()] = None,
) -> MediaAssetResponse:
    data = await file.read()
    extension = (file.filename or "asset.bin").rsplit(".", 1)[-1]
    stored = await LocalEvidenceStorage(settings.evidence_storage_dir).save(
        patient_id=patient.id,
        data=data,
        extension=extension,
    )
    asset = await MediaRepository(session).create(
        {
            "patient_id": patient.id,
            "interaction_id": interaction_id,
            "asset_type": asset_type,
            "storage_path": stored.storage_path,
            "content_type": file.content_type or "application/octet-stream",
            "sha256": stored.sha256,
            "size_bytes": stored.size_bytes,
            "retention_expires_at": retention_expiration(settings.evidence_retention_days),
        }
    )
    return MediaAssetResponse.model_validate(asset)


@router.post("/cleanup-expired")
async def cleanup_expired_evidence(
    _patient: PatientDep,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, int]:
    deleted = await cleanup_expired_media(
        media_repository=MediaRepository(session),
        storage=LocalEvidenceStorage(settings.evidence_storage_dir),
    )
    return {"deleted": deleted}
