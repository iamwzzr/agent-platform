from uuid import uuid4

import pytest

from app.providers import (
    AgentProvider,
    DeterministicMockProvider,
)
from app.schemas.artifact import Evidence, Requirement
from app.validation import validate_artifact


@pytest.mark.asyncio
async def test_mock_provider_builds_grounded_artifact() -> None:
    run_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()

    python_requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    kubernetes_requirement = Requirement(
        id="req-2",
        text="Operate Kubernetes workloads.",
        priority="medium",
    )

    evidence = Evidence(
        requirement_id=python_requirement.id,
        workspace_id="workspace-1",
        document_id=document_id,
        chunk_id=chunk_id,
        excerpt="Built Python FastAPI services.",
        score=1.0,
    )

    provider = DeterministicMockProvider()

    assert isinstance(provider, AgentProvider)

    first_artifact = await provider.draft_artifact(
        run_id=run_id,
        requirements=[
            python_requirement,
            kubernetes_requirement,
        ],
        evidence=[evidence],
    )
    second_artifact = await provider.draft_artifact(
        run_id=run_id,
        requirements=[
            python_requirement,
            kubernetes_requirement,
        ],
        evidence=[evidence],
    )

    assert first_artifact == second_artifact
    assert first_artifact.run_id == run_id
    assert first_artifact.claims[0].text == evidence.excerpt
    assert first_artifact.claims[0].requirement_ids == [python_requirement.id]
    assert first_artifact.citations[0].chunk_id == chunk_id
    assert first_artifact.gaps[0].requirement_id == (kubernetes_requirement.id)
    assert first_artifact.gaps[0].reason_code == ("no_grounded_evidence")
    assert first_artifact.cover_letter is None

    validation = validate_artifact(
        first_artifact,
        expected_run_id=run_id,
        workspace_id="workspace-1",
        trusted_requirements=[
            python_requirement,
            kubernetes_requirement,
        ],
        retrieved_evidence=[evidence],
    )

    assert validation.passed is True


@pytest.mark.asyncio
async def test_mock_provider_snapshots_requirement_inputs() -> None:
    original_text = "Build Python FastAPI services."
    requirement = Requirement(
        id="req-1",
        text=original_text,
        priority="high",
    )
    provider = DeterministicMockProvider()

    artifact = await provider.draft_artifact(
        run_id=uuid4(),
        requirements=[requirement],
        evidence=[],
    )

    requirement.text = "Tampered after provider execution."

    assert artifact.requirements[0].text == original_text
