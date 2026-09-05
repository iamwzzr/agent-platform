from unittest.mock import Mock

import pytest

import app.openai_provider as openai_provider_module
import app.providers as providers_module
from app.config import Settings
from app.openai_provider import OpenAIResponsesProvider
from app.providers import AgentProvider, DeterministicMockProvider


def test_build_agent_provider_uses_mock_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_PLATFORM_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_PLATFORM_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_PLATFORM_OPENAI_MODEL", raising=False)

    client_factory = Mock()
    monkeypatch.setattr(
        openai_provider_module,
        "AsyncOpenAI",
        client_factory,
    )
    client_factory.assert_not_called()

    settings = Settings(_env_file=None)

    provider = providers_module.build_agent_provider(settings)

    assert isinstance(provider, DeterministicMockProvider)
    assert isinstance(provider, AgentProvider)
    client_factory.assert_not_called()


def test_build_agent_provider_uses_openai_when_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = Mock()
    client_factory = Mock(return_value=fake_client)
    monkeypatch.setattr(
        openai_provider_module,
        "AsyncOpenAI",
        client_factory,
    )
    settings = Settings(
        _env_file=None,
        llm_provider="openai",
        openai_api_key="test-api-key",
        openai_model="test-model",
    )

    provider = providers_module.build_agent_provider(settings)

    assert isinstance(provider, OpenAIResponsesProvider)
    assert isinstance(provider, AgentProvider)
    assert provider.model_name == "test-model"
    client_factory.assert_called_once_with(
        api_key="test-api-key",
        max_retries=0,
    )
