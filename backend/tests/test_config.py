import traceback

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_uses_default_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_PLATFORM_DATABASE_URL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_url == "sqlite+aiosqlite:///./agent-platform.db"


def test_settings_uses_bounded_provider_retry_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.provider_retry_max_attempts == 3
    assert settings.provider_retry_initial_delay_seconds == 0.5


def test_settings_reads_database_url_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AGENT_PLATFORM_DATABASE_URL",
        "sqlite+aiosqlite:///./test.db",
    )

    settings = Settings(_env_file=None)

    assert settings.database_url == "sqlite+aiosqlite:///./test.db"


def test_settings_reads_provider_retry_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_PLATFORM_PROVIDER_RETRY_MAX_ATTEMPTS", "5")
    monkeypatch.setenv(
        "AGENT_PLATFORM_PROVIDER_RETRY_INITIAL_DELAY_SECONDS",
        "1.25",
    )

    settings = Settings(_env_file=None)

    assert settings.provider_retry_max_attempts == 5
    assert settings.provider_retry_initial_delay_seconds == 1.25


@pytest.mark.parametrize(
    ("setting_name", "value"),
    [
        ("provider_retry_max_attempts", 0),
        ("provider_retry_max_attempts", 6),
        ("provider_retry_initial_delay_seconds", -0.1),
        ("provider_retry_initial_delay_seconds", 61.0),
    ],
)
def test_settings_rejects_unbounded_provider_retry_configuration(
    setting_name: str,
    value: float,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            **{setting_name: value},
        )


def test_settings_reads_openai_provider_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_PLATFORM_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AGENT_PLATFORM_OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("AGENT_PLATFORM_OPENAI_MODEL", "test-model")

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "openai"
    assert settings.openai_model == "test-model"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "test-api-key"
    assert "test-api-key" not in repr(settings)


def test_settings_rejects_openai_provider_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_PLATFORM_LLM_PROVIDER", "openai")
    monkeypatch.delenv("AGENT_PLATFORM_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_PLATFORM_OPENAI_MODEL", "test-model")

    with pytest.raises(
        ValidationError,
        match="AGENT_PLATFORM_OPENAI_API_KEY",
    ):
        Settings(_env_file=None)


def test_settings_rejects_openai_provider_without_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_PLATFORM_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AGENT_PLATFORM_OPENAI_API_KEY", "test-api-key")
    monkeypatch.delenv("AGENT_PLATFORM_OPENAI_MODEL", raising=False)

    with pytest.raises(
        ValidationError,
        match="AGENT_PLATFORM_OPENAI_MODEL",
    ):
        Settings(_env_file=None)


def test_settings_validation_error_does_not_expose_openai_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_marker = "private-openai-key-marker"
    monkeypatch.setenv("AGENT_PLATFORM_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AGENT_PLATFORM_OPENAI_API_KEY", private_marker)
    monkeypatch.delenv("AGENT_PLATFORM_OPENAI_MODEL", raising=False)

    with pytest.raises(
        ValidationError,
        match="AGENT_PLATFORM_OPENAI_MODEL",
    ) as error:
        Settings(_env_file=None)

    rendered_error = (
        str(error.value)
        + error.value.json()
        + "".join(traceback.format_exception(error.value))
    )
    assert private_marker not in rendered_error


@pytest.mark.parametrize(
    ("api_key", "model", "expected_setting"),
    [
        ("   ", "test-model", "AGENT_PLATFORM_OPENAI_API_KEY"),
        ("test-api-key", "   ", "AGENT_PLATFORM_OPENAI_MODEL"),
    ],
)
def test_settings_rejects_blank_openai_configuration(
    api_key: str,
    model: str,
    expected_setting: str,
) -> None:
    with pytest.raises(
        ValidationError,
        match=expected_setting,
    ):
        Settings(
            _env_file=None,
            llm_provider="openai",
            openai_api_key=api_key,
            openai_model=model,
        )


def test_settings_uses_default_agent_max_revisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_PLATFORM_AGENT_MAX_REVISIONS", raising=False)
    assert Settings(_env_file=None).agent_max_revisions == 2


@pytest.mark.parametrize("value", [0, 5])
def test_settings_reads_bounded_agent_max_revisions_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    value: int,
) -> None:
    monkeypatch.setenv("AGENT_PLATFORM_AGENT_MAX_REVISIONS", str(value))
    assert Settings(_env_file=None).agent_max_revisions == value


@pytest.mark.parametrize("value", [-1, 6])
def test_settings_rejects_out_of_bounds_agent_max_revisions(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, agent_max_revisions=value)
