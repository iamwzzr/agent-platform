from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db_core import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "length(trim(workspace_id)) > 0",
            name="ck_documents_workspace_id_not_blank",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_documents_name_not_blank",
        ),
        CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_documents_content_not_blank",
        ),
        UniqueConstraint(
            "id",
            "workspace_id",
            name="uq_documents_id_workspace_id",
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
    name: Mapped[str] = mapped_column(
        String(255),
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
