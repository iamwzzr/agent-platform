from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.artifact import (
    ApplicationArtifact,
    Citation,
    Claim,
    Evidence,
    Gap,
    Requirement,
    ResumeBullet,
)
from app.validation import validate_artifact


def test_validate_artifact_rejects_forged_citation() -> None:
    document_id = uuid4()
    trusted_chunk_id = uuid4()
    forged_chunk_id = uuid4()

    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )

    trusted_evidence = Evidence(
        requirement_id=requirement.id,
        workspace_id="workspace-1",
        document_id=document_id,
        chunk_id=trusted_chunk_id,
        excerpt="Built Python FastAPI services.",
        score=1.0,
    )

    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[requirement],
        claims=[
            Claim(
                id="claim-1",
                text="Built Python FastAPI services.",
                requirement_ids=[requirement.id],
                citation_chunk_ids=[forged_chunk_id],
            )
        ],
        resume_bullets=[],
        cover_letter=None,
        gaps=[],
        citations=[
            Citation(
                document_id=document_id,
                chunk_id=forged_chunk_id,
            )
        ],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[trusted_evidence],
    )

    assert validation.passed is False
    assert validation.invalid_citation_chunk_ids == [forged_chunk_id]


def test_validate_artifact_rejects_citation_for_other_requirement() -> None:
    document_id = uuid4()
    sql_chunk_id = uuid4()

    python_requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    sql_requirement = Requirement(
        id="req-2",
        text="Administer SQL databases.",
        priority="medium",
    )

    sql_evidence = Evidence(
        requirement_id=sql_requirement.id,
        workspace_id="workspace-1",
        document_id=document_id,
        chunk_id=sql_chunk_id,
        excerpt="Administered SQL databases.",
        score=1.0,
    )

    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[
            python_requirement,
            sql_requirement,
        ],
        claims=[
            Claim(
                id="claim-1",
                text="Built Python FastAPI services.",
                requirement_ids=[python_requirement.id],
                citation_chunk_ids=[sql_chunk_id],
            )
        ],
        resume_bullets=[],
        cover_letter=None,
        gaps=[
            Gap(
                requirement_id=sql_requirement.id,
                reason_code="no_grounded_evidence",
            )
        ],
        citations=[
            Citation(
                document_id=document_id,
                chunk_id=sql_chunk_id,
            )
        ],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[
            python_requirement,
            sql_requirement,
        ],
        retrieved_evidence=[sql_evidence],
    )

    assert validation.passed is False
    assert validation.unsupported_requirement_ids == [python_requirement.id]


def test_validate_artifact_accepts_gap_without_evidence() -> None:
    requirement = Requirement(
        id="req-1",
        text="Five years of Kubernetes experience.",
        priority="high",
    )

    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[requirement],
        claims=[],
        resume_bullets=[],
        cover_letter=None,
        gaps=[
            Gap(
                requirement_id=requirement.id,
                reason_code="no_grounded_evidence",
            )
        ],
        citations=[],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[],
    )

    assert validation.passed is True


def test_validate_artifact_rejects_uncovered_requirement() -> None:
    requirement = Requirement(
        id="req-1",
        text="Five years of Kubernetes experience.",
        priority="high",
    )

    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[requirement],
        claims=[],
        resume_bullets=[],
        cover_letter=None,
        gaps=[],
        citations=[],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[],
    )

    assert validation.passed is False
    assert validation.uncovered_requirement_ids == [requirement.id]


def test_validate_artifact_rejects_claim_and_gap_conflict() -> None:
    document_id = uuid4()
    chunk_id = uuid4()

    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    evidence = Evidence(
        requirement_id=requirement.id,
        workspace_id="workspace-1",
        document_id=document_id,
        chunk_id=chunk_id,
        excerpt="Built Python FastAPI services.",
        score=1.0,
    )

    grounded_artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[requirement],
        claims=[
            Claim(
                id="claim-1",
                text="Built Python FastAPI services.",
                requirement_ids=[requirement.id],
                citation_chunk_ids=[chunk_id],
            )
        ],
        resume_bullets=[],
        cover_letter=None,
        gaps=[],
        citations=[
            Citation(
                document_id=document_id,
                chunk_id=chunk_id,
            )
        ],
    )

    grounded_validation = validate_artifact(
        grounded_artifact,
        expected_run_id=grounded_artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[evidence],
    )

    assert grounded_validation.passed is True

    conflicting_artifact = grounded_artifact.model_copy(
        update={
            "gaps": [
                Gap(
                    requirement_id=requirement.id,
                    reason_code="no_grounded_evidence",
                )
            ]
        }
    )

    conflicting_validation = validate_artifact(
        conflicting_artifact,
        expected_run_id=conflicting_artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[evidence],
    )

    assert conflicting_validation.passed is False
    assert conflicting_validation.conflicting_requirement_ids == [requirement.id]


