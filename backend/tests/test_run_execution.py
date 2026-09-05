from uuid import UUID, uuid4

import pytest

from app.run_execution import (
    InvalidRunExecutionResultError,
    RunExecutionResult,
    RunTerminalStatus,
)
from app.schemas.artifact import (
    ApplicationArtifact,
    ArtifactValidation,
    Gap,
    Requirement,
)


def _valid_artifact(run_id: UUID) -> ApplicationArtifact:
    requirement = Requirement(
        id="req-1",
        text="Five years of Kubernetes experience.",
        priority="high",
    )
    return ApplicationArtifact(
        run_id=run_id,
        requirements=[requirement],
        gaps=[
            Gap(
                requirement_id=requirement.id,
                reason_code="no_grounded_evidence",
            )
        ],
    )


def _trusted_requirements() -> tuple[Requirement, ...]:
    return tuple(_valid_artifact(uuid4()).requirements)


def test_run_execution_result_accepts_success_with_validated_artifact() -> None:
    artifact = _valid_artifact(uuid4())
    validation = ArtifactValidation(passed=True)

    result = RunExecutionResult(
        run_id=artifact.run_id,
        workspace_id="workspace-1",
        terminal_status="succeeded",
        artifact=artifact,
        validation=validation,
        trusted_requirements=tuple(artifact.requirements),
        retrieved_evidence=(),
    )

    assert result.run_id == artifact.run_id
    assert result.artifact is artifact
    assert result.validation is validation


def test_run_execution_result_accepts_validation_failure_without_artifact() -> None:
    run_id = uuid4()
    validation = ArtifactValidation(
        passed=False,
        uncovered_requirement_ids=["req-1"],
    )

    result = RunExecutionResult(
        run_id=run_id,
        workspace_id="workspace-1",
        terminal_status="validation_failed",
        artifact=None,
        validation=validation,
        trusted_requirements=_trusted_requirements(),
        retrieved_evidence=(),
    )

    assert result.run_id == run_id
    assert result.artifact is None
    assert result.validation is validation


@pytest.mark.parametrize(
    ("terminal_status", "artifact", "validation", "expected_message"),
    [
        (
            "succeeded",
            None,
            ArtifactValidation(passed=True),
            "Successful run execution requires an artifact",
        ),
        (
            "succeeded",
            _valid_artifact(uuid4()),
            ArtifactValidation(passed=False),
            "Successful run execution requires passing validation",
        ),
        (
            "validation_failed",
            _valid_artifact(uuid4()),
            ArtifactValidation(passed=False),
            "Validation-failed run execution cannot publish an artifact",
        ),
        (
            "validation_failed",
            None,
            ArtifactValidation(passed=True),
            "Validation-failed run execution requires failing validation",
        ),
        (
            "paused",
            None,
            ArtifactValidation(passed=False),
            "Run execution returned an unsupported terminal status",
        ),
    ],
)
def test_run_execution_result_rejects_inconsistent_values(
    terminal_status: str,
    artifact: ApplicationArtifact | None,
    validation: ArtifactValidation,
    expected_message: str,
) -> None:
    with pytest.raises(InvalidRunExecutionResultError, match=expected_message):
        RunExecutionResult(
            run_id=artifact.run_id if artifact is not None else uuid4(),
            workspace_id="workspace-1",
            terminal_status=terminal_status,  # type: ignore[arg-type]
            artifact=artifact,
            validation=validation,
            trusted_requirements=(
                tuple(artifact.requirements)
                if artifact is not None
                else _trusted_requirements()
            ),
            retrieved_evidence=(),
        )


def test_run_execution_result_rejects_artifact_for_another_result() -> None:
    run_id = uuid4()

    with pytest.raises(
        InvalidRunExecutionResultError,
        match="Successful run execution artifact does not match the result",
    ):
        RunExecutionResult(
            run_id=run_id,
            workspace_id="workspace-1",
            terminal_status="succeeded",
            artifact=_valid_artifact(UUID(int=run_id.int ^ 1)),
            validation=ArtifactValidation(passed=True),
            trusted_requirements=_trusted_requirements(),
            retrieved_evidence=(),
        )


def test_run_execution_result_rejects_unvalidated_dynamic_values() -> None:
    with pytest.raises(
        InvalidRunExecutionResultError,
        match="Run execution requires a valid run ID",
    ):
        RunExecutionResult(
            run_id=str(uuid4()),  # type: ignore[arg-type]
            workspace_id="workspace-1",
            terminal_status="validation_failed",
            artifact=None,
            validation=ArtifactValidation(passed=False),
            trusted_requirements=_trusted_requirements(),
            retrieved_evidence=(),
        )

    with pytest.raises(
        InvalidRunExecutionResultError,
        match="Run execution requires a validation result",
    ):
        RunExecutionResult(
            run_id=uuid4(),
            workspace_id="workspace-1",
            terminal_status="validation_failed",
            artifact=None,
            validation=None,  # type: ignore[arg-type]
            trusted_requirements=_trusted_requirements(),
            retrieved_evidence=(),
        )

    with pytest.raises(
        InvalidRunExecutionResultError,
        match="Successful run execution requires an artifact",
    ):
        RunExecutionResult(
            run_id=uuid4(),
            workspace_id="workspace-1",
            terminal_status="succeeded",
            artifact={"run_id": str(uuid4())},  # type: ignore[arg-type]
            validation=ArtifactValidation(passed=True),
            trusted_requirements=_trusted_requirements(),
            retrieved_evidence=(),
        )


def test_run_terminal_status_type_lists_only_controlled_graph_outcomes() -> None:
    statuses: tuple[RunTerminalStatus, ...] = (
        "succeeded",
        "validation_failed",
    )

    assert statuses == ("succeeded", "validation_failed")
