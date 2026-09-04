from collections import Counter
from collections.abc import Sequence
from uuid import UUID

from app.schemas.artifact import (
    ApplicationArtifact,
    ArtifactValidation,
    Evidence,
    Requirement,
)


def validate_artifact(
    artifact: ApplicationArtifact,
    *,
    expected_run_id: UUID,
    workspace_id: str,
    trusted_requirements: Sequence[Requirement],
    retrieved_evidence: Sequence[Evidence],
) -> ArtifactValidation:
    artifact = ApplicationArtifact.model_validate(artifact.model_dump(mode="python"))
    run_id_mismatch = artifact.run_id != expected_run_id

    trusted_requirement_id_counts = Counter(
        requirement.id for requirement in trusted_requirements
    )
    artifact_requirement_id_counts = Counter(
        requirement.id for requirement in artifact.requirements
    )

    duplicate_requirement_ids = {
        requirement_id
        for requirement_id, count in trusted_requirement_id_counts.items()
        if count > 1
    } | {
        requirement_id
        for requirement_id, count in artifact_requirement_id_counts.items()
        if count > 1
    }
    trusted_requirements_by_id = {
        requirement.id: requirement for requirement in trusted_requirements
    }
    artifact_requirements_by_id = {
        requirement.id: requirement for requirement in artifact.requirements
    }

    trusted_requirement_ids = set(trusted_requirements_by_id)
    all_requirement_ids = trusted_requirement_ids | set(artifact_requirements_by_id)

    mismatched_requirement_ids = {
        requirement_id
        for requirement_id in all_requirement_ids
        if trusted_requirements_by_id.get(requirement_id)
        != artifact_requirements_by_id.get(requirement_id)
    }

    trusted_evidence_by_key = {
        (
            evidence.requirement_id,
            evidence.document_id,
            evidence.chunk_id,
        ): evidence
        for evidence in retrieved_evidence
        if (
            evidence.workspace_id == workspace_id
            and evidence.requirement_id in trusted_requirement_ids
        )
    }
    trusted_evidence_keys = set(trusted_evidence_by_key)

    evidenced_requirement_ids = {
        requirement_id for requirement_id, _, _ in trusted_evidence_keys
    }

    trusted_citation_pairs = {
        (document_id, chunk_id) for _, document_id, chunk_id in trusted_evidence_keys
    }

    invalid_chunk_ids: set[UUID] = set()
    valid_declared_citations: dict[UUID, UUID] = {}
    unsupported_citation_chunk_ids: set[UUID] = set()

    for citation in artifact.citations:
        citation_pair = (
            citation.document_id,
            citation.chunk_id,
        )

        if citation_pair in trusted_citation_pairs:
            valid_declared_citations[citation.chunk_id] = citation.document_id
        else:
            invalid_chunk_ids.add(citation.chunk_id)

    supported_requirement_ids: set[str] = set()
    unsupported_requirement_ids: set[str] = set()
    unsupported_claim_ids: set[str] = set()

    for claim in artifact.claims:
        claim_is_supported = True

        for chunk_id in claim.citation_chunk_ids:
            if chunk_id not in valid_declared_citations:
                invalid_chunk_ids.add(chunk_id)
                continue

            document_id = valid_declared_citations[chunk_id]
            citation_evidence = [
                trusted_evidence_by_key.get(
                    (
                        requirement_id,
                        document_id,
                        chunk_id,
                    )
                )
                for requirement_id in claim.requirement_ids
            ]

            citation_supports_claim = any(
                evidence is not None and evidence.excerpt == claim.text
                for evidence in citation_evidence
            )

            if not citation_supports_claim:
                unsupported_citation_chunk_ids.add(chunk_id)

        for requirement_id in claim.requirement_ids:
            has_support = any(
                trusted_evidence_by_key.get(
                    (
                        requirement_id,
                        valid_declared_citations[chunk_id],
                        chunk_id,
                    )
                )
                is not None
                and trusted_evidence_by_key[
                    (
                        requirement_id,
                        valid_declared_citations[chunk_id],
                        chunk_id,
                    )
                ].excerpt
                == claim.text
                for chunk_id in claim.citation_chunk_ids
                if chunk_id in valid_declared_citations
            )

            if has_support:
                supported_requirement_ids.add(requirement_id)
            else:
                unsupported_requirement_ids.add(requirement_id)
                claim_is_supported = False

        if not claim_is_supported:
            unsupported_claim_ids.add(claim.id)

    claim_id_counts = Counter(claim.id for claim in artifact.claims)
    duplicate_claim_ids = {
        claim_id for claim_id, count in claim_id_counts.items() if count > 1
    }

    claims_by_id = {claim.id: claim for claim in artifact.claims}
    unsupported_resume_bullet_indexes: list[int] = []

    for index, bullet in enumerate(artifact.resume_bullets):
        referenced_claims = [
            claims_by_id.get(claim_id) for claim_id in bullet.claim_ids
        ]

        references_are_valid = all(
            claim is not None
            and claim.id not in unsupported_claim_ids
            and all(
                chunk_id in valid_declared_citations
                for chunk_id in claim.citation_chunk_ids
            )
            for claim in referenced_claims
        )
        text_is_supported = all(
            claim is not None and claim.text == bullet.text
            for claim in referenced_claims
        )

        if not references_are_valid or not text_is_supported:
            unsupported_resume_bullet_indexes.append(index)

    gap_requirement_id_counts = Counter(gap.requirement_id for gap in artifact.gaps)

    duplicate_gap_requirement_ids = {
        requirement_id
        for requirement_id, count in gap_requirement_id_counts.items()
        if count > 1
    }
    all_gap_requirement_ids = set(gap_requirement_id_counts)

    gapped_requirement_ids = all_gap_requirement_ids & trusted_requirement_ids
    unknown_gap_requirement_ids = all_gap_requirement_ids - trusted_requirement_ids
    evidenced_gap_requirement_ids = gapped_requirement_ids & evidenced_requirement_ids

    conflicting_requirement_ids = supported_requirement_ids & gapped_requirement_ids

    uncovered_requirement_ids = (
        trusted_requirement_ids - supported_requirement_ids - gapped_requirement_ids
    )

    sorted_unsupported_claim_ids = sorted(unsupported_claim_ids)
    sorted_invalid_ids = sorted(
        invalid_chunk_ids,
        key=str,
    )
    sorted_unsupported_ids = sorted(unsupported_requirement_ids)
    sorted_uncovered_ids = sorted(uncovered_requirement_ids)
    sorted_conflicting_ids = sorted(conflicting_requirement_ids)
    sorted_mismatched_ids = sorted(mismatched_requirement_ids)
    sorted_duplicate_requirement_ids = sorted(duplicate_requirement_ids)
    sorted_duplicate_gap_requirement_ids = sorted(duplicate_gap_requirement_ids)
    sorted_unknown_gap_requirement_ids = sorted(unknown_gap_requirement_ids)
    sorted_evidenced_gap_requirement_ids = sorted(evidenced_gap_requirement_ids)
    sorted_duplicate_claim_ids = sorted(duplicate_claim_ids)
    sorted_unsupported_citation_chunk_ids = sorted(
        unsupported_citation_chunk_ids,
        key=str,
    )
    unsupported_cover_letter = artifact.cover_letter is not None

    return ArtifactValidation(
        passed=(
            not sorted_invalid_ids
            and not sorted_unsupported_ids
            and not sorted_uncovered_ids
            and not sorted_conflicting_ids
            and not sorted_mismatched_ids
            and not sorted_unsupported_claim_ids
            and not unsupported_resume_bullet_indexes
            and not unsupported_cover_letter
            and not sorted_duplicate_requirement_ids
            and not sorted_unknown_gap_requirement_ids
            and not sorted_duplicate_claim_ids
            and not sorted_unsupported_citation_chunk_ids
            and not run_id_mismatch
            and not sorted_evidenced_gap_requirement_ids
            and not sorted_duplicate_gap_requirement_ids
        ),
        invalid_citation_chunk_ids=sorted_invalid_ids,
        unsupported_requirement_ids=(sorted_unsupported_ids),
        uncovered_requirement_ids=(sorted_uncovered_ids),
        conflicting_requirement_ids=(sorted_conflicting_ids),
        mismatched_requirement_ids=(sorted_mismatched_ids),
        unsupported_claim_ids=sorted_unsupported_claim_ids,
        unsupported_resume_bullet_indexes=(unsupported_resume_bullet_indexes),
        unsupported_cover_letter=unsupported_cover_letter,
        duplicate_requirement_ids=(sorted_duplicate_requirement_ids),
        unknown_gap_requirement_ids=(sorted_unknown_gap_requirement_ids),
        evidenced_gap_requirement_ids=(sorted_evidenced_gap_requirement_ids),
        duplicate_claim_ids=sorted_duplicate_claim_ids,
        unsupported_citation_chunk_ids=(sorted_unsupported_citation_chunk_ids),
        run_id_mismatch=run_id_mismatch,
        duplicate_gap_requirement_ids=(sorted_duplicate_gap_requirement_ids),
    )
