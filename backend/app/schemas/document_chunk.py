from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: str
    document_id: UUID
    position: int
    content: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)

        return value.astimezone(UTC)


class DocumentIngestionRead(BaseModel):
    document_id: UUID
    workspace_id: str
    chunk_count: int = Field(ge=0)
    chunks: list[DocumentChunkRead]
