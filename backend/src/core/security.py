from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_password_hasher = PasswordHasher()


@dataclass(frozen=True)
class AccessToken:
    token: str
    expires_at: datetime


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return _password_hasher.verify(hashed_password, password)
    except VerifyMismatchError:
        return False


def create_access_token(
    *,
    subject: str,
    role: str,
    secret: str,
    issuer: str = "remind-backend",
    expires_at: datetime | None = None,
    lifetime: timedelta | None = None,
) -> AccessToken:
    expires = expires_at or datetime.now(UTC) + (lifetime or timedelta(hours=12))
    payload = {
        "sub": subject,
        "role": role,
        "iss": issuer,
        "exp": expires,
        "iat": datetime.now(UTC),
    }
    return AccessToken(
        token=jwt.encode(payload, secret, algorithm="HS256"),
        expires_at=expires,
    )


def decode_access_token(
    token: str,
    *,
    secret: str,
    issuer: str = "remind-backend",
) -> dict[str, Any]:
    return jwt.decode(token, secret, algorithms=["HS256"], issuer=issuer)
