import json
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

import app.openai_provider as openai_provider_module
from app.openai_provider import (
    OpenAIResponsesProvider,
    ProviderConfigurationError,
    ProviderResponseError,
)
from app.schemas.artifact import (
    ApplicationArtifact,
    ArtifactValidation,
    Gap,
    Requirement,
)


def test_openai_provider_rejects_missing_api_key() -> None:
    with pytest.raises(
        ProviderConfigurationError,
        match="AGENT_PLATFORM_OPENAI_API_KEY",
    ):
        OpenAIResponsesProvider(
            api_key=None,
            model="test-model",
        )


@pytest.mark.asyncio
async def test_openai_provider_drafts_with_structured_output() -> None:
    run_id = uuid4()
    requirement = Requirement(
        id="req-1",
        text="Operate Kubernetes workloads.",
        priority="high",
    )
    expected_artifact = ApplicationArtifact(
        run_id=run_id,
        requirements=[requirement],
        gaps=[
            Gap(
                requirement_id=requirement.id,
                reason_code="no_grounded_evidence",
            )
        ],
    )
    parse = AsyncMock(
        return_value=SimpleNamespace(
            status="completed",
            output_parsed=expected_artifact,
        )
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=parse),
    )
    provider = OpenAIResponsesProvider(
        api_key="test-api-key",
        model="test-model",
        client=client,
    )

    result = await provider.draft_artifact(
        run_id=run_id,
        requirements=[requirement],
        evidence=[],
    )

    assert result == expected_artifact
    parse.assert_awaited_once()

    request = parse.await_args.kwargs
    assert request["model"] == "test-model"
    assert request["text_format"] is ApplicationArtifact
    assert request["store"] is False
    assert str(run_id) in request["input"][-1]["content"]
    assert requirement.text in request["input"][-1]["content"]


@pytest.mark.asyncio
async def test_openai_provider_rejects_missing_parsed_output() -> None:
    requirement = Requirement(
        id="req-1",
        text="Operate Kubernetes workloads.",
        priority="high",
    )
    private_output = "private raw provider output"
    parse = AsyncMock(
        return_value=SimpleNamespace(
            status="completed",
            output_parsed=None,
            output_text=private_output,
        )
    )
    provider = OpenAIResponsesProvider(
        api_key="test-api-key",
        model="test-model",
        client=SimpleNamespace(
            responses=SimpleNamespace(parse=parse),
        ),
    )

    with pytest.raises(
        ProviderResponseError,
        match="parsed ApplicationArtifact",
    ) as error:
        await provider.draft_artifact(
            run_id=uuid4(),
            requirements=[requirement],
            evidence=[],
        )

    assert private_output not in str(error.value)
    assert "test-api-key" not in str(error.value)


@pytest.mark.asyncio
async def test_openai_provider_revises_with_validation_context() -> None:
    run_id = uuid4()
    requirement = Requirement(
        id="req-1",
        text="Operate Kubernetes workloads.",
        priority="high",
    )
    original_artifact = ApplicationArtifact(
        run_id=run_id,
        requirements=[requirement],
    )
    validation = ArtifactValidation(
        passed=False,
        uncovered_requirement_ids=[requirement.id],
    )
    revised_artifact = ApplicationArtifact(
        run_id=run_id,
        requirements=[requirement],
        gaps=[
            Gap(
                requirement_id=requirement.id,
                reason_code="no_grounded_evidence",
            )
        ],
    )
    parse = AsyncMock(
        return_value=SimpleNamespace(
            status="completed",
            output_parsed=revised_artifact,
        )
    )
    provider = OpenAIResponsesProvider(
        api_key="test-api-key",
        model="test-model",
        client=SimpleNamespace(
            responses=SimpleNamespace(parse=parse),
        ),
    )

    result = await provider.revise_artifact(
        run_id=run_id,
        artifact=original_artifact,
        validation=validation,
        requirements=[requirement],
        evidence=[],
    )

    assert result == revised_artifact
    parse.assert_awaited_once()

    request = parse.await_args.kwargs
    assert request["model"] == "test-model"
    assert request["text_format"] is ApplicationArtifact
    assert request["store"] is False

    request_data = json.loads(request["input"][-1]["content"])
    assert request_data == {
        "run_id": str(run_id),
        "artifact": original_artifact.model_dump(mode="json"),
        "validation": validation.model_dump(mode="json"),
        "requirements": [requirement.model_dump(mode="json")],
        "evidence": [],
    }


