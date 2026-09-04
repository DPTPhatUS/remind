from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings, get_settings
from core.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from db.models import Patient
from db.session import get_session
from providers.compreface import CompreFaceClient

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def to_http_error(error: AppError) -> HTTPException:
    if isinstance(error, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error.message)
    if isinstance(error, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error.message)
    if isinstance(error, PermissionDeniedError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error.message)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error.message)


async def get_current_patient(session: SessionDep) -> Patient:
    result = await session.execute(select(Patient).order_by(Patient.created_at.asc()).limit(1))
    patient = result.scalars().first()
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient profile not found.",
        )
    return patient


PatientDep = Annotated[Patient, Depends(get_current_patient)]


def get_compreface_client(settings: SettingsDep) -> CompreFaceClient:
    return CompreFaceClient(
        base_url=settings.compreface_base_url,
        api_key=settings.compreface_api_key,
    )


CompreFaceDep = Annotated[CompreFaceClient, Depends(get_compreface_client)]