import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("APP_NAME=From file\nAPP_ENV=test\n", encoding="utf-8")
    monkeypatch.setenv("APP_NAME", "From environment")
    monkeypatch.delenv("APP_ENV", raising=False)
    settings = Settings(_env_file=dotenv)
    assert settings.app_name == "From environment"
    assert settings.app_env == "test"
    assert create_app(settings).title == "From environment"


def test_blank_configuration_uses_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_NAME", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text("APP_NAME=\nUNRELATED_VALUE=ignored\n", encoding="utf-8")
    assert Settings(_env_file=dotenv).app_name == Settings(_env_file=None).app_name


def test_invalid_environment_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="invalid")


def test_database_url_is_redacted():
    settings = Settings(_env_file=None, database_url="postgresql://example")
    assert "postgresql://example" not in repr(settings)
