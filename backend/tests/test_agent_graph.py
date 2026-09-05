from collections.abc import Sequence
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.agent.graph import (
    InvalidExtractedRequirementsError,
    InvalidRetrievedEvidenceError,
    build_application_graph,
)
from app.providers import DeterministicMockProvider
from app.rag.retrieval import RetrievalDocumentNotFoundError, RetrievedChunk
from app.schemas.artifact import ApplicationArtifact, Gap, Requirement


@pytest.mark.asyncio
async def test_application_graph_runs_happy_path_in_order() -> None:
    run_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()

    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    retrieved_chunk = RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        workspace_id="workspace-1",
        position=0,
        content="Built Python FastAPI services.",
        score=1.0,
    )

    async def extract_requirements(
        job_description: str,
    ) -> Sequence[Requirement]:
        assert job_description == requirement.text
        return [requirement]

    async def retrieve_chunks_for_requirement(
        *,
        workspace_id: str,
        query: str,
        document_ids: Sequence[UUID],
    ) -> Sequence[RetrievedChunk]:
        assert workspace_id == "workspace-1"
        assert query == requirement.text
        assert list(document_ids) == [document_id]
        return [retrieved_chunk]

    async def verify_retrieved_chunk(
        *,
        requirement: Requirement,
        chunk: RetrievedChunk,
    ) -> str | None:
        assert requirement.id == "req-1"
        assert chunk == retrieved_chunk
        return chunk.content

    graph = build_application_graph(
        provider=DeterministicMockProvider(),
        extract_requirements=extract_requirements,
        retrieve_chunks_for_requirement=retrieve_chunks_for_requirement,
        verify_retrieved_chunk=verify_retrieved_chunk,
    )

    result = await graph.ainvoke(
        {
            "run_id": run_id,
            "workspace_id": "workspace-1",
            "job_description": requirement.text,
            "document_ids": [document_id],
        }
    )

    assert result["node_trace"] == [
        "extract",
        "retrieve",
        "draft",
        "validate",
        "terminal",
    ]
    assert result["terminal_status"] == "succeeded"
    assert result["requirements"] == [requirement]
    assert result["retrieved_evidence"][0].requirement_id == requirement.id
    assert result["retrieved_evidence"][0].chunk_id == chunk_id
    assert result["artifact"].run_id == run_id
    assert result["validation"].passed is True


@pytest.mark.asyncio
async def test_graph_rejects_duplicate_requirement_ids_before_retrieval() -> None:
    extract_requirements = AsyncMock(
        return_value=[
            Requirement(
                id="req-1",
                text="Build Python FastAPI services.",
                priority="high",
            ),
            Requirement(
                id="req-1",
                text="Build TypeScript React interfaces.",
                priority="medium",
            ),
        ]
    )
    retrieve_chunks_for_requirement = AsyncMock(
        side_effect=AssertionError(
            "retrieval ran before duplicate requirement IDs were rejected"
        )
    )

    graph = build_application_graph(
        provider=DeterministicMockProvider(),
        extract_requirements=extract_requirements,
        retrieve_chunks_for_requirement=retrieve_chunks_for_requirement,
        verify_retrieved_chunk=AsyncMock(),
    )

    with pytest.raises(
        InvalidExtractedRequirementsError,
        match=r"Duplicate extracted requirement IDs: req-1",
    ):
        await graph.ainvoke(
            {
                "run_id": uuid4(),
                "workspace_id": "workspace-1",
                "job_description": "Build a web application.",
                "document_ids": [uuid4()],
            }
        )

    retrieve_chunks_for_requirement.assert_not_awaited()


