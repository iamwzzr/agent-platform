from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Count = Annotated[int, Field(ge=0)]


class OverviewConfiguration(BaseModel):
    """Public current deployment settings, not historical run configuration."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    max_revisions: int = Field(ge=0, le=5)
    provider_retry_max_attempts: int = Field(ge=1, le=5)
    provider_retry_initial_delay_seconds: float = Field(ge=0, le=60)
    retrieval_method: Literal["deterministic_sparse_cosine"]
    retrieval_top_k: Literal[5]


class OverviewUsage(BaseModel):
    """Workspace totals; published artifacts can contain only evidence gaps."""

    model_config = ConfigDict(extra="forbid")

    saved_jobs: Count = 0
    jobs_with_runs: Count = 0
    runs: Count = 0
    succeeded_runs: Count = 0
    validation_failed_runs: Count = 0
    failed_runs: Count = 0
    active_runs: Count = 0
    published_artifacts: Count = 0
    jobs_with_published_artifacts: Count = 0
    mock_runs: Count = 0
    openai_runs: Count = 0
    other_provider_runs: Count = 0
    artifacts_with_resume_bullets: Count = 0
    gap_only_artifacts: Count = 0
    resume_bullets: Count = 0
    gaps: Count = 0
    cover_letters: Count = 0


class WorkspaceOverviewRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    generated_at: datetime
    configuration: OverviewConfiguration
    usage: OverviewUsage
