from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.artifact import ApplicationArtifact, ArtifactValidation

RunStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "validation_failed",
    "failed",
]

IdempotencyKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=200,
    ),
]


class RunModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunCreate(RunModel):
    document_ids: list[UUID] = Field(min_length=1, max_length=100)


class RunEventRead(RunModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    run_id: UUID
    sequence: int = Field(ge=0)
    kind: str
    data: dict[str, object]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return _normalize_utc(value)


class CitationSourceRead(RunModel):
    document_id: UUID
    document_name: str
    chunk_id: UUID
    position: int = Field(ge=0)
    excerpt: str


class RunArtifactRead(RunModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    run_id: UUID
    content: ApplicationArtifact
    validation: ArtifactValidation
    citation_sources: list[CitationSourceRead] = Field(default_factory=list)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return _normalize_utc(value)


class RunRead(RunModel):
    id: UUID
    workspace_id: str
    job_id: UUID
    idempotency_key: IdempotencyKey
    document_ids: list[UUID]
    status: RunStatus
    provider: str
    model: str
    current_node: str | None
    revision_count: int = Field(ge=0)
    attempt_count: int = Field(ge=0)
    retryable: bool
    can_resume: bool = False
    terminal_validation: ArtifactValidation | None = None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    lease_expires_at: datetime | None
    events: list[RunEventRead]
    artifact: RunArtifactRead | None

    @field_validator(
        "created_at",
        "started_at",
        "finished_at",
        "lease_expires_at",
    )
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _normalize_utc(value)


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
