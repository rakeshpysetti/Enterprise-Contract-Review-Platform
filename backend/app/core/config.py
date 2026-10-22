"""Settings loaded from environment variables and the repository's .env file."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class AccessAccount(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    role: Literal["reader", "reviewer"] = "reader"
    token_sha256: SecretStr

    @field_validator("token_sha256")
    @classmethod
    def validate_digest(cls, value: SecretStr) -> SecretStr:
        digest = value.get_secret_value()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("token_sha256 must be a lowercase SHA-256 digest")
        return value


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
    auth_accounts: list[AccessAccount] = Field(default_factory=list)
    require_auth: bool = False
    analysis_recovery_seconds: int = Field(default=3600, ge=60)
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://contracts:contracts@localhost:5432/contracts"
    )
    ollama_base_url: HttpUrl = "http://localhost:11434"
    ollama_model: str = "gemma3"
    ollama_timeout_seconds: float = Field(default=120.0, gt=0)
    ollama_max_retries: int = Field(default=2, ge=0, le=10)
    ollama_retry_backoff_seconds: float = Field(default=0.5, ge=0, le=60)
    ollama_temperature: float = Field(default=0.0, ge=0, le=2)
    ollama_num_ctx: int = Field(default=8192, ge=2048, le=131072)
    max_concurrent_model_requests: int = Field(default=1, ge=1, le=8)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    vector_index_dir: Path = Path("data/vector_indexes")
    retrieval_top_k: int = Field(default=5, ge=1, le=10)
    upload_dir: Path = Path("data/sample_contracts")
    processed_dir: Path = Path("data/processed")
    max_pdf_size_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    max_request_body_bytes: int = Field(default=64 * 1024, ge=1024)
    max_pdf_pages: int = Field(default=200, ge=1)
    max_contract_text_chars: int = Field(default=16000, ge=1)
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
        if self.app_env == "production":
            if "*" in self.cors_origins:
                raise ValueError("Production CORS origins must be explicit")
            for origin in self.cors_origins:
                parsed = urlsplit(origin)
                if parsed.scheme != "https" and parsed.hostname not in {
                    "localhost",
                    "127.0.0.1",
                    "::1",
                }:
                    raise ValueError("Production CORS origins must use HTTPS")
        digests = [
            account.token_sha256.get_secret_value() for account in self.auth_accounts
        ]
        if len(digests) != len(set(digests)):
            raise ValueError("Each access key must identify exactly one account")
        return self
