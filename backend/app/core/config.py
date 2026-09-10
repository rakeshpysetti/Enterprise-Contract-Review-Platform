"""Settings loaded from environment variables and the repository's .env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_name: str = Field(
        default="Enterprise Contract Review & Obligation Extraction Platform",
        min_length=1,
    )
    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://contracts:contracts@localhost:5432/contracts"
    )
    ollama_base_url: HttpUrl = "http://localhost:11434"
    ollama_model: str | None = None
    embedding_model: str | None = None
    upload_dir: Path = Path("data/sample_contracts")
    processed_dir: Path = Path("data/processed")