def test_validate_artifact_rejects_removed_requirement() -> None:
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

    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[
            python_requirement,
        ],
        claims=[],
        resume_bullets=[],
        cover_letter=None,
        gaps=[
            Gap(
                requirement_id=python_requirement.id,
                reason_code="no_grounded_evidence",
            ),
            Gap(
                requirement_id=kubernetes_requirement.id,
                reason_code="no_grounded_evidence",
            ),
        ],
        citations=[],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[
            python_requirement,
            kubernetes_requirement,
        ],
        retrieved_evidence=[],
    )

    assert validation.passed is False
    assert validation.mismatched_requirement_ids == [kubernetes_requirement.id]


def test_validate_artifact_rejects_claim_text_not_supported_by_evidence() -> None:
    document_id = uuid4()
    chunk_id = uuid4()

    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    evidence = Evidence(
        requirement_id=requirement.id,
        workspace_id="workspace-1",
        document_id=document_id,
        chunk_id=chunk_id,
        excerpt="Built Python FastAPI services.",
        score=1.0,
    )

    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[requirement],
        claims=[
            Claim(
                id="claim-1",
                text="Managed a team of 50 engineers.",
                requirement_ids=[requirement.id],
                citation_chunk_ids=[chunk_id],
            )
        ],
        resume_bullets=[],
        cover_letter=None,
        gaps=[],
        citations=[
            Citation(
                document_id=document_id,
                chunk_id=chunk_id,
            )
        ],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[evidence],
    )

    assert validation.passed is False
    assert validation.unsupported_claim_ids == ["claim-1"]


def test_validate_artifact_rejects_unsupported_resume_bullet() -> None:
    document_id = uuid4()
    chunk_id = uuid4()

    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    evidence = Evidence(
        requirement_id=requirement.id,
        workspace_id="workspace-1",
        document_id=document_id,
        chunk_id=chunk_id,
        excerpt="Built Python FastAPI services.",
        score=1.0,
    )

    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[requirement],
        claims=[
            Claim(
                id="claim-1",
                text=evidence.excerpt,
                requirement_ids=[requirement.id],
                citation_chunk_ids=[chunk_id],
            )
        ],
        resume_bullets=[
            ResumeBullet(
                text="Managed a team of 50 engineers.",
                claim_ids=["claim-1"],
            )
        ],
        cover_letter=None,
        gaps=[],
        citations=[
            Citation(
                document_id=document_id,
                chunk_id=chunk_id,
            )
        ],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[evidence],
    )

    assert validation.passed is False
    assert validation.unsupported_resume_bullet_indexes == [0]


def test_validate_artifact_rejects_unvalidated_cover_letter() -> None:
    requirement = Requirement(
        id="req-1",
        text="Five years of Kubernetes experience.",
        priority="high",
    )

    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[requirement],
        claims=[],
        resume_bullets=[],
        cover_letter=("I have five years of Kubernetes experience."),
        gaps=[
            Gap(
                requirement_id=requirement.id,
                reason_code="no_grounded_evidence",
            )
        ],
        citations=[],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[],
    )

    assert validation.passed is False
    assert validation.unsupported_cover_letter is True


def test_validate_artifact_rejects_duplicate_requirement_ids() -> None:
    trusted_requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    tampered_requirement = Requirement(
        id="req-1",
        text="Administer SQL databases.",
        priority="low",
    )

    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[
            tampered_requirement,
            trusted_requirement,
        ],
        claims=[],
        resume_bullets=[],
        cover_letter=None,
        gaps=[
            Gap(
                requirement_id=trusted_requirement.id,
                reason_code="no_grounded_evidence",
            )
        ],
        citations=[],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[trusted_requirement],
        retrieved_evidence=[],
    )

    assert validation.passed is False
    assert validation.duplicate_requirement_ids == ["req-1"]


