from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        CheckConstraint(
            "sequence >= 0",
            name="ck_run_events_sequence_non_negative",
        ),
        CheckConstraint(
            "length(trim(kind)) > 0",
            name="ck_run_events_kind_not_blank",
        ),
        UniqueConstraint(
            "run_id",
            "sequence",
            name="uq_run_events_run_id_sequence",
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
    sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    data: Mapped[dict[str, object]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