@pytest.mark.asyncio
async def test_graph_revises_failed_draft_once_then_succeeds() -> None:
    run_id = uuid4()
    requirement = Requirement(
        id="req-1",
        text="Five years of Kubernetes experience.",
        priority="high",
    )
    initial_artifact = ApplicationArtifact(
        run_id=run_id,
        requirements=[requirement],
        claims=[],
        resume_bullets=[],
        cover_letter=None,
        gaps=[],
        citations=[],
    )
    revised_artifact = initial_artifact.model_copy(
        update={
            "gaps": [
                Gap(
                    requirement_id=requirement.id,
                    reason_code="no_grounded_evidence",
                )
            ]
        },
        deep=True,
    )
    provider = DeterministicMockProvider()
    provider.draft_artifact = AsyncMock(return_value=initial_artifact)
    provider.revise_artifact = AsyncMock(return_value=revised_artifact)

    graph = build_application_graph(
        provider=provider,
        extract_requirements=AsyncMock(return_value=[requirement]),
        retrieve_chunks_for_requirement=AsyncMock(return_value=[]),
        verify_retrieved_chunk=AsyncMock(),
        max_revisions=1,
    )

    result = await graph.ainvoke(
        {
            "run_id": run_id,
            "workspace_id": "workspace-1",
            "job_description": requirement.text,
            "document_ids": [uuid4()],
        }
    )

    assert result["node_trace"] == [
        "extract",
        "retrieve",
        "draft",
        "validate",
        "revise",
        "validate",
        "terminal",
    ]
    assert result["revision_count"] == 1
    assert result["terminal_status"] == "succeeded"
    assert result["validation"].passed is True

    provider.draft_artifact.assert_awaited_once()
    provider.revise_artifact.assert_awaited_once()

    revise_inputs = provider.revise_artifact.await_args.kwargs
    assert revise_inputs["run_id"] == run_id
    assert revise_inputs["artifact"] == initial_artifact
    assert revise_inputs["validation"].passed is False
    assert revise_inputs["requirements"] == [requirement]
    assert revise_inputs["evidence"] == []


@pytest.mark.asyncio
async def test_graph_stops_after_revision_budget_is_exhausted() -> None:
    run_id = uuid4()
    requirement = Requirement(
        id="req-1",
        text="Five years of Kubernetes experience.",
        priority="high",
    )
    invalid_artifact = ApplicationArtifact(
        run_id=run_id,
        requirements=[requirement],
        claims=[],
        resume_bullets=[],
        cover_letter=None,
        gaps=[],
        citations=[],
    )
    provider = DeterministicMockProvider()
    provider.draft_artifact = AsyncMock(return_value=invalid_artifact)
    provider.revise_artifact = AsyncMock(return_value=invalid_artifact)

    graph = build_application_graph(
        provider=provider,
        extract_requirements=AsyncMock(return_value=[requirement]),
        retrieve_chunks_for_requirement=AsyncMock(return_value=[]),
        verify_retrieved_chunk=AsyncMock(),
        max_revisions=2,
    )

    result = await graph.ainvoke(
        {
            "run_id": run_id,
            "workspace_id": "workspace-1",
            "job_description": requirement.text,
            "document_ids": [uuid4()],
        }
    )

    assert result["node_trace"] == [
        "extract",
        "retrieve",
        "draft",
        "validate",
        "revise",
        "validate",
        "revise",
        "validate",
        "terminal",
    ]
    assert result["revision_count"] == 2
    assert result["terminal_status"] == "validation_failed"
    assert result["validation"].passed is False
    assert result["validation"].uncovered_requirement_ids == [requirement.id]

    provider.draft_artifact.assert_awaited_once()
    assert provider.revise_artifact.await_count == 2


@pytest.mark.asyncio
async def test_graph_rejects_empty_requirement_batch_before_draft() -> None:
    provider = DeterministicMockProvider()
    provider.draft_artifact = AsyncMock(
        side_effect=AssertionError(
            "draft ran before empty requirement batch was rejected"
        )
    )
    retrieve_chunks_for_requirement = AsyncMock()

    graph = build_application_graph(
        provider=provider,
        extract_requirements=AsyncMock(return_value=[]),
        retrieve_chunks_for_requirement=retrieve_chunks_for_requirement,
        verify_retrieved_chunk=AsyncMock(),
    )

    with pytest.raises(
        InvalidExtractedRequirementsError,
        match="No requirements were extracted",
    ):
        await graph.ainvoke(
            {
                "run_id": uuid4(),
                "workspace_id": "workspace-1",
                "job_description": "Build a web application.",
                "document_ids": [uuid4()],
            }
        )

    retrieve_chunks_for_requirement.assert_not_awaited()
    provider.draft_artifact.assert_not_awaited()


@pytest.mark.asyncio
async def test_graph_propagates_retrieval_failure_before_provider() -> None:
    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    retrieval_failure = RetrievalDocumentNotFoundError("Document not found")
    provider = DeterministicMockProvider()
    provider.draft_artifact = AsyncMock()
    provider.revise_artifact = AsyncMock()
    verify_retrieved_chunk = AsyncMock()

    graph = build_application_graph(
        provider=provider,
        extract_requirements=AsyncMock(return_value=[requirement]),
        retrieve_chunks_for_requirement=AsyncMock(side_effect=retrieval_failure),
        verify_retrieved_chunk=verify_retrieved_chunk,
    )

    with pytest.raises(
        RetrievalDocumentNotFoundError,
        match="Document not found",
    ) as exc_info:
        await graph.ainvoke(
            {
                "run_id": uuid4(),
                "workspace_id": "workspace-1",
                "job_description": requirement.text,
                "document_ids": [uuid4()],
            }
        )

    assert exc_info.value is retrieval_failure
    verify_retrieved_chunk.assert_not_awaited()
    provider.draft_artifact.assert_not_awaited()
    provider.revise_artifact.assert_not_awaited()


