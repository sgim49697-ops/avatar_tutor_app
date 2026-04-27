# config.py - environment-driven settings for the avatar tutor POC backend
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Avatar Tutor POC"
    app_env: str = "local"
    backend_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    database_url: str | None = None
    auto_migrate: bool = False

    model_mode: Literal["local", "mock"] = "local"
    model_fallback_enabled: bool = True
    model_device: str = "cuda"

    stt_model_name: str = "large-v3-turbo"
    embedding_model_name: str = "BAAI/bge-m3"

    llm_base_url: str = "http://localhost:8001/v1"
    llm_model_name: str = "Qwen/Qwen3-8B"
    llm_api_key: str = "local-dev-key"
    llm_timeout_sec: float = 60.0

    tts_language: str = "KR"
    tts_speaker_id: str | None = None
    tts_output_dir: Path = Field(default=Path("backend/app/static/tts"))

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

