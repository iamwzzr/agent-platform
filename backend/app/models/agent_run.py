from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db_core import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "length(trim(workspace_id)) > 0",
            name="ck_agent_runs_workspace_id_not_blank",
        ),
        CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="ck_agent_runs_idempotency_key_not_blank",
        ),
        CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_agent_runs_provider_not_blank",
        ),
        CheckConstraint(
            "length(trim(model)) > 0",
            name="ck_agent_runs_model_not_blank",
        ),
        CheckConstraint(
            "status IN "
            "('queued', 'running', 'succeeded', 'validation_failed', 'failed')",
            name="ck_agent_runs_status_valid",
        ),
        CheckConstraint(
            "revision_count >= 0",
            name="ck_agent_runs_revision_count_non_negative",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_agent_runs_attempt_count_non_negative",
        ),
        CheckConstraint(
            "(status = 'running' AND lease_expires_at IS NOT NULL "
            "AND execution_token IS NOT NULL) OR "
            "(status != 'running' AND lease_expires_at IS NULL "
            "AND execution_token IS NULL)",
            name="ck_agent_runs_execution_lease_consistent",
        ),
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_agent_runs_workspace_id_idempotency_key",
        ),
        ForeignKeyConstraint(
            ["job_id", "workspace_id"],
            ["jobs.id", "jobs.workspace_id"],
            name="fk_agent_runs_job_workspace",
            ondelete="CASCADE",
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
    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    document_ids: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="queued",
    )
    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="mock",
    )
    model: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="deterministic-mock-v1",
    )
    current_node: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    state_json: Mapped[dict[str, object]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
    )
    revision_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    retryable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    execution_token: Mapped[UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
