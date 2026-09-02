from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        CheckConstraint(
            "length(trim(workspace_id)) > 0",
            name="ck_document_chunks_workspace_id_not_blank",
        ),
        CheckConstraint(
            "position >= 0",
            name="ck_document_chunks_position_non_negative",
        ),
        CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_document_chunks_content_not_blank",
        ),
        UniqueConstraint(
            "document_id",
            "position",
            name="uq_document_chunks_document_id_position",
        ),
        ForeignKeyConstraint(
            ("document_id", "workspace_id"),
            ("documents.id", "documents.workspace_id"),
            name="fk_document_chunks_document_workspace",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
    )
    workspace_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
