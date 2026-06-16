from fastapi import APIRouter, HTTPException

from api.deps import CurrentUserDep, SessionDep, SettingsDep, to_http_error
from core.errors import AppError
from schemas.auth import (
    BootstrapAdminRequest,
    CurrentUserResponse,
    LoginRequest,
    TokenResponse,
)
from services.auth_service import AuthService

router = APIRouter()


@router.post("/bootstrap-admin", response_model=TokenResponse)
async def bootstrap_admin(
    request: BootstrapAdminRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    service = AuthService(session, settings)
    try:
        user, _patient = await service.bootstrap_admin(
            email=str(request.email),
            display_name=request.display_name,
            password=request.password,
            patient_display_name=request.patient_display_name,
        )
    except AppError as error:
        raise to_http_error(error) from error
    token = service.issue_token(user)
    return TokenResponse(access_token=token.token, expires_at=token.expires_at.isoformat())


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    service = AuthService(session, settings)
    try:
        user = await service.authenticate(email=str(request.email), password=request.password)
    except AppError as error:
        raise to_http_error(error) from error
    token = service.issue_token(user)
    return TokenResponse(access_token=token.token, expires_at=token.expires_at.isoformat())


@router.get("/me", response_model=CurrentUserResponse)
async def me(user: CurrentUserDep) -> CurrentUserResponse:
    if not user.email:
        raise HTTPException(status_code=401, detail="Invalid user.")
    return CurrentUserResponse.model_validate(user)
