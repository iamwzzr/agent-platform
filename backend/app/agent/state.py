import operator
from typing import Annotated, Literal, TypedDict
from uuid import UUID

from app.schemas.artifact import (
    ApplicationArtifact,
    ArtifactValidation,
    Evidence,
    Requirement,
)

NodeName = Literal[
    "extract",
    "retrieve",
    "draft",
    "validate",
    "revise",
    "terminal",
]
TerminalStatus = Literal[
    "succeeded",
    "validation_failed",
]


class ApplicationGraphInput(TypedDict):
    run_id: UUID
    workspace_id: str
    job_description: str
    document_ids: list[UUID]


class ApplicationGraphState(ApplicationGraphInput, total=False):
    requirements: list[Requirement]
    retrieved_evidence: list[Evidence]
    artifact: ApplicationArtifact
    validation: ArtifactValidation
    revision_count: int
    validated_revision_count: int
    node_trace: Annotated[list[NodeName], operator.add]
    terminal_status: TerminalStatus
