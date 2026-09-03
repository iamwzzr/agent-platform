from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.document import Document
from app.rag.ingestion import (
    DocumentIngestionConflictError,
    DocumentNotFoundError,
    ingest_document,
)
from app.schemas.document import DocumentCreate, DocumentRead
from app.schemas.document_chunk import DocumentIngestionRead

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/documents",
    tags=["documents"],
)

SessionDependency = Annotated[
    AsyncSession,
    Depends(get_session),
]

WorkspaceId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    ),
]


@router.post(
    "",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    workspace_id: WorkspaceId,
    payload: DocumentCreate,
    session: SessionDependency,
) -> Document:
    document = Document(
        workspace_id=workspace_id,
        name=payload.name,
        content=payload.content,
    )

    session.add(document)
    await session.commit()
    await session.refresh(document)

    return document


@router.get(
    "/{document_id}",
    response_model=DocumentRead,
)
async def get_document(
    workspace_id: WorkspaceId,
    document_id: UUID,
    session: SessionDependency,
) -> Document:
    result = await session.execute(
        select(Document).where(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
        )
    )
    document = result.scalar_one_or_none()

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return document


@router.post(
    "/{document_id}/ingest",
    response_model=DocumentIngestionRead,
)
async def ingest_saved_document(
    workspace_id: WorkspaceId,
    document_id: UUID,
    session: SessionDependency,
) -> DocumentIngestionRead:
    try:
        chunks = await ingest_document(
            session,
            workspace_id=workspace_id,
            document_id=document_id,
        )
        await session.commit()
    except DocumentNotFoundError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        ) from exc
    except DocumentIngestionConflictError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document ingestion conflict",
        ) from exc

    return DocumentIngestionRead(
        document_id=document_id,
        workspace_id=workspace_id,
        chunk_count=len(chunks),
        chunks=chunks,
    )
