import re
from collections.abc import Sequence
from inspect import isawaitable
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.graph import (
    InvalidRetrievedEvidenceError,
    RequirementChunkRetriever,
    RequirementExtractor,
    RetrievedChunkVerifier,
    build_application_graph,
)
from app.agent.state import ApplicationGraphState, NodeName
from app.models.agent_run import AgentRun
from app.models.document_chunk import DocumentChunk
from app.models.job import Job
from app.models.run_event import RunEvent
from app.openai_provider import ProviderConfigurationError
from app.providers import AgentProvider, ProviderRetry
from app.rag.retrieval import RetrievedChunk, retrieve_chunks
from app.run_execution import (
    InvalidRunExecutionResultError,
    RunExecutionLeaseLostError,
    RunExecutionResult,
)
from app.schemas.artifact import (
    ApplicationArtifact,
    ArtifactValidation,
    Evidence,
    Requirement,
)

_CHECKPOINT_KEYS = frozenset(
    {
        "requirements",
        "retrieved_evidence",
        "artifact",
        "validation",
        "revision_count",
        "validated_revision_count",
        "node_trace",
        "terminal_status",
    }
)


class RunExecutorConfigurationError(ProviderConfigurationError):
    """Raised when a persisted run cannot be executed by this executor."""


async def extract_requirements_deterministically(
    job_description: str,
) -> Sequence[Requirement]:
    """Create stable requirement records without making another paid model call."""
    candidates = [
        candidate.strip()
        for candidate in re.split(r"(?:\n+|(?<=[.!?])\s+)", job_description)
        if candidate.strip()
    ]
    fragments = [
        candidate[offset : offset + 800]
        for candidate in candidates
        for offset in range(0, len(candidate), 800)
    ][:20]
    return [
        Requirement(
            id=f"req-{index}",
            text=fragment,
            priority="high" if index == 1 else "medium",
        )
        for index, fragment in enumerate(fragments, start=1)
    ]


