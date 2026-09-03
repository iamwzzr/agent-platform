from uuid import uuid4

import pytest

from app.models.document_chunk import DocumentChunk
from app.rag.retrieval import rank_chunks


def test_rank_chunks_orders_results_and_keeps_sources() -> None:
    partial_document_id = uuid4()
    relevant_document_id = uuid4()

    chunks = [
        DocumentChunk(
            id=uuid4(),
            workspace_id="workspace-1",
            document_id=partial_document_id,
            position=0,
            content="Python data analysis",
        ),
        DocumentChunk(
            id=uuid4(),
            workspace_id="workspace-1",
            document_id=relevant_document_id,
            position=1,
            content="Built Python FastAPI services",
        ),
        DocumentChunk(
            id=uuid4(),
            workspace_id="workspace-1",
            document_id=uuid4(),
            position=0,
            content="Java database administration",
        ),
    ]

    ranked = rank_chunks(
        "Python FastAPI",
        chunks,
        top_k=5,
    )

    assert [item.chunk_id for item in ranked] == [
        chunks[1].id,
        chunks[0].id,
    ]
    assert ranked[0].document_id == relevant_document_id
    assert ranked[0].workspace_id == "workspace-1"
    assert ranked[0].position == 1
    assert ranked[0].content == "Built Python FastAPI services"
    assert ranked[0].score > ranked[1].score > 0.0


def test_rank_chunks_applies_top_k_and_preserves_tie_order() -> None:
    first = DocumentChunk(
        id=uuid4(),
        workspace_id="workspace-1",
        document_id=uuid4(),
        position=0,
        content="Python API",
    )
    second = DocumentChunk(
        id=uuid4(),
        workspace_id="workspace-1",
        document_id=uuid4(),
        position=1,
        content="Python web",
    )

    ranked = rank_chunks(
        "Python",
        [first, second],
        top_k=1,
    )

    assert [item.chunk_id for item in ranked] == [first.id]


def test_rank_chunks_filters_weak_matches() -> None:
    weak_match = DocumentChunk(
        id=uuid4(),
        workspace_id="workspace-1",
        document_id=uuid4(),
        position=0,
        content="Python marketing sales operations",
    )

    ranked = rank_chunks(
        "Python FastAPI",
        [weak_match],
        min_score=0.5,
    )

    assert ranked == []


@pytest.mark.parametrize("top_k", [0, -1])
def test_rank_chunks_rejects_invalid_top_k(top_k: int) -> None:
    with pytest.raises(ValueError, match="top_k"):
        rank_chunks(
            "Python",
            [],
            top_k=top_k,
        )


@pytest.mark.parametrize("min_score", [-0.01, 1.01])
def test_rank_chunks_rejects_invalid_min_score(
    min_score: float,
) -> None:
    with pytest.raises(ValueError, match="min_score"):
        rank_chunks(
            "Python",
            [],
            min_score=min_score,
        )
