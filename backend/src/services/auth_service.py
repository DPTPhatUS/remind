from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings
from core.errors import ConflictError, PermissionDeniedError
from core.security import create_access_token, hash_password, verify_password
from db.models import Patient, UserAccount
from db.repositories.auth import AuthRepository


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.repository = AuthRepository(session)
        self.settings = settings

    async def bootstrap_admin(
        self,
        *,
        email: str,
        display_name: str,
        password: str,
        patient_display_name: str,
    ) -> tuple[UserAccount, Patient]:
        if not self.settings.allow_bootstrap_admin:
            raise PermissionDeniedError("Admin bootstrap is disabled.")
        if await self.repository.admin_count() > 0:
            raise ConflictError("An admin account already exists.")
        return await self.repository.create_admin_with_patient(
            email=email,
            display_name=display_name,
            password_hash=hash_password(password),
            patient_display_name=patient_display_name,
        )

    async def authenticate(self, *, email: str, password: str) -> UserAccount:
        user = await self.repository.get_user_by_email(email)
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise PermissionDeniedError("Invalid email or password.")
        return user

    def issue_token(self, user: UserAccount):
        return create_access_token(
            subject=user.id,
            role=user.role,
            secret=self.settings.jwt_secret,
            issuer=self.settings.jwt_issuer,
            expires_at=datetime.now(UTC) + timedelta(minutes=self.settings.access_token_minutes),
        )

    async def patient_for_user(self, user_id: str) -> Patient | None:
        return await self.repository.first_patient_for_user(user_id)
