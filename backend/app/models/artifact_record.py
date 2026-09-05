from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ArtifactRecord(Base):
    __tablename__ = "artifact_records"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            name="uq_artifact_records_run_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[dict[str, object]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )
    validation: Mapped[dict[str, object]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
