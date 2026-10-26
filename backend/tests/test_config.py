import pytest
from pydantic import ValidationError

from remind.config import Settings


@pytest.mark.parametrize(
    "values",
    [
        {"enrollment_ms": 0},
        {"min_observations": 0},
        {"vision_threads": 0},
        {"voice_visitor_threshold": 0.8, "voice_user_threshold": 0.65},
        {"memory_timezone": "invalid/timezone"},
    ],
)
def test_invalid_runtime_settings_are_rejected(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)
