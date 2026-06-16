from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import CaregiverAccess, Patient, UserAccount


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def admin_count(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(UserAccount).where(UserAccount.role == "admin")
        )
        return int(result.scalar_one())

    async def get_user_by_email(self, email: str) -> UserAccount | None:
        result = await self.session.execute(select(UserAccount).where(UserAccount.email == email))
        return result.scalar_one_or_none()

    async def get_user(self, user_id: str) -> UserAccount | None:
        return await self.session.get(UserAccount, user_id)

    async def create_admin_with_patient(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
        patient_display_name: str,
    ) -> tuple[UserAccount, Patient]:
        user = UserAccount(
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            role="admin",
        )
        patient = Patient(display_name=patient_display_name)
        self.session.add_all([user, patient])
        await self.session.flush()
        self.session.add(
            CaregiverAccess(patient_id=patient.id, user_id=user.id, access_level="admin")
        )
        await self.session.commit()
        await self.session.refresh(user)
        await self.session.refresh(patient)
        return user, patient

    async def first_patient_for_user(self, user_id: str) -> Patient | None:
        result = await self.session.execute(
            select(Patient)
            .join(CaregiverAccess, CaregiverAccess.patient_id == Patient.id)
            .where(CaregiverAccess.user_id == user_id)
        )
        return result.scalars().first()
