from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.config import Settings
from app.openai_provider import OpenAIResponsesProvider, ProviderConfigurationError
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
