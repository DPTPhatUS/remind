from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Remind Backend"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://remind:remind@localhost:5432/remind"
    openai_api_key: str = ""
    openai_text_model: str = "gpt-5.5"
    openai_transcribe_model: str = "gpt-4o-transcribe"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536
    compreface_base_url: str = "http://localhost:8000"
    compreface_api_key: str = ""
    identity_high_confidence: float = 0.95
    identity_medium_confidence: float = 0.80
    identity_recognized_confidence: float = 0.60
    evidence_storage_dir: Path = Path(".local/evidence")
    evidence_retention_days: int = 30
    live_frame_sample_interval_ms: int = 500
    live_interaction_candidate_score: float = 0.45
    live_interaction_active_score: float = 0.70
    live_interaction_min_candidate_ms: int = 2000
    live_interaction_end_silence_ms: int = 8000
    live_audio_sample_rate_hz: int = 16000
    live_audio_vad_mode: int = 2
    live_audio_utterance_max_ms: int = 12000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