@pytest.mark.asyncio
async def test_graph_does_not_treat_provider_failure_as_validation_failure() -> None:
    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    provider_failure = RuntimeError("Provider unavailable")
    provider = DeterministicMockProvider()
    provider.draft_artifact = AsyncMock(side_effect=provider_failure)
    provider.revise_artifact = AsyncMock()

    graph = build_application_graph(
        provider=provider,
        extract_requirements=AsyncMock(return_value=[requirement]),
        retrieve_chunks_for_requirement=AsyncMock(return_value=[]),
        verify_retrieved_chunk=AsyncMock(),
    )

    with pytest.raises(
        RuntimeError,
        match="Provider unavailable",
    ) as exc_info:
        await graph.ainvoke(
            {
                "run_id": uuid4(),
                "workspace_id": "workspace-1",
                "job_description": requirement.text,
                "document_ids": [uuid4()],
            }
        )

    assert exc_info.value is provider_failure
    provider.draft_artifact.assert_awaited_once()
    provider.revise_artifact.assert_not_awaited()


@pytest.mark.asyncio
async def test_graph_reuses_persisted_requirements_and_evidence_on_resume() -> None:
    run_id = uuid4()
    document_id = uuid4()
    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    provider = DeterministicMockProvider()
    extract_requirements = AsyncMock()
    retrieve_chunks_for_requirement = AsyncMock()

    graph = build_application_graph(
        provider=provider,
        extract_requirements=extract_requirements,
        retrieve_chunks_for_requirement=retrieve_chunks_for_requirement,
        verify_retrieved_chunk=AsyncMock(),
    )

    result = await graph.ainvoke(
        {
            "run_id": run_id,
            "workspace_id": "workspace-1",
            "job_description": requirement.text,
            "document_ids": [document_id],
            "requirements": [requirement],
            "retrieved_evidence": [],
            "node_trace": ["extract", "retrieve"],
        }
    )

    extract_requirements.assert_not_awaited()
    retrieve_chunks_for_requirement.assert_not_awaited()
    assert result["node_trace"] == [
        "extract",
        "retrieve",
        "draft",
        "validate",
        "terminal",
    ]
    assert result["terminal_status"] == "succeeded"


@pytest.mark.asyncio
async def test_graph_rejects_retrieval_outside_the_trusted_scope() -> None:
    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    document_id = uuid4()
    verifier = AsyncMock()
    graph = build_application_graph(
        provider=DeterministicMockProvider(),
        extract_requirements=AsyncMock(return_value=[requirement]),
        retrieve_chunks_for_requirement=AsyncMock(
            return_value=[
                RetrievedChunk(
                    chunk_id=uuid4(),
                    document_id=document_id,
                    workspace_id="workspace-2",
                    position=0,
                    content="Built Python FastAPI services.",
                    score=1.0,
                )
            ]
        ),
        verify_retrieved_chunk=verifier,
    )

    with pytest.raises(
        InvalidRetrievedEvidenceError,
        match="outside the workflow scope",
    ):
        await graph.ainvoke(
            {
                "run_id": uuid4(),
                "workspace_id": "workspace-1",
                "job_description": requirement.text,
                "document_ids": [document_id],
            }
        )

    verifier.assert_not_awaited()


@pytest.mark.asyncio
async def test_graph_rejects_a_verified_excerpt_not_present_in_its_chunk() -> None:
    requirement = Requirement(
        id="req-1",
        text="Build Python FastAPI services.",
        priority="high",
    )
    document_id = uuid4()
    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        workspace_id="workspace-1",
        position=0,
        content="Built Python FastAPI services.",
        score=1.0,
    )
    graph = build_application_graph(
        provider=DeterministicMockProvider(),
        extract_requirements=AsyncMock(return_value=[requirement]),
        retrieve_chunks_for_requirement=AsyncMock(return_value=[chunk]),
        verify_retrieved_chunk=AsyncMock(return_value="invented excerpt"),
    )

    with pytest.raises(
        InvalidRetrievedEvidenceError,
        match="not present in the retrieved chunk",
    ):
        await graph.ainvoke(
            {
                "run_id": uuid4(),
                "workspace_id": "workspace-1",
                "job_description": requirement.text,
                "document_ids": [document_id],
            }
        )
