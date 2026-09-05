import asyncio
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.config import Settings
from app.openai_provider import (
    OpenAIResponsesProvider,
    ProviderConfigurationError,
    ProviderResponseError,
)
from app.schemas.artifact import (
    ApplicationArtifact,
    ArtifactValidation,
    Citation,
    Claim,
    Evidence,
    Gap,
    Requirement,
    ResumeBullet,
)

ProviderFailureReason = Literal[
    "timeout",
    "connection_error",
    "rate_limited",
    "quota_exceeded",
    "conflict",
    "server_error",
    "configuration_error",
    "invalid_response",
    "client_error",
    "unknown_error",
]


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    retryable: bool
    reason_code: ProviderFailureReason
    retry_after_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ProviderRetry:
    attempt: int
    max_attempts: int
    delay_seconds: float
    reason_code: ProviderFailureReason


def _retry_after_seconds(error: APIStatusError) -> float | None:
    headers = error.response.headers
    milliseconds = headers.get("retry-after-ms")
    if milliseconds is not None:
        try:
            delay = float(milliseconds) / 1_000
        except ValueError:
            pass
        else:
            return delay if 0 <= delay <= 60 else None

    retry_after = headers.get("retry-after")
    if retry_after is None:
        return None
    try:
        delay = float(retry_after)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(retry_after)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        delay = (retry_at - datetime.now(UTC)).total_seconds()
    return delay if 0 <= delay <= 60 else None


def _jitter_delay(delay_seconds: float) -> float:
    return delay_seconds * random.uniform(0.75, 1.0)


def classify_provider_error(error: Exception) -> ProviderFailure:
    if isinstance(error, ProviderConfigurationError):
        return ProviderFailure(
            retryable=False,
            reason_code="configuration_error",
        )
    if isinstance(error, ProviderResponseError):
        return ProviderFailure(
            retryable=False,
            reason_code="invalid_response",
        )
    if isinstance(error, APITimeoutError):
        return ProviderFailure(
            retryable=True,
            reason_code="timeout",
        )
    if isinstance(error, APIConnectionError):
        return ProviderFailure(
            retryable=True,
            reason_code="connection_error",
        )
    if isinstance(error, APIStatusError):
        if error.status_code == 429:
            body = error.body
            error_code: object = None
            error_type: object = None
            if isinstance(body, dict):
                error_code = body.get("code")
                error_type = body.get("type")
                nested_error = body.get("error")
                if isinstance(nested_error, dict):
                    error_code = error_code or nested_error.get("code")
                    error_type = error_type or nested_error.get("type")
            if error_code in {
                "billing_hard_limit_reached",
                "billing_not_active",
                "insufficient_quota",
                "usage_limit_reached",
            } or error_type in {"insufficient_quota", "billing_error"}:
                return ProviderFailure(
                    retryable=False,
                    reason_code="quota_exceeded",
                )

        if error.status_code == 408:
            reason_code: ProviderFailureReason = "timeout"
        elif error.status_code == 409:
            reason_code = "conflict"
        elif error.status_code == 429:
            reason_code = "rate_limited"
        elif error.status_code >= 500:
            reason_code = "server_error"
        else:
            reason_code = "client_error"

        if error.status_code in {401, 403}:
            return ProviderFailure(
                retryable=False,
                reason_code=reason_code,
            )

        retry_header = error.response.headers.get("x-should-retry")
        if retry_header == "true":
            retryable = True
        elif retry_header == "false":
            retryable = False
        else:
            retryable = error.status_code in {408, 409, 429} or error.status_code >= 500
        return ProviderFailure(
            retryable=retryable,
            reason_code=reason_code,
            retry_after_seconds=(_retry_after_seconds(error) if retryable else None),
        )
    return ProviderFailure(
        retryable=False,
        reason_code="unknown_error",
    )


