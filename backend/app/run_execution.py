from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.schemas.artifact import (
    ApplicationArtifact,
    ArtifactValidation,
    Evidence,
    Requirement,
)
from app.validation import validate_artifact

RunTerminalStatus = Literal["succeeded", "validation_failed"]


class InvalidRunExecutionResultError(ValueError):
    """Raised when an executor returns an inconsistent terminal result."""


class RunExecutionLeaseLostError(RuntimeError):
    """Raised when an older worker no longer owns a run execution lease."""


@dataclass(frozen=True, slots=True)
class RunExecutionResult:
    run_id: UUID
    workspace_id: str
    terminal_status: RunTerminalStatus
    artifact: ApplicationArtifact | None
    validation: ArtifactValidation
    trusted_requirements: tuple[Requirement, ...]
    retrieved_evidence: tuple[Evidence, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, UUID):
            raise InvalidRunExecutionResultError(
                "Run execution requires a valid run ID"
            )
        if not isinstance(self.workspace_id, str) or not self.workspace_id.strip():
            raise InvalidRunExecutionResultError(
                "Run execution requires a valid workspace ID"
            )
        if self.terminal_status not in ("succeeded", "validation_failed"):
            raise InvalidRunExecutionResultError(
                "Run execution returned an unsupported terminal status"
            )
        if not isinstance(self.validation, ArtifactValidation):
            raise InvalidRunExecutionResultError(
                "Run execution requires a validation result"
            )
        if not self.trusted_requirements or not all(
            isinstance(requirement, Requirement)
            for requirement in self.trusted_requirements
        ):
            raise InvalidRunExecutionResultError(
                "Run execution requires trusted requirements"
            )
        if not all(
            isinstance(evidence, Evidence) for evidence in self.retrieved_evidence
        ):
            raise InvalidRunExecutionResultError(
                "Run execution contains invalid retrieved evidence"
            )

        if self.terminal_status == "succeeded":
            if not isinstance(self.artifact, ApplicationArtifact):
                raise InvalidRunExecutionResultError(
                    "Successful run execution requires an artifact"
                )
            if self.artifact.run_id != self.run_id:
                raise InvalidRunExecutionResultError(
                    "Successful run execution artifact does not match the result"
                )
            if not self.validation.passed:
                raise InvalidRunExecutionResultError(
                    "Successful run execution requires passing validation"
                )
            expected_validation = validate_artifact(
                self.artifact,
                expected_run_id=self.run_id,
                workspace_id=self.workspace_id,
                trusted_requirements=self.trusted_requirements,
                retrieved_evidence=self.retrieved_evidence,
            )
            if self.validation != expected_validation:
                raise InvalidRunExecutionResultError(
                    "Successful run validation does not match trusted inputs"
                )
            return

        if self.artifact is not None:
            raise InvalidRunExecutionResultError(
                "Validation-failed run execution cannot publish an artifact"
            )
        if self.validation.passed:
            raise InvalidRunExecutionResultError(
                "Validation-failed run execution requires failing validation"
            )
        validation_data = self.validation.model_dump(mode="python")
        if not any(
            value for field, value in validation_data.items() if field != "passed"
        ):
            raise InvalidRunExecutionResultError(
                "Validation-failed run execution requires failure details"
            )
