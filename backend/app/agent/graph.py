from collections import Counter
from collections.abc import Sequence
from typing import Literal, Protocol
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.agent.state import ApplicationGraphInput, ApplicationGraphState
from app.providers import AgentProvider
from app.rag.retrieval import RetrievedChunk
from app.schemas.artifact import ApplicationArtifact, Evidence, Requirement
from app.validation import validate_artifact


class InvalidExtractedRequirementsError(ValueError):
    """Raised when extracted requirements violate workflow invariants."""


class RequirementExtractor(Protocol):
    async def __call__(
        self,
        job_description: str,
    ) -> Sequence[Requirement]: ...


class RequirementChunkRetriever(Protocol):
    async def __call__(
        self,
        *,
        workspace_id: str,
        query: str,
        document_ids: Sequence[UUID],
    ) -> Sequence[RetrievedChunk]: ...


class RetrievedChunkVerifier(Protocol):
    async def __call__(
        self,
        *,
        requirement: Requirement,
        chunk: RetrievedChunk,
    ) -> str | None: ...


def build_application_graph(
    *,
    provider: AgentProvider,
    extract_requirements: RequirementExtractor,
    retrieve_chunks_for_requirement: RequirementChunkRetriever,
    verify_retrieved_chunk: RetrievedChunkVerifier,
    max_revisions: int = 2,
):
    if max_revisions < 0:
        raise ValueError("max_revisions must be greater than or equal to zero")

    async def extract(
        state: ApplicationGraphState,
    ) -> dict[str, object]:
        extracted = await extract_requirements(state["job_description"])
        requirements = [
            Requirement.model_validate(requirement.model_dump(mode="python"))
            for requirement in extracted
        ]
        if not requirements:
            raise InvalidExtractedRequirementsError("No requirements were extracted")
        duplicate_requirement_ids = sorted(
            requirement_id
            for requirement_id, count in Counter(
                requirement.id for requirement in requirements
            ).items()
            if count > 1
        )
        if duplicate_requirement_ids:
            raise InvalidExtractedRequirementsError(
                "Duplicate extracted requirement IDs: "
                + ", ".join(duplicate_requirement_ids)
            )

        return {
            "requirements": requirements,
            "node_trace": ["extract"],
        }

    async def retrieve(
        state: ApplicationGraphState,
    ) -> dict[str, object]:
        workspace_id = state["workspace_id"]
        document_ids = state["document_ids"]
        allowed_document_ids = set(document_ids)
        evidence: list[Evidence] = []

        for requirement in state["requirements"]:
            chunks = await retrieve_chunks_for_requirement(
                workspace_id=workspace_id,
                query=requirement.text,
                document_ids=document_ids,
            )

            for chunk in chunks:
                if (
                    chunk.workspace_id != workspace_id
                    or chunk.document_id not in allowed_document_ids
                ):
                    raise ValueError("Retrieved chunk is outside the workflow scope")

                excerpt = await verify_retrieved_chunk(
                    requirement=requirement.model_copy(deep=True),
                    chunk=chunk,
                )

                if excerpt is None:
                    continue

                if excerpt not in chunk.content:
                    raise ValueError(
                        "Verified excerpt is not present in the retrieved chunk"
                    )

                evidence.append(
                    Evidence(
                        requirement_id=requirement.id,
                        workspace_id=chunk.workspace_id,
                        document_id=chunk.document_id,
                        chunk_id=chunk.chunk_id,
                        excerpt=excerpt,
                        score=chunk.score,
                    )
                )

        return {
            "retrieved_evidence": evidence,
            "node_trace": ["retrieve"],
        }

    async def draft(
        state: ApplicationGraphState,
    ) -> dict[str, object]:
        artifact = await provider.draft_artifact(
            run_id=state["run_id"],
            requirements=[
                requirement.model_copy(deep=True)
                for requirement in state["requirements"]
            ],
            evidence=[
                item.model_copy(deep=True) for item in state["retrieved_evidence"]
            ],
        )
        artifact_snapshot = ApplicationArtifact.model_validate(
            artifact.model_dump(mode="python")
        )
        return {
            "artifact": artifact_snapshot,
            "revision_count": 0,
            "node_trace": ["draft"],
        }

    def validate(
        state: ApplicationGraphState,
    ) -> dict[str, object]:
        validation = validate_artifact(
            state["artifact"],
            expected_run_id=state["run_id"],
            workspace_id=state["workspace_id"],
            trusted_requirements=state["requirements"],
            retrieved_evidence=state["retrieved_evidence"],
        )
        return {
            "validation": validation,
            "node_trace": ["validate"],
        }

    async def revise(
        state: ApplicationGraphState,
    ) -> dict[str, object]:
        artifact = await provider.revise_artifact(
            run_id=state["run_id"],
            artifact=state["artifact"].model_copy(deep=True),
            validation=state["validation"].model_copy(deep=True),
            requirements=[
                requirement.model_copy(deep=True)
                for requirement in state["requirements"]
            ],
            evidence=[
                item.model_copy(deep=True) for item in state["retrieved_evidence"]
            ],
        )
        artifact_snapshot = ApplicationArtifact.model_validate(
            artifact.model_dump(mode="python")
        )
        return {
            "artifact": artifact_snapshot,
            "revision_count": state["revision_count"] + 1,
            "node_trace": ["revise"],
        }

    def route_after_validation(
        state: ApplicationGraphState,
    ) -> Literal["revise", "terminal"]:
        if state["validation"].passed:
            return "terminal"
        if state["revision_count"] < max_revisions:
            return "revise"
        return "terminal"

    def terminal(
        state: ApplicationGraphState,
    ) -> dict[str, object]:
        terminal_status = (
            "succeeded" if state["validation"].passed else "validation_failed"
        )
        return {
            "terminal_status": terminal_status,
            "node_trace": ["terminal"],
        }

    builder = StateGraph(
        ApplicationGraphState,
        input_schema=ApplicationGraphInput,
    )
    builder.add_node("extract", extract)
    builder.add_node("retrieve", retrieve)
    builder.add_node("draft", draft)
    builder.add_node("validate", validate)
    builder.add_node("revise", revise)
    builder.add_node("terminal", terminal)

    builder.add_edge(START, "extract")
    builder.add_edge("extract", "retrieve")
    builder.add_edge("retrieve", "draft")
    builder.add_edge("draft", "validate")
    builder.add_conditional_edges("validate", route_after_validation)
    builder.add_edge("revise", "validate")
    builder.add_edge("terminal", END)

    return builder.compile()