class ApplicationGraphRunExecutor:
    """Execute the application graph while durably saving completed nodes."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        provider: AgentProvider,
        extract_requirements: RequirementExtractor | None = None,
        retrieve_chunks_for_requirement: RequirementChunkRetriever | None = None,
        verify_retrieved_chunk: RetrievedChunkVerifier | None = None,
        max_revisions: int = 2,
        provider_retry_max_attempts: int = 3,
        provider_retry_initial_delay_seconds: float = 0.25,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._extract_requirements = (
            extract_requirements or extract_requirements_deterministically
        )
        self._retrieve_chunks_for_requirement = (
            retrieve_chunks_for_requirement or self._retrieve_chunks
        )
        self._verify_retrieved_chunk = (
            verify_retrieved_chunk or self._verify_retrieved_chunk_from_database
        )
        self._max_revisions = max_revisions
        self._provider_retry_max_attempts = provider_retry_max_attempts
        self._provider_retry_initial_delay_seconds = (
            provider_retry_initial_delay_seconds
        )

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    async def aclose(self) -> None:
        close = getattr(self._provider, "aclose", None)
        if close is None:
            return
        result = close()
        if isawaitable(result):
            await result

    async def _retrieve_chunks(
        self,
        *,
        workspace_id: str,
        query: str,
        document_ids: Sequence[UUID],
    ) -> Sequence[RetrievedChunk]:
        async with self._session_factory() as session:
            return await retrieve_chunks(
                session,
                workspace_id=workspace_id,
                query=query,
                document_ids=document_ids,
            )

    async def _verify_retrieved_chunk_from_database(
        self,
        *,
        requirement: Requirement,
        chunk: RetrievedChunk,
    ) -> str | None:
        del requirement
        async with self._session_factory() as session:
            stored_chunk = await session.scalar(
                select(DocumentChunk).where(
                    DocumentChunk.id == chunk.chunk_id,
                    DocumentChunk.document_id == chunk.document_id,
                    DocumentChunk.workspace_id == chunk.workspace_id,
                )
            )
        if (
            stored_chunk is None
            or stored_chunk.position != chunk.position
            or stored_chunk.content != chunk.content
        ):
            raise InvalidRetrievedEvidenceError(
                "Retrieved chunk does not match persisted evidence"
            )
        if chunk.score <= 0:
            return None
        return stored_chunk.content[:800]

    async def _load_input(
        self,
        run_id: UUID,
        execution_token: UUID,
    ) -> ApplicationGraphState:
        async with self._session_factory() as session:
            result = await session.execute(
                select(AgentRun, Job)
                .join(
                    Job,
                    (Job.id == AgentRun.job_id)
                    & (Job.workspace_id == AgentRun.workspace_id),
                )
                .where(
                    AgentRun.id == run_id,
                    AgentRun.status == "running",
                    AgentRun.execution_token == execution_token,
                )
            )
            row = result.one_or_none()

        if row is None:
            raise RunExecutionLeaseLostError(
                "Run execution lease is no longer owned by this worker"
            )

        run, job = row
        if run.provider != self.provider_name or run.model != self.model_name:
            raise RunExecutorConfigurationError(
                "Agent run provider does not match the configured executor"
            )

        state: ApplicationGraphState = {
            "run_id": run.id,
            "workspace_id": run.workspace_id,
            "job_description": job.description,
            "document_ids": [UUID(value) for value in run.document_ids],
        }
        state.update(self._deserialize_checkpoint(run.state_json))
        return state

    @staticmethod
    def _deserialize_checkpoint(
        checkpoint: dict[str, object],
    ) -> ApplicationGraphState:
        state: ApplicationGraphState = {}
        if "requirements" in checkpoint:
            state["requirements"] = [
                Requirement.model_validate(value)
                for value in _require_list(checkpoint["requirements"])
            ]
        if "retrieved_evidence" in checkpoint:
            state["retrieved_evidence"] = [
                Evidence.model_validate(value)
                for value in _require_list(checkpoint["retrieved_evidence"])
            ]
        if "artifact" in checkpoint:
            state["artifact"] = ApplicationArtifact.model_validate(
                checkpoint["artifact"]
            )
        if "validation" in checkpoint:
            state["validation"] = ArtifactValidation.model_validate(
                checkpoint["validation"]
            )
        if "revision_count" in checkpoint:
            state["revision_count"] = _require_int(checkpoint["revision_count"])
        if "validated_revision_count" in checkpoint:
            state["validated_revision_count"] = _require_int(
                checkpoint["validated_revision_count"]
            )
        if "node_trace" in checkpoint:
            state["node_trace"] = [
                _require_node_name(value)
                for value in _require_list(checkpoint["node_trace"])
            ]
        if "terminal_status" in checkpoint:
            terminal_status = checkpoint["terminal_status"]
            if terminal_status not in {"succeeded", "validation_failed"}:
                raise RunExecutorConfigurationError(
                    "Persisted checkpoint has an invalid terminal status"
                )
            state["terminal_status"] = terminal_status
        return state

    @staticmethod
    def _serialize_checkpoint(
        state: ApplicationGraphState,
    ) -> dict[str, object]:
        checkpoint: dict[str, object] = {}
        for key in _CHECKPOINT_KEYS:
            if key not in state:
                continue
            value = state[key]  # type: ignore[literal-required]
            if isinstance(value, (ApplicationArtifact, ArtifactValidation)):
                checkpoint[key] = value.model_dump(mode="json")
            elif key in {"requirements", "retrieved_evidence"}:
                checkpoint[key] = [
                    item.model_dump(mode="json")
                    for item in value  # type: ignore[union-attr]
                ]
            else:
                checkpoint[key] = value
        return checkpoint

    async def _save_checkpoint(
        self,
        run_id: UUID,
        *,
        execution_token: UUID,
        node: NodeName,
        state: ApplicationGraphState,
    ) -> None:
        async with self._session_factory() as session:
            checkpoint = self._serialize_checkpoint(state)
            claim = await session.execute(
                update(AgentRun)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.status == "running",
                    AgentRun.execution_token == execution_token,
                )
                .values(
                    current_node=node,
                    state_json=checkpoint,
                    revision_count=state.get("revision_count", 0),
                )
            )
            if claim.rowcount != 1:
                raise RunExecutionLeaseLostError(
                    "Run execution lease is no longer owned by this worker"
                )
            latest_sequence = await session.scalar(
                select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id)
            )
            session.add(
                RunEvent(
                    run_id=run_id,
                    sequence=0 if latest_sequence is None else latest_sequence + 1,
                    kind="node_completed",
                    data={"node": node},
                )
            )
            await session.commit()

    async def _record_retry(
        self,
        run_id: UUID,
        *,
        execution_token: UUID,
        retry: ProviderRetry,
    ) -> None:
        async with self._session_factory() as session:
            claim = await session.execute(
                update(AgentRun)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.status == "running",
                    AgentRun.execution_token == execution_token,
                )
                .values(execution_token=execution_token)
            )
            if claim.rowcount != 1:
                raise RunExecutionLeaseLostError(
                    "Run execution lease is no longer owned by this worker"
                )
            latest_sequence = await session.scalar(
                select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id)
            )
            session.add(
                RunEvent(
                    run_id=run_id,
                    sequence=0 if latest_sequence is None else latest_sequence + 1,
                    kind="retry_scheduled",
                    data={
                        "attempt": retry.attempt + 1,
                        "max_attempts": retry.max_attempts,
                        "delay_seconds": retry.delay_seconds,
                        "reason_code": retry.reason_code,
                    },
                )
            )
            await session.commit()

    async def __call__(
        self,
        run_id: UUID,
        execution_token: UUID,
    ) -> RunExecutionResult:
        state = await self._load_input(run_id, execution_token)
        if "terminal_status" not in state:
            graph = build_application_graph(
                provider=self._provider,
                extract_requirements=self._extract_requirements,
                retrieve_chunks_for_requirement=self._retrieve_chunks_for_requirement,
                verify_retrieved_chunk=self._verify_retrieved_chunk,
                max_revisions=self._max_revisions,
                provider_retry_max_attempts=self._provider_retry_max_attempts,
                provider_retry_initial_delay_seconds=(
                    self._provider_retry_initial_delay_seconds
                ),
                on_provider_retry=lambda retry: self._record_retry(
                    run_id,
                    execution_token=execution_token,
                    retry=retry,
                ),
            )
            async for update_payload in graph.astream(state, stream_mode="updates"):
                for node_name, update in update_payload.items():
                    if not update:
                        continue
                    _merge_update(state, update)
                    node = _require_node_name(node_name)
                    await self._save_checkpoint(
                        run_id,
                        execution_token=execution_token,
                        node=node,
                        state=state,
                    )

        return _build_execution_result(state, run_id)


def _merge_update(
    state: ApplicationGraphState,
    update: dict[str, Any],
) -> None:
    for key, value in update.items():
        if key == "node_trace":
            state.setdefault("node_trace", []).extend(value)
        else:
            state[key] = value  # type: ignore[literal-required]


def _build_execution_result(
    state: ApplicationGraphState,
    run_id: UUID,
) -> RunExecutionResult:
    terminal_status = state.get("terminal_status")
    validation = state.get("validation")
    if terminal_status not in {"succeeded", "validation_failed"} or not isinstance(
        validation, ArtifactValidation
    ):
        raise InvalidRunExecutionResultError(
            "Application graph did not return a controlled terminal result"
        )
    artifact = state.get("artifact") if terminal_status == "succeeded" else None
    return RunExecutionResult(
        run_id=run_id,
        workspace_id=state["workspace_id"],
        terminal_status=terminal_status,
        artifact=artifact,
        validation=validation,
        trusted_requirements=tuple(state["requirements"]),
        retrieved_evidence=tuple(state["retrieved_evidence"]),
    )


def _require_list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise RunExecutorConfigurationError("Persisted checkpoint is invalid")
    return value


def _require_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RunExecutorConfigurationError("Persisted checkpoint is invalid")
    return value


def _require_node_name(value: object) -> NodeName:
    if value not in {"extract", "retrieve", "draft", "validate", "revise", "terminal"}:
        raise RunExecutorConfigurationError("Persisted checkpoint is invalid")
    return value  # type: ignore[return-value]
