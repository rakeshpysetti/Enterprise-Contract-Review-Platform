"""Settings loaded from environment variables and the repository's .env file."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
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
    ollama_model: str = "gemma3"
    ollama_timeout_seconds: float = Field(default=120.0, gt=0)
    ollama_max_retries: int = Field(default=2, ge=0, le=10)
    ollama_retry_backoff_seconds: float = Field(default=0.5, ge=0, le=60)
    ollama_temperature: float = Field(default=0.0, ge=0, le=2)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    vector_index_dir: Path = Path("data/vector_indexes")
    retrieval_top_k: int = Field(default=5, ge=1, le=100)
    upload_dir: Path = Path("data/sample_contracts")
    processed_dir: Path = Path("data/processed")
    max_pdf_size_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    cors_origins: list[str] = Field(default_factory=list)
    cors_allow_credentials: bool = False

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, origins: list[str]) -> list[str]:
        validated: list[str] = []
        for raw_origin in origins:
            origin = raw_origin.strip().rstrip("/")
            if origin == "*":
                validated.append(origin)
                continue
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CORS origins must be valid HTTP or HTTPS origins")
            validated.append(origin)
        return list(dict.fromkeys(validated))

    @model_validator(mode="after")
    def validate_cors_credentials(self) -> "Settings":
        if self.cors_allow_credentials and "*" in self.cors_origins:
            raise ValueError("Wildcard CORS origins cannot allow credentials")
        return self
