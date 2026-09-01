import pytest

from app.config import Settings


def test_settings_uses_default_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_PLATFORM_DATABASE_URL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_url == "sqlite+aiosqlite:///./agent-platform.db"


def test_settings_reads_database_url_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AGENT_PLATFORM_DATABASE_URL",
        "sqlite+aiosqlite:///./test.db",
    )

    settings = Settings(_env_file=None)

    assert settings.database_url == "sqlite+aiosqlite:///./test.db"
