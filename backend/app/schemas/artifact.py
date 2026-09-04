from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
    ),
]

ShortText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=800,
    ),
]

LongText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=5_000,
    ),
]


class ArtifactModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Requirement(ArtifactModel):
    id: Identifier
    text: ShortText
    priority: Literal["high", "medium", "low"]


class Citation(ArtifactModel):
    document_id: UUID
    chunk_id: UUID


class Evidence(ArtifactModel):
    requirement_id: Identifier
    workspace_id: Identifier
    document_id: UUID
    chunk_id: UUID
    excerpt: ShortText
    score: float = Field(ge=0.0, le=1.0)


class Claim(ArtifactModel):
    id: Identifier
    text: ShortText
    requirement_ids: list[Identifier] = Field(
        min_length=1,
        max_length=20,
    )
    citation_chunk_ids: list[UUID] = Field(
        min_length=1,
        max_length=20,
    )


class ResumeBullet(ArtifactModel):
    text: ShortText
    claim_ids: list[Identifier] = Field(
        min_length=1,
        max_length=20,
    )


class Gap(ArtifactModel):
    requirement_id: Identifier
    reason_code: Literal["no_grounded_evidence"]


class ApplicationArtifact(ArtifactModel):
    run_id: UUID
    requirements: list[Requirement] = Field(
        min_length=1,
        max_length=20,
    )
    claims: list[Claim] = Field(
        default_factory=list,
        max_length=50,
    )
    resume_bullets: list[ResumeBullet] = Field(
        default_factory=list,
        max_length=20,
    )
    cover_letter: LongText | None = None
    gaps: list[Gap] = Field(
        default_factory=list,
        max_length=20,
    )
    citations: list[Citation] = Field(
        default_factory=list,
        max_length=100,
    )


class ArtifactValidation(ArtifactModel):
    passed: bool
    invalid_citation_chunk_ids: list[UUID] = Field(default_factory=list)
    unsupported_claim_ids: list[Identifier] = Field(default_factory=list)
    unsupported_requirement_ids: list[Identifier] = Field(default_factory=list)
    unsupported_resume_bullet_indexes: list[int] = Field(default_factory=list)
    unsupported_cover_letter: bool = False
    uncovered_requirement_ids: list[Identifier] = Field(default_factory=list)
    conflicting_requirement_ids: list[Identifier] = Field(default_factory=list)
    mismatched_requirement_ids: list[Identifier] = Field(default_factory=list)
    duplicate_requirement_ids: list[Identifier] = Field(default_factory=list)
    unknown_gap_requirement_ids: list[Identifier] = Field(default_factory=list)
    evidenced_gap_requirement_ids: list[Identifier] = Field(default_factory=list)
    duplicate_gap_requirement_ids: list[Identifier] = Field(default_factory=list)
    duplicate_claim_ids: list[Identifier] = Field(default_factory=list)
    unsupported_citation_chunk_ids: list[UUID] = Field(default_factory=list)
    run_id_mismatch: bool = False
