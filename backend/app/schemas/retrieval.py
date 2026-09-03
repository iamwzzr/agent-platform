from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

RetrievalQuery = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=2_000,
    ),
]


class RetrievalRequest(BaseModel):
    query: RetrievalQuery
    document_ids: list[UUID] | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )


class RetrievedChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: UUID
    document_id: UUID
    workspace_id: str
    position: int
    content: str
    score: float = Field(ge=0.0, le=1.0)


class RetrievalRead(BaseModel):
    query: str
    count: int = Field(ge=0)
    results: list[RetrievedChunkRead]