def test_validate_artifact_rejects_gap_for_unknown_requirement() -> None:
    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )

    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[requirement],
        claims=[],
        resume_bullets=[],
        cover_letter=None,
        gaps=[
            Gap(
                requirement_id=requirement.id,
                reason_code="no_grounded_evidence",
            ),
            Gap(
                requirement_id="req-forged",
                reason_code="no_grounded_evidence",
            ),
        ],
        citations=[],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[],
    )

    assert validation.passed is False
    assert validation.unknown_gap_requirement_ids == ["req-forged"]


def test_validate_artifact_rejects_duplicate_claim_ids() -> None:
    document_id = uuid4()
    first_chunk_id = uuid4()
    second_chunk_id = uuid4()

    requirement = Requirement(
        id="req-1",
        text="Build Python services.",
        priority="high",
    )
    first_evidence = Evidence(
        requirement_id=requirement.id,
        workspace_id="workspace-1",
        document_id=document_id,
        chunk_id=first_chunk_id,
        excerpt="Built FastAPI services.",
        score=1.0,
    )
    second_evidence = Evidence(
        requirement_id=requirement.id,
        workspace_id="workspace-1",
        document_id=document_id,
        chunk_id=second_chunk_id,
        excerpt="Built Django services.",
        score=1.0,
    )

    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[requirement],
        claims=[
            Claim(
                id="claim-1",
                text=first_evidence.excerpt,
                requirement_ids=[requirement.id],
                citation_chunk_ids=[first_chunk_id],
            ),
            Claim(
                id="claim-1",
                text=second_evidence.excerpt,
                requirement_ids=[requirement.id],
                citation_chunk_ids=[second_chunk_id],
            ),
        ],
        resume_bullets=[],
        cover_letter=None,
        gaps=[],
        citations=[
            Citation(
                document_id=document_id,
                chunk_id=first_chunk_id,
            ),
            Citation(
                document_id=document_id,
                chunk_id=second_chunk_id,
            ),
        ],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[
            first_evidence,
            second_evidence,
        ],
    )

    assert validation.passed is False
    assert validation.duplicate_claim_ids == ["claim-1"]


def test_validate_artifact_rejects_citation_not_supporting_claim() -> None:
    document_id = uuid4()
    supporting_chunk_id = uuid4()
    irrelevant_chunk_id = uuid4()

    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    supporting_evidence = Evidence(
        requirement_id=requirement.id,
        workspace_id="workspace-1",
        document_id=document_id,
        chunk_id=supporting_chunk_id,
        excerpt="Built Python FastAPI services.",
        score=1.0,
    )
    irrelevant_evidence = Evidence(
        requirement_id=requirement.id,
        workspace_id="workspace-1",
        document_id=document_id,
        chunk_id=irrelevant_chunk_id,
        excerpt="Administered SQL databases.",
        score=0.8,
    )

    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[requirement],
        claims=[
            Claim(
                id="claim-1",
                text=supporting_evidence.excerpt,
                requirement_ids=[requirement.id],
                citation_chunk_ids=[
                    supporting_chunk_id,
                    irrelevant_chunk_id,
                ],
            )
        ],
        resume_bullets=[],
        cover_letter=None,
        gaps=[],
        citations=[
            Citation(
                document_id=document_id,
                chunk_id=supporting_chunk_id,
            ),
            Citation(
                document_id=document_id,
                chunk_id=irrelevant_chunk_id,
            ),
        ],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[
            supporting_evidence,
            irrelevant_evidence,
        ],
    )

    assert validation.passed is False
    assert validation.unsupported_citation_chunk_ids == [irrelevant_chunk_id]


def test_validate_artifact_rejects_mismatched_run_id() -> None:
    expected_run_id = uuid4()
    unexpected_run_id = uuid4()

    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    artifact = ApplicationArtifact(
        run_id=unexpected_run_id,
        requirements=[requirement],
        claims=[],
        resume_bullets=[],
        cover_letter=None,
        gaps=[
            Gap(
                requirement_id=requirement.id,
                reason_code="no_grounded_evidence",
            )
        ],
        citations=[],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=expected_run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[],
    )

    assert validation.passed is False
    assert validation.run_id_mismatch is True


