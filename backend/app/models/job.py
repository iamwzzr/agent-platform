from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db_core import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "length(trim(workspace_id)) > 0",
            name="ck_jobs_workspace_id_not_blank",
        ),
        CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_jobs_title_not_blank",
        ),
        CheckConstraint(
            "length(trim(description)) > 0",
            name="ck_jobs_description_not_blank",
        ),
        Index(
            "uq_jobs_id_workspace_id",
            "id",
            "workspace_id",
            unique=True,
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
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
