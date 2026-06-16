from datetime import UTC, datetime, timedelta


def retention_expiration(days: int, now: datetime | None = None) -> str:
    base = now or datetime.now(UTC)
    return (base + timedelta(days=days)).isoformat()