def test_validate_artifact_rejects_gap_when_evidence_exists() -> None:
    document_id = uuid4()
    chunk_id = uuid4()

    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    evidence = Evidence(
        requirement_id=requirement.id,
        workspace_id="workspace-1",
        document_id=document_id,
        chunk_id=chunk_id,
        excerpt="Built Python FastAPI services.",
        score=1.0,
    )
    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[requirement],
        claims=[],
        resume_bullets=[],
        cover_letter=None,
        gaps=[
            Gap(
                requirement_id=requirement.id,
                reason_code="no_grounded_evidence",
            )
        ],
        citations=[],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[evidence],
    )

    assert validation.passed is False
    assert validation.evidenced_gap_requirement_ids == [requirement.id]


def test_validate_artifact_rejects_bullet_with_mixed_claims() -> None:
    document_id = uuid4()
    python_chunk_id = uuid4()
    sql_chunk_id = uuid4()

    python_requirement = Requirement(
        id="req-python",
        text="Build Python services.",
        priority="high",
    )
    sql_requirement = Requirement(
        id="req-sql",
        text="Administer SQL databases.",
        priority="medium",
    )
    python_evidence = Evidence(
        requirement_id=python_requirement.id,
        workspace_id="workspace-1",
        document_id=document_id,
        chunk_id=python_chunk_id,
        excerpt="Built Python services.",
        score=1.0,
    )
    sql_evidence = Evidence(
        requirement_id=sql_requirement.id,
        workspace_id="workspace-1",
        document_id=document_id,
        chunk_id=sql_chunk_id,
        excerpt="Administered SQL databases.",
        score=1.0,
    )

    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[python_requirement, sql_requirement],
        claims=[
            Claim(
                id="claim-python",
                text=python_evidence.excerpt,
                requirement_ids=[python_requirement.id],
                citation_chunk_ids=[python_chunk_id],
            ),
            Claim(
                id="claim-sql",
                text=sql_evidence.excerpt,
                requirement_ids=[sql_requirement.id],
                citation_chunk_ids=[sql_chunk_id],
            ),
        ],
        resume_bullets=[
            ResumeBullet(
                text=python_evidence.excerpt,
                claim_ids=["claim-python", "claim-sql"],
            )
        ],
        cover_letter=None,
        gaps=[],
        citations=[
            Citation(
                document_id=document_id,
                chunk_id=python_chunk_id,
            ),
            Citation(
                document_id=document_id,
                chunk_id=sql_chunk_id,
            ),
        ],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[
            python_requirement,
            sql_requirement,
        ],
        retrieved_evidence=[
            python_evidence,
            sql_evidence,
        ],
    )

    assert validation.passed is False
    assert validation.unsupported_resume_bullet_indexes == [0]


def test_validate_artifact_revalidates_mutated_claim() -> None:
    requirement = Requirement(
        id="req-1",
        text="Operate Kubernetes workloads.",
        priority="high",
    )
    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[requirement],
        claims=[
            Claim(
                id="claim-forged",
                text="I led one hundred engineers.",
                requirement_ids=[requirement.id],
                citation_chunk_ids=[uuid4()],
            )
        ],
        resume_bullets=[],
        cover_letter=None,
        gaps=[
            Gap(
                requirement_id=requirement.id,
                reason_code="no_grounded_evidence",
            )
        ],
        citations=[],
    )

    artifact.claims[0].requirement_ids.clear()
    artifact.claims[0].citation_chunk_ids.clear()

    with pytest.raises(ValidationError):
        validate_artifact(
            artifact,
            expected_run_id=artifact.run_id,
            workspace_id="workspace-1",
            trusted_requirements=[requirement],
            retrieved_evidence=[],
        )


def test_validate_artifact_rejects_duplicate_gap_requirements() -> None:
    requirement = Requirement(
        id="req-1",
        text="Operate Kubernetes workloads.",
        priority="high",
    )
    artifact = ApplicationArtifact(
        run_id=uuid4(),
        requirements=[requirement],
        claims=[],
        resume_bullets=[],
        cover_letter=None,
        gaps=[
            Gap(
                requirement_id=requirement.id,
                reason_code="no_grounded_evidence",
            ),
            Gap(
                requirement_id=requirement.id,
                reason_code="no_grounded_evidence",
            ),
        ],
        citations=[],
    )

    validation = validate_artifact(
        artifact,
        expected_run_id=artifact.run_id,
        workspace_id="workspace-1",
        trusted_requirements=[requirement],
        retrieved_evidence=[],
    )

    assert validation.passed is False
    assert validation.duplicate_gap_requirement_ids == [requirement.id]
