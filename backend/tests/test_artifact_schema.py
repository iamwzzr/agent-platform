from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.artifact import (
    ApplicationArtifact,
    Citation,
    Claim,
    Gap,
    Requirement,
    ResumeBullet,
)


def test_application_artifact_accepts_grounded_claim() -> None:
    run_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()

    artifact = ApplicationArtifact(
        run_id=run_id,
        requirements=[
            Requirement(
                id="req-1",
                text="Build Python FastAPI services.",
                priority="high",
            )
        ],
        claims=[
            Claim(
                id="claim-1",
                text="Built Python FastAPI services.",
                requirement_ids=["req-1"],
                citation_chunk_ids=[chunk_id],
            )
        ],
        resume_bullets=[
            ResumeBullet(
                text="Built Python FastAPI services.",
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

    assert artifact.run_id == run_id
    assert artifact.claims[0].citation_chunk_ids == [chunk_id]
    assert artifact.citations[0].document_id == document_id


def test_claim_rejects_empty_citations() -> None:
    with pytest.raises(ValidationError):
        Claim(
            id="claim-1",
            text="Unsupported claim.",
            requirement_ids=["req-1"],
            citation_chunk_ids=[],
        )


@pytest.mark.parametrize("text", ["", "   "])
def test_requirement_rejects_blank_text(text: str) -> None:
    with pytest.raises(ValidationError):
        Requirement(
            id="req-1",
            text=text,
            priority="high",
        )


def test_artifact_models_reject_extra_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Requirement.model_validate(
            {
                "id": "req-1",
                "text": "Build Python services.",
                "priority": "high",
                "invented_field": "not allowed",
            }
        )

    assert exc_info.value.errors()[0]["type"] == ("extra_forbidden")


def test_gap_requires_controlled_reason_code() -> None:
    with pytest.raises(ValidationError):
        Gap(
            requirement_id="req-1",
            reason=("Candidate led 100 engineers for 10 years."),
        )

    gap = Gap(
        requirement_id="req-1",
        reason_code="no_grounded_evidence",
    )
    assert gap.reason_code == "no_grounded_evidence"

    with pytest.raises(ValidationError):
        Gap(
            requirement_id="req-1",
            reason_code="invented_narrative",
        )
