from datetime import UTC, datetime, timedelta

from core.security import create_access_token, hash_password, verify_password


def test_password_hash_verifies_original_password_only() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_access_token_contains_subject_role_and_expiration() -> None:
    token_data = create_access_token(
        subject="user-1",
        role="admin",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        secret="test-secret-with-at-least-32-bytes",
    )

    assert token_data.token
    assert token_data.expires_at.tzinfo is UTC
