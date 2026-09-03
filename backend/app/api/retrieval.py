from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.rag.retrieval import RetrievalDocumentNotFoundError, retrieve_chunks
from app.schemas.retrieval import RetrievalRead, RetrievalRequest

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/retrieval",
    tags=["retrieval"],
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
    response_model=RetrievalRead,
)
async def search_chunks(
    workspace_id: WorkspaceId,
    payload: RetrievalRequest,
    session: SessionDependency,
) -> RetrievalRead:
    try:
        results = await retrieve_chunks(
            session,
            workspace_id=workspace_id,
            query=payload.query,
            document_ids=payload.document_ids,
            top_k=payload.top_k,
            min_score=payload.min_score,
        )
    except RetrievalDocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        ) from exc

    return RetrievalRead(
        query=payload.query,
        count=len(results),
        results=results,
    )