async def retry_external[T](
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int,
    initial_delay_seconds: float,
    classify: Callable[[Exception], ProviderFailure] = classify_provider_error,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_retry: Callable[[ProviderRetry], Awaitable[None]] | None = None,
    jitter: Callable[[float], float] = _jitter_delay,
) -> T:
    if not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be between 1 and 5")
    if not 0 <= initial_delay_seconds <= 60:
        raise ValueError("initial_delay_seconds must be between 0 and 60")

    attempt = 1
    while True:
        try:
            return await operation()
        except Exception as error:
            failure = classify(error)
            if not failure.retryable or attempt >= max_attempts:
                raise

            backoff_seconds = min(
                60.0,
                initial_delay_seconds * (2 ** (attempt - 1)),
            )
            delay_seconds = (
                failure.retry_after_seconds
                if failure.retry_after_seconds is not None
                else max(0.0, min(60.0, jitter(backoff_seconds)))
            )
            if on_retry is not None:
                await on_retry(
                    ProviderRetry(
                        attempt=attempt,
                        max_attempts=max_attempts,
                        delay_seconds=delay_seconds,
                        reason_code=failure.reason_code,
                    )
                )
            await sleep(delay_seconds)
            attempt += 1


@runtime_checkable
class AgentProvider(Protocol):
    name: str
    model_name: str

    async def draft_artifact(
        self,
        *,
        run_id: UUID,
        requirements: Sequence[Requirement],
        evidence: Sequence[Evidence],
    ) -> ApplicationArtifact: ...
    async def revise_artifact(
        self,
        *,
        run_id: UUID,
        artifact: ApplicationArtifact,
        validation: ArtifactValidation,
        requirements: Sequence[Requirement],
        evidence: Sequence[Evidence],
    ) -> ApplicationArtifact: ...


class DeterministicMockProvider:
    name = "mock"
    model_name = "deterministic-mock-v1"

    async def draft_artifact(
        self,
        *,
        run_id: UUID,
        requirements: Sequence[Requirement],
        evidence: Sequence[Evidence],
    ) -> ApplicationArtifact:
        evidence_by_requirement: dict[
            str,
            list[Evidence],
        ] = {}

        for item in evidence:
            evidence_by_requirement.setdefault(
                item.requirement_id,
                [],
            ).append(item)

        claims: list[Claim] = []
        resume_bullets: list[ResumeBullet] = []
        gaps: list[Gap] = []
        citations_by_chunk_id: dict[UUID, Citation] = {}

        for index, requirement in enumerate(
            requirements,
            start=1,
        ):
            matches = sorted(
                evidence_by_requirement.get(
                    requirement.id,
                    [],
                ),
                key=lambda item: (
                    -item.score,
                    str(item.chunk_id),
                ),
            )

            if not matches:
                gaps.append(
                    Gap(
                        requirement_id=requirement.id,
                        reason_code="no_grounded_evidence",
                    )
                )
                continue

            best_evidence = matches[0]
            claim_id = f"claim-{index}"

            claims.append(
                Claim(
                    id=claim_id,
                    text=best_evidence.excerpt,
                    requirement_ids=[requirement.id],
                    citation_chunk_ids=[best_evidence.chunk_id],
                )
            )
            resume_bullets.append(
                ResumeBullet(
                    text=best_evidence.excerpt,
                    claim_ids=[claim_id],
                )
            )
            citations_by_chunk_id.setdefault(
                best_evidence.chunk_id,
                Citation(
                    document_id=best_evidence.document_id,
                    chunk_id=best_evidence.chunk_id,
                ),
            )

        return ApplicationArtifact(
            run_id=run_id,
            requirements=[
                requirement.model_copy(deep=True) for requirement in requirements
            ],
            claims=claims,
            resume_bullets=resume_bullets,
            cover_letter=None,
            gaps=gaps,
            citations=list(citations_by_chunk_id.values()),
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
        return await self.draft_artifact(
            run_id=run_id,
            requirements=requirements,
            evidence=evidence,
        )


def build_agent_provider(settings: Settings) -> AgentProvider:
    if settings.llm_provider == "mock":
        return DeterministicMockProvider()

    api_key = settings.openai_api_key
    model = settings.openai_model
    if api_key is None or model is None:
        raise ProviderConfigurationError(
            "OpenAI provider requires AGENT_PLATFORM_OPENAI_API_KEY "
            "and AGENT_PLATFORM_OPENAI_MODEL"
        )

    return OpenAIResponsesProvider(
        api_key=api_key.get_secret_value(),
        model=model,
    )
