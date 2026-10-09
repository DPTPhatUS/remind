from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_dir: Path = Path(".local")
    openai_api_key: str = Field(
        default="", validation_alias=AliasChoices("REMIND_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    openai_text_model: str = "gpt-4.1-mini"
    openai_transcribe_model: str = "gpt-4o-transcribe-diarize"
    match_threshold: float = Field(default=0.55, ge=0, le=1)
    match_margin: float = Field(default=0.08, ge=0, le=1)
    enrollment_ms: int = 2000
    min_observations: int = 5
    vision_threads: int = 4
    speaker_device: str = "cpu"
    speaker_threshold: float = 0.8
    spool_limit_bytes: int = Field(default=1073741824, gt=0)
    media_retention_seconds: int = Field(default=86400, gt=0)
    origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_prefix="REMIND_", populate_by_name=True
    )
