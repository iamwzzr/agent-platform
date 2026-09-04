import os
from typing import cast
from uuid import uuid4

import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr

from app.openai_provider import OpenAIClient, OpenAIResponsesProvider
from app.schemas.artifact import Requirement
from app.validation import validate_artifact

LIVE_TEST_FLAG = "AGENT_PLATFORM_RUN_OPENAI_LIVE_TEST"
API_KEY_ENV = "AGENT_PLATFORM_OPENAI_API_KEY"
MODEL_ENV = "AGENT_PLATFORM_OPENAI_MODEL"
REQUIRED_CONFIGURATION = (API_KEY_ENV, MODEL_ENV)


def _load_live_configuration() -> tuple[SecretStr, str]:
    missing = [
        name for name in REQUIRED_CONFIGURATION if not os.environ.get(name, "").strip()
    ]
    if missing:
        pytest.fail(
            "OpenAI live smoke test requires non-blank environment variables: "
            + ", ".join(missing),
            pytrace=False,
        )

    return (
        SecretStr(os.environ[API_KEY_ENV].strip()),
        os.environ[MODEL_ENV].strip(),
    )


@pytest.mark.asyncio
async def test_openai_provider_live_draft_passes_validation() -> None:
    if os.environ.get(LIVE_TEST_FLAG) != "1":
        pytest.skip(f"set {LIVE_TEST_FLAG}=1 to enable the paid OpenAI live smoke test")

    secret_api_key, model = _load_live_configuration()
    run_id = uuid4()
    requirement = Requirement(
        id="req-live-smoke",
        text="Operate production Kubernetes workloads.",
        priority="high",
    )

    artifact = None
    failure_type: str | None = None
    try:
        async with AsyncOpenAI(
            api_key=secret_api_key.get_secret_value(),
            max_retries=0,
            timeout=30.0,
        ) as client:
            provider = OpenAIResponsesProvider(
                api_key=secret_api_key.get_secret_value(),
                model=model,
                client=cast(OpenAIClient, client),
            )
            artifact = await provider.draft_artifact(
                run_id=run_id,
                requirements=[requirement],
                evidence=[],
            )
    except Exception as error:  # noqa: BLE001
        failure_type = type(error).__name__

    if failure_type is not None:
        pytest.fail(
            f"OpenAI live smoke request failed with {failure_type}; "
            "provider details were suppressed",
            pytrace=False,
        )
    if artifact is None:
        pytest.fail(
            "OpenAI live smoke request returned no artifact",
            pytrace=False,
        )

    validation = validate_artifact(
        artifact,
        expected_run_id=run_id,
        workspace_id="workspace-live-smoke",
        trusted_requirements=[requirement],
        retrieved_evidence=[],
    )

    if not validation.passed:
        pytest.fail(
            "OpenAI live smoke artifact failed deterministic validation: "
            f"{validation.model_dump_json()}",
            pytrace=False,
        )