@pytest.mark.asyncio
async def test_openai_provider_builds_default_client_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    requirement = Requirement(
        id="req-1",
        text="Operate Kubernetes workloads.",
        priority="high",
    )
    expected_artifact = ApplicationArtifact(
        run_id=run_id,
        requirements=[requirement],
        gaps=[
            Gap(
                requirement_id=requirement.id,
                reason_code="no_grounded_evidence",
            )
        ],
    )
    parse = AsyncMock(
        return_value=SimpleNamespace(
            status="completed",
            output_parsed=expected_artifact,
        )
    )
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(parse=parse),
    )
    client_factory = Mock(return_value=fake_client)
    monkeypatch.setattr(
        openai_provider_module,
        "AsyncOpenAI",
        client_factory,
    )

    provider = OpenAIResponsesProvider(
        api_key=" test-api-key ",
        model="test-model",
    )

    result = await provider.draft_artifact(
        run_id=run_id,
        requirements=[requirement],
        evidence=[],
    )

    assert result == expected_artifact
    client_factory.assert_called_once_with(api_key="test-api-key")
    parse.assert_awaited_once()


@pytest.mark.asyncio
async def test_openai_provider_sanitizes_pydantic_parse_error() -> None:
    private_marker = "private-provider-output-marker"
    api_key = "test-api-key"
    requirement = Requirement(
        id="req-1",
        text="Operate Kubernetes workloads.",
        priority="high",
    )

    with pytest.raises(ValidationError) as parse_error:
        ApplicationArtifact.model_validate_json(
            json.dumps(
                {
                    "run_id": private_marker,
                    "requirements": [requirement.model_dump(mode="json")],
                }
            )
        )

    assert private_marker in str(parse_error.value)

    parse = AsyncMock(side_effect=parse_error.value)
    provider = OpenAIResponsesProvider(
        api_key=api_key,
        model="test-model",
        client=SimpleNamespace(
            responses=SimpleNamespace(parse=parse),
        ),
    )

    with pytest.raises(ProviderResponseError) as error:
        await provider.draft_artifact(
            run_id=uuid4(),
            requirements=[requirement],
            evidence=[],
        )

    assert str(error.value) == (
        "OpenAI response did not include a parsed ApplicationArtifact"
    )
    rendered_error = "".join(traceback.format_exception(error.value))
    assert private_marker not in rendered_error
    assert api_key not in rendered_error


@pytest.mark.asyncio
async def test_openai_provider_rejects_incomplete_response_even_if_parsed() -> None:
    run_id = uuid4()
    requirement = Requirement(
        id="req-1",
        text="Operate Kubernetes workloads.",
        priority="high",
    )
    parsed_artifact = ApplicationArtifact(
        run_id=run_id,
        requirements=[requirement],
    )
    private_details = "private incomplete response details"
    parse = AsyncMock(
        return_value=SimpleNamespace(
            status="incomplete",
            output_parsed=parsed_artifact,
            incomplete_details=private_details,
        )
    )
    provider = OpenAIResponsesProvider(
        api_key="test-api-key",
        model="test-model",
        client=SimpleNamespace(
            responses=SimpleNamespace(parse=parse),
        ),
    )

    with pytest.raises(ProviderResponseError) as error:
        await provider.draft_artifact(
            run_id=run_id,
            requirements=[requirement],
            evidence=[],
        )

    assert str(error.value) == "OpenAI response did not complete successfully"
    rendered_error = "".join(traceback.format_exception(error.value))
    assert private_details not in rendered_error
    assert "test-api-key" not in rendered_error


def test_openai_provider_rejects_blank_model_before_client_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_factory = Mock()
    monkeypatch.setattr(
        openai_provider_module,
        "AsyncOpenAI",
        client_factory,
    )

    with pytest.raises(
        ProviderConfigurationError,
        match="AGENT_PLATFORM_OPENAI_MODEL",
    ):
        OpenAIResponsesProvider(
            api_key="test-api-key",
            model="   ",
        )

    client_factory.assert_not_called()
