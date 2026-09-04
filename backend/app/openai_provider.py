import json
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.schemas.artifact import (
    ApplicationArtifact,
    ArtifactValidation,
    Evidence,
    Requirement,
)


class ProviderConfigurationError(ValueError):
    """Raised when a provider is missing required configuration."""


class ProviderResponseError(RuntimeError):
    """Raised when a provider response has no usable structured output."""


class ParsedArtifactResponse(Protocol):
    status: str
    output_parsed: ApplicationArtifact | None


class ResponsesParser(Protocol):
    async def parse(
        self,
        *,
        model: str,
        input: list[dict[str, str]],
        text_format: type[ApplicationArtifact],
        store: bool,
    ) -> ParsedArtifactResponse: ...


class OpenAIClient(Protocol):
    responses: ResponsesParser


class OpenAIResponsesProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        client: OpenAIClient | None = None,
    ) -> None:
        if api_key is None or not api_key.strip():
            raise ProviderConfigurationError(
                "AGENT_PLATFORM_OPENAI_API_KEY is required for the OpenAI provider"
            )
        if not model.strip():
            raise ProviderConfigurationError(
                "AGENT_PLATFORM_OPENAI_MODEL is required for the OpenAI provider"
            )

        self._api_key = api_key.strip()
        self.model_name = model.strip()
        self._client = (
            client if client is not None else AsyncOpenAI(api_key=self._api_key)
        )

    async def draft_artifact(
        self,
        *,
        run_id: UUID,
        requirements: Sequence[Requirement],
        evidence: Sequence[Evidence],
    ) -> ApplicationArtifact:
        return await self._request_artifact(
            instructions=(
                "Create a grounded ApplicationArtifact using only the supplied "
                "requirements and evidence. Record a no_grounded_evidence gap "
                "instead of inventing facts."
            ),
            request_data={
                "run_id": str(run_id),
                "requirements": [
                    requirement.model_dump(mode="json") for requirement in requirements
                ],
                "evidence": [item.model_dump(mode="json") for item in evidence],
            },
        )

    async def revise_artifact(
        self,
        *,
        run_id: UUID,
        artifact: ApplicationArtifact,
        validation: ArtifactValidation,
        requirements: Sequence[Requirement],
        evidence: Sequence[Evidence],
    ) -> ApplicationArtifact:
        return await self._request_artifact(
            instructions=(
                "Revise the supplied ApplicationArtifact to address the "
                "validation results. Use only the supplied requirements and "
                "evidence, and never invent facts or citations."
            ),
            request_data={
                "run_id": str(run_id),
                "artifact": artifact.model_dump(mode="json"),
                "validation": validation.model_dump(mode="json"),
                "requirements": [
                    requirement.model_dump(mode="json") for requirement in requirements
                ],
                "evidence": [item.model_dump(mode="json") for item in evidence],
            },
        )

    async def _request_artifact(
        self,
        *,
        instructions: str,
        request_data: dict[str, object],
    ) -> ApplicationArtifact:
        try:
            response = await self._client.responses.parse(
                model=self.model_name,
                input=[
                    {
                        "role": "system",
                        "content": instructions,
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            request_data,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    },
                ],
                text_format=ApplicationArtifact,
                store=False,
            )
        except ValidationError:
            raise ProviderResponseError(
                "OpenAI response did not include a parsed ApplicationArtifact"
            ) from None

        if response.status != "completed":
            raise ProviderResponseError("OpenAI response did not complete successfully")

        if response.output_parsed is None:
            raise ProviderResponseError(
                "OpenAI response did not include a parsed ApplicationArtifact"
            )

        return response.output_parsed
