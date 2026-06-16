from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings, get_settings
from core.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from core.security import decode_access_token
from db.models import Patient, UserAccount
from db.repositories.auth import AuthRepository
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


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> UserAccount:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_access_token(
            token,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        ) from exc
    user = await AuthRepository(session).get_user(str(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject.",
        )
    return user


CurrentUserDep = Annotated[UserAccount, Depends(get_current_user)]


async def require_admin(user: CurrentUserDep) -> UserAccount:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return user


AdminUserDep = Annotated[UserAccount, Depends(require_admin)]


async def get_current_patient(session: SessionDep, user: CurrentUserDep) -> Patient:
    patient = await AuthRepository(session).first_patient_for_user(user.id)
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
