from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.rag.embedding import cosine_similarity, embed_text


class RetrievalDocumentNotFoundError(Exception):
    """Raised when a requested document is not visible in the workspace."""


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    workspace_id: str
    position: int
    content: str
    score: float


def rank_chunks(
    query: str,
    chunks: Sequence[DocumentChunk],
    *,
    top_k: int = 5,
    min_score: float = 0.0,
) -> list[RetrievedChunk]:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")

    if not 0.0 <= min_score <= 1.0:
        raise ValueError("min_score must be between 0 and 1")

    query_embedding = embed_text(query)
    ranked: list[RetrievedChunk] = []

    for chunk in chunks:
        score = cosine_similarity(
            query_embedding,
            embed_text(chunk.content),
        )

        if score <= min_score:
            continue

        ranked.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                workspace_id=chunk.workspace_id,
                position=chunk.position,
                content=chunk.content,
                score=score,
            )
        )

    ranked.sort(
        key=lambda item: item.score,
        reverse=True,
    )

    return ranked[:top_k]


async def retrieve_chunks(
    session: AsyncSession,
    *,
    workspace_id: str,
    query: str,
    document_ids: Sequence[UUID] | None = None,
    top_k: int = 5,
    min_score: float = 0.0,
) -> list[RetrievedChunk]:
    if document_ids is not None and not document_ids:
        return rank_chunks(
            query,
            [],
            top_k=top_k,
            min_score=min_score,
        )

    if document_ids is not None:
        requested_document_ids = set(document_ids)

        document_result = await session.execute(
            select(Document.id).where(
                Document.workspace_id == workspace_id,
                Document.id.in_(requested_document_ids),
            )
        )
        visible_document_ids = set(
            document_result.scalars().all()
        )

        if visible_document_ids != requested_document_ids:
            raise RetrievalDocumentNotFoundError(
                "Document not found"
            )

    statement = select(DocumentChunk).where(
        DocumentChunk.workspace_id == workspace_id
    )

    if document_ids is not None:
        statement = statement.where(
            DocumentChunk.document_id.in_(document_ids)
        )

    result = await session.execute(
        statement.order_by(
            DocumentChunk.document_id,
            DocumentChunk.position,
            DocumentChunk.id,
        )
    )
    chunks = list(result.scalars().all())

    return rank_chunks(
        query,
        chunks,
        top_k=top_k,
        min_score=min_score,
    )
