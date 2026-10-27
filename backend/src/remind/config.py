from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_dir: Path = Path(".local")
    openai_api_key: str = Field(
        default="", validation_alias=AliasChoices("REMIND_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    openai_text_model: str = "gpt-6-luna"
    openai_transcribe_model: str = "gpt-4o-transcribe-diarize"
    match_threshold: float = Field(default=0.55, ge=0, le=1)
    match_margin: float = Field(default=0.08, ge=0, le=1)
    enrollment_ms: int = Field(default=2000, gt=0)
    min_observations: int = Field(default=5, ge=1)
    vision_threads: int = Field(default=4, ge=1)
    # ECAPA cosine operating points; calibrate on staged Remind conversations.
    voice_user_threshold: float = Field(default=0.65, ge=0, le=1)
    voice_visitor_threshold: float = Field(default=0.35, ge=-1, le=1)
    voice_enrollment_threshold: float = Field(default=0.55, ge=0, le=1)
    voice_min_speech_seconds: float = Field(default=1.5, ge=0.5, le=10)
    voice_threads: int = Field(default=2, ge=1, le=16)
    memory_timezone: str = "Asia/Ho_Chi_Minh"
    spool_limit_bytes: int = Field(default=1073741824, gt=0)
    media_retention_seconds: int = Field(default=86400, gt=0)
    origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if self.voice_visitor_threshold >= self.voice_user_threshold:
            raise ValueError("Voice visitor threshold must be below user threshold")
        try:
            ZoneInfo(self.memory_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("memory_timezone must be a valid IANA timezone") from exc
        return self

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_prefix="REMIND_", populate_by_name=True
    )
