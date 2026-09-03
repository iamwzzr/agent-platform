from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.rag.chunking import split_text


class DocumentNotFoundError(Exception):
    """Raised when a document is not visible in the requested workspace."""


class DocumentIngestionConflictError(Exception):
    """Raised when stored chunks differ from the requested ingestion."""


async def ingest_document(
    session: AsyncSession,
    *,
    workspace_id: str,
    document_id: UUID,
    chunk_size_words: int = 120,
    overlap_words: int = 20,
) -> list[DocumentChunk]:
    result = await session.execute(
        select(Document).where(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
        )
    )
    document = result.scalar_one_or_none()

    if document is None:
        raise DocumentNotFoundError("Document not found")

    chunk_contents = split_text(
        document.content,
        chunk_size_words=chunk_size_words,
        overlap_words=overlap_words,
    )

    existing_result = await session.execute(
        select(DocumentChunk)
        .where(
            DocumentChunk.document_id == document.id,
            DocumentChunk.workspace_id == document.workspace_id,
        )
        .order_by(DocumentChunk.position)
    )
    existing_chunks = list(existing_result.scalars().all())

    expected_pairs = list(enumerate(chunk_contents))
    existing_pairs = [(chunk.position, chunk.content) for chunk in existing_chunks]

    if existing_pairs == expected_pairs:
        return existing_chunks

    if existing_chunks:
        raise DocumentIngestionConflictError(
            "Stored chunks conflict with requested ingestion"
        )

    chunks = [
        DocumentChunk(
            workspace_id=document.workspace_id,
            document_id=document.id,
            position=position,
            content=content,
        )
        for position, content in enumerate(chunk_contents)
    ]

    session.add_all(chunks)
    await session.flush()

    return chunks
