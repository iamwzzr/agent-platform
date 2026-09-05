from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application_executor import ApplicationGraphRunExecutor
from app.db_core import build_engine, build_session_factory, create_tables
from app.models.agent_run import AgentRun
from app.models.artifact_record import ArtifactRecord
from app.models.document import Document
from app.models.job import Job
from app.models.run_event import RunEvent
from app.providers import AgentProvider, DeterministicMockProvider
from app.rag.chunking import split_text
from app.rag.ingestion import ingest_document
from app.run_service import AgentRunService
from app.schemas.artifact import (
    ApplicationArtifact,
    ArtifactValidation,
    Citation,
    Claim,
    Evidence,
    Gap,
    Requirement,
    ResumeBullet,
)
from app.schemas.evaluation import (
    EvaluationCase,
    EvaluationCaseMetrics,
    EvaluationCaseResult,
    EvaluationDataset,
    EvaluationMetricSummary,
    EvaluationReport,
    EvaluationThresholds,
    ValidationFailureField,
)

EvidenceRefKey = tuple[str, str, int]
EVALUATION_MAX_REVISIONS = 1
EVALUATION_PROVIDER_RETRY_MAX_ATTEMPTS = 1


class EvaluationDatasetError(ValueError):
    """Raised when a fixed evaluation dataset is unreadable or inconsistent."""


class EvaluationExecutionError(RuntimeError):
    """Raised when the evaluation harness cannot inspect a case result."""


class _ForgedCitationProvider(DeterministicMockProvider):
    """Produce a schema-valid artifact whose citations are deliberately forged."""

    async def draft_artifact(
        self,
        *,
        run_id: UUID,
        requirements: Sequence[Requirement],
        evidence: Sequence[Evidence],
    ) -> ApplicationArtifact:
        evidence_by_requirement: dict[str, list[Evidence]] = {}
        for item in evidence:
            evidence_by_requirement.setdefault(item.requirement_id, []).append(item)

        claims: list[Claim] = []
        resume_bullets: list[ResumeBullet] = []
        gaps: list[Gap] = []
        citations: list[Citation] = []
        for index, requirement in enumerate(requirements, start=1):
            matches = evidence_by_requirement.get(requirement.id, [])
            if not matches:
                gaps.append(
                    Gap(
                        requirement_id=requirement.id,
                        reason_code="no_grounded_evidence",
                    )
                )
                continue

            source = matches[0]
            forged_chunk_id = uuid5(
                NAMESPACE_URL,
                f"agent-platform-eval-forged:{requirement.id}",
            )
            claim_id = f"forged-claim-{index}"
            claims.append(
                Claim(
                    id=claim_id,
                    text=source.excerpt,
                    requirement_ids=[requirement.id],
                    citation_chunk_ids=[forged_chunk_id],
                )
            )
            resume_bullets.append(
                ResumeBullet(
                    text=source.excerpt,
                    claim_ids=[claim_id],
                )
            )
            citations.append(
                Citation(
                    document_id=source.document_id,
                    chunk_id=forged_chunk_id,
                )
            )

        return ApplicationArtifact(
            run_id=run_id,
            requirements=[item.model_copy(deep=True) for item in requirements],
            claims=claims,
            resume_bullets=resume_bullets,
            cover_letter=None,
            gaps=gaps,
            citations=citations,
        )

    async def revise_artifact(
        self,
        *,
        run_id: UUID,
        artifact: ApplicationArtifact,
        validation: ArtifactValidation,
        requirements: Sequence[Requirement],
        evidence: Sequence[Evidence],
    ) -> ApplicationArtifact:
        del artifact, validation
        return await self.draft_artifact(
            run_id=run_id,
            requirements=requirements,
            evidence=evidence,
        )


def load_evaluation_dataset(path: Path) -> EvaluationDataset:
    try:
        raw_dataset = path.read_text(encoding="utf-8")
    except OSError as error:
        raise EvaluationDatasetError("Evaluation dataset could not be read") from error

    try:
        dataset = EvaluationDataset.model_validate_json(raw_dataset)
    except ValidationError as error:
        raise EvaluationDatasetError("Evaluation dataset is invalid") from error

    _validate_expected_chunk_positions(dataset)
    return dataset


def _validate_expected_chunk_positions(dataset: EvaluationDataset) -> None:
    for case in dataset.cases:
        chunk_counts = {
            document.document_ref: len(split_text(document.content))
            for document in case.documents
        }
        for evidence_ref in case.expected.relevant_evidence:
            if evidence_ref.chunk_position >= chunk_counts[evidence_ref.document_ref]:
                raise EvaluationDatasetError(
                    "Evaluation evidence references a missing chunk position"
                )


def calculate_retrieval_metrics(
    expected: set[EvidenceRefKey],
    actual: set[EvidenceRefKey],
) -> tuple[float | None, int]:
    unexpected_count = len(actual - expected)
    if not expected:
        return None, unexpected_count
    return round(len(expected & actual) / len(expected), 4), unexpected_count


def calculate_artifact_metrics(
    *,
    artifact: ApplicationArtifact,
    trusted_requirements: Sequence[Requirement],
    retrieved_evidence: Sequence[Evidence],
    expected_supported_requirement_ids: set[str],
    expected_gap_requirement_ids: set[str],
) -> tuple[float | None, float | None, float, float]:
    claims_by_chunk_id: dict[UUID, list[Claim]] = {}
    for claim in artifact.claims:
        for chunk_id in claim.citation_chunk_ids:
            claims_by_chunk_id.setdefault(chunk_id, []).append(claim)

    def citation_supports_claim(
        *,
        document_id: UUID,
        chunk_id: UUID,
        claim: Claim,
        requirement_id: str,
    ) -> bool:
        return any(
            item.requirement_id == requirement_id
            and item.document_id == document_id
            and item.chunk_id == chunk_id
            and item.excerpt == claim.text
            for item in retrieved_evidence
        )

    valid_citation_count = 0
    for citation in artifact.citations:
        citation_is_valid = any(
            citation_supports_claim(
                document_id=citation.document_id,
                chunk_id=citation.chunk_id,
                claim=claim,
                requirement_id=requirement_id,
            )
            for claim in claims_by_chunk_id.get(citation.chunk_id, [])
            for requirement_id in claim.requirement_ids
        )
        valid_citation_count += int(citation_is_valid)

    if artifact.citations:
        citation_validity = round(
            valid_citation_count / len(artifact.citations),
            4,
        )
    elif artifact.claims:
        citation_validity = 0.0
    else:
        citation_validity = None

    declared_citations_by_chunk: dict[UUID, list[Citation]] = {}
    for citation in artifact.citations:
        declared_citations_by_chunk.setdefault(citation.chunk_id, []).append(citation)

    supported_requirement_ids: set[str] = set()
    fully_supported_claim_count = 0
    for claim in artifact.claims:
        supported_claim_requirement_ids: set[str] = set()
        for requirement_id in claim.requirement_ids:
            if any(
                citation_supports_claim(
                    document_id=citation.document_id,
                    chunk_id=chunk_id,
                    claim=claim,
                    requirement_id=requirement_id,
                )
                for chunk_id in claim.citation_chunk_ids
                for citation in declared_citations_by_chunk.get(chunk_id, [])
            ):
                supported_claim_requirement_ids.add(requirement_id)
                supported_requirement_ids.add(requirement_id)
        if supported_claim_requirement_ids == set(claim.requirement_ids):
            fully_supported_claim_count += 1

    citation_coverage = (
        round(fully_supported_claim_count / len(artifact.claims), 4)
        if artifact.claims
        else None
    )

    gap_id_counts = Counter(gap.requirement_id for gap in artifact.gaps)
    actual_gap_ids = set(gap_id_counts)
    trusted_requirement_ids = [item.id for item in trusted_requirements]
    correctly_covered = sum(
        (requirement_id in supported_requirement_ids)
        != (requirement_id in actual_gap_ids)
        for requirement_id in trusted_requirement_ids
    )
    requirement_coverage = round(
        correctly_covered / len(trusted_requirement_ids),
        4,
    )

    correctly_classified = sum(
        (
            requirement_id in expected_supported_requirement_ids
            and requirement_id in supported_requirement_ids
            and requirement_id not in actual_gap_ids
        )
        or (
            requirement_id in expected_gap_requirement_ids
            and requirement_id in actual_gap_ids
            and requirement_id not in supported_requirement_ids
        )
        for requirement_id in trusted_requirement_ids
    )
    gap_accuracy = round(
        correctly_classified / len(trusted_requirement_ids),
        4,
    )
    return (
        citation_validity,
        citation_coverage,
        requirement_coverage,
        gap_accuracy,
    )


def _build_evaluation_provider(case: EvaluationCase) -> AgentProvider:
    if case.provider_scenario == "forged_citation":
        return _ForgedCitationProvider()
    return DeterministicMockProvider()


async def _seed_case(
    session_factory: async_sessionmaker[AsyncSession],
    case: EvaluationCase,
) -> tuple[UUID, list[UUID], dict[UUID, tuple[str, int, UUID]]]:
    workspace_id = f"eval-{case.case_id}"
    job = Job(
        workspace_id=workspace_id,
        title=case.job.title,
        description=case.job.description,
    )
    stored_documents = [
        Document(
            workspace_id=workspace_id,
            name=document.name,
            content=document.content,
        )
        for document in case.documents
    ]
    chunk_locations: dict[UUID, tuple[str, int, UUID]] = {}

    async with session_factory() as session:
        session.add_all([job, *stored_documents])
        await session.flush()
        for expected_document, stored_document in zip(
            case.documents,
            stored_documents,
            strict=True,
        ):
            chunks = await ingest_document(
                session,
                workspace_id=workspace_id,
                document_id=stored_document.id,
            )
            for chunk in chunks:
                chunk_locations[chunk.id] = (
                    expected_document.document_ref,
                    chunk.position,
                    stored_document.id,
                )
        await session.commit()

    return job.id, [document.id for document in stored_documents], chunk_locations


def _checkpoint_models[T](
    checkpoint: dict[str, object],
    key: str,
    model: type[T],
) -> list[T]:
    values = checkpoint.get(key)
    if not isinstance(values, list):
        raise EvaluationExecutionError("Evaluation checkpoint is incomplete")
    try:
        return [model.model_validate(value) for value in values]  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValidationError) as error:
        raise EvaluationExecutionError("Evaluation checkpoint is invalid") from error


def _checkpoint_validation(checkpoint: dict[str, object]) -> ArtifactValidation:
    value = checkpoint.get("validation")
    try:
        return ArtifactValidation.model_validate(value)
    except (TypeError, ValidationError) as error:
        raise EvaluationExecutionError("Evaluation checkpoint is invalid") from error


def _observed_validation_failures(
    validation: ArtifactValidation,
) -> list[ValidationFailureField]:
    return [
        cast(ValidationFailureField, field_name)
        for field_name in ArtifactValidation.model_fields
        if field_name != "passed" and bool(getattr(validation, field_name))
    ]


def _candidate_invalid_citation_chunk_ids(
    artifact: ApplicationArtifact,
    retrieved_evidence: Sequence[Evidence],
) -> set[UUID]:
    trusted_citation_pairs = {
        (item.document_id, item.chunk_id) for item in retrieved_evidence
    }
    valid_declared_chunk_ids: set[UUID] = set()
    invalid_chunk_ids: set[UUID] = set()
    for citation in artifact.citations:
        if (citation.document_id, citation.chunk_id) in trusted_citation_pairs:
            valid_declared_chunk_ids.add(citation.chunk_id)
        else:
            invalid_chunk_ids.add(citation.chunk_id)

    for claim in artifact.claims:
        invalid_chunk_ids.update(
            chunk_id
            for chunk_id in claim.citation_chunk_ids
            if chunk_id not in valid_declared_chunk_ids
        )
    return invalid_chunk_ids


def _append_metric_failure(
    failures: list[str],
    *,
    name: str,
    actual: float | None,
    threshold: float,
) -> None:
    if actual is not None and actual < threshold:
        failures.append(f"{name}={actual:.4f} is below {threshold:.4f}")


async def run_evaluation_case(
    case: EvaluationCase,
    *,
    thresholds: EvaluationThresholds,
    database_path: Path,
) -> EvaluationCaseResult:
    if database_path.exists():
        raise EvaluationExecutionError(
            "Evaluation database path must not already exist"
        )
    engine = build_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = build_session_factory(engine)
    service: AgentRunService | None = None
    try:
        await create_tables(engine)
        job_id, document_ids, chunk_locations = await _seed_case(
            session_factory,
            case,
        )
        provider = _build_evaluation_provider(case)
        executor = ApplicationGraphRunExecutor(
            session_factory=session_factory,
            provider=provider,
            max_revisions=EVALUATION_MAX_REVISIONS,
            provider_retry_max_attempts=EVALUATION_PROVIDER_RETRY_MAX_ATTEMPTS,
            provider_retry_initial_delay_seconds=0,
        )
        service = AgentRunService(
            session_factory=session_factory,
            executor=executor,
        )
        workspace_id = f"eval-{case.case_id}"
        run_id = await service.start_run(
            workspace_id=workspace_id,
            job_id=job_id,
            document_ids=document_ids,
            idempotency_key=f"eval-{case.case_id}",
        )

        async with session_factory() as session:
            run = await session.get(AgentRun, run_id)
            artifact_records = list(
                (
                    await session.scalars(
                        select(ArtifactRecord).where(ArtifactRecord.run_id == run_id)
                    )
                ).all()
            )
            events = list(
                (
                    await session.scalars(
                        select(RunEvent)
                        .where(RunEvent.run_id == run_id)
                        .order_by(RunEvent.sequence)
                    )
                ).all()
            )

        if run is None:
            raise EvaluationExecutionError("Evaluation run was not persisted")
        if run.status not in {"succeeded", "validation_failed", "failed"}:
            raise EvaluationExecutionError(
                "Evaluation run did not reach a terminal state"
            )

        trusted_requirements = _checkpoint_models(
            run.state_json,
            "requirements",
            Requirement,
        )
        retrieved_evidence = _checkpoint_models(
            run.state_json,
            "retrieved_evidence",
            Evidence,
        )
        validation = _checkpoint_validation(run.state_json)
        observed_validation_failures = _observed_validation_failures(validation)

        expected_retrieval = {
            (
                item.requirement_id,
                item.document_ref,
                item.chunk_position,
            )
            for item in case.expected.relevant_evidence
        }
        actual_retrieval: set[EvidenceRefKey] = set()
        for item in retrieved_evidence:
            location = chunk_locations.get(item.chunk_id)
            if location is None or item.document_id != location[2]:
                raise EvaluationExecutionError(
                    "Retrieved evidence cannot be resolved to the seeded case"
                )
            actual_retrieval.add((item.requirement_id, location[0], location[1]))

        retrieval_recall, unexpected_retrieval_count = calculate_retrieval_metrics(
            expected_retrieval,
            actual_retrieval,
        )
        metrics = EvaluationCaseMetrics(
            retrieval_recall_at_5=retrieval_recall,
            unexpected_retrieval_count=unexpected_retrieval_count,
        )
        failures: list[str] = []
        if trusted_requirements != case.expected.requirements:
            failures.append("requirements_mismatch")
        if run.status != case.expected.terminal_status:
            failures.append(
                f"terminal_status={run.status} expected {case.expected.terminal_status}"
            )
        if len(artifact_records) != case.expected.artifact_record_count:
            failures.append(
                "artifact_record_count="
                f"{len(artifact_records)} expected "
                f"{case.expected.artifact_record_count}"
            )
        if case.expected.terminal_status not in {event.kind for event in events}:
            failures.append("terminal_event_missing")

        expected_failure_fields = set(case.expected.validation_failure_fields)
        if not expected_failure_fields.issubset(observed_validation_failures):
            failures.append("expected_validation_failure_missing")

        _append_metric_failure(
            failures,
            name="retrieval_recall_at_5",
            actual=metrics.retrieval_recall_at_5,
            threshold=thresholds.retrieval_recall_at_5,
        )
        if not expected_retrieval and metrics.unexpected_retrieval_count:
            failures.append(
                "unexpected_retrieval_count="
                f"{metrics.unexpected_retrieval_count} expected 0"
            )

        guardrail_passed: bool | None = None
        if case.case_kind == "quality":
            if not validation.passed:
                failures.append("published_validation_failed")
            if len(artifact_records) == 1:
                artifact = ApplicationArtifact.model_validate(
                    artifact_records[0].content
                )
                persisted_validation = ArtifactValidation.model_validate(
                    artifact_records[0].validation
                )
                if persisted_validation != validation:
                    failures.append("persisted_validation_mismatch")
                (
                    citation_validity,
                    citation_coverage,
                    requirement_coverage,
                    gap_accuracy,
                ) = calculate_artifact_metrics(
                    artifact=artifact,
                    trusted_requirements=trusted_requirements,
                    retrieved_evidence=retrieved_evidence,
                    expected_supported_requirement_ids=set(
                        case.expected.supported_requirement_ids
                    ),
                    expected_gap_requirement_ids=set(case.expected.gap_requirement_ids),
                )
                metrics = metrics.model_copy(
                    update={
                        "citation_validity": citation_validity,
                        "citation_coverage": citation_coverage,
                        "requirement_coverage": requirement_coverage,
                        "gap_accuracy": gap_accuracy,
                    }
                )
                for metric_name in (
                    "citation_validity",
                    "citation_coverage",
                    "requirement_coverage",
                    "gap_accuracy",
                ):
                    _append_metric_failure(
                        failures,
                        name=metric_name,
                        actual=getattr(metrics, metric_name),
                        threshold=getattr(thresholds, metric_name),
                    )
            else:
                failures.append("published_artifact_unavailable")
        else:
            if validation.passed:
                failures.append("guardrail_validation_unexpectedly_passed")
            candidate_value = run.state_json.get("artifact")
            if candidate_value is None:
                failures.append("candidate_artifact_checkpoint_missing")
            else:
                try:
                    candidate_artifact = ApplicationArtifact.model_validate(
                        candidate_value
                    )
                except (TypeError, ValidationError) as error:
                    raise EvaluationExecutionError(
                        "Evaluation candidate artifact checkpoint is invalid"
                    ) from error
                candidate_invalid_ids = _candidate_invalid_citation_chunk_ids(
                    candidate_artifact,
                    retrieved_evidence,
                )
                if not candidate_invalid_ids:
                    failures.append("forged_citation_missing")
                if candidate_invalid_ids != set(validation.invalid_citation_chunk_ids):
                    failures.append("invalid_citation_detection_mismatch")
            guardrail_passed = not failures

        return EvaluationCaseResult(
            case_id=case.case_id,
            case_kind=case.case_kind,
            passed=not failures,
            expected_terminal_status=case.expected.terminal_status,
            actual_terminal_status=cast(
                str,
                run.status,
            ),
            artifact_record_count=len(artifact_records),
            validation_failure_fields=observed_validation_failures,
            guardrail_passed=guardrail_passed,
            metrics=metrics,
            failures=failures,
        )
    finally:
        try:
            if service is not None:
                await service.aclose()
        finally:
            await engine.dispose()


def _execution_error_result(case: EvaluationCase) -> EvaluationCaseResult:
    return EvaluationCaseResult(
        case_id=case.case_id,
        case_kind=case.case_kind,
        passed=False,
        expected_terminal_status=case.expected.terminal_status,
        actual_terminal_status="execution_error",
        artifact_record_count=0,
        guardrail_passed=False if case.case_kind == "guardrail" else None,
        metrics=EvaluationCaseMetrics(),
        failures=["execution_error"],
    )


def _mean_metric(
    results: Sequence[EvaluationCaseResult],
    metric_name: str,
) -> float | None:
    values = [
        cast(float, value)
        for result in results
        if result.case_kind == "quality"
        if (value := getattr(result.metrics, metric_name)) is not None
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _build_report(
    dataset: EvaluationDataset,
    results: list[EvaluationCaseResult],
) -> EvaluationReport:
    failed_case_ids = [result.case_id for result in results if not result.passed]
    execution_error_case_ids = [
        result.case_id
        for result in results
        if result.actual_terminal_status == "execution_error"
    ]
    guardrail_results = [
        result for result in results if result.case_kind == "guardrail"
    ]
    guardrail_pass_rate = (
        round(
            sum(result.guardrail_passed is True for result in guardrail_results)
            / len(guardrail_results),
            4,
        )
        if guardrail_results
        else None
    )
    return EvaluationReport(
        dataset_version=dataset.version,
        suite_kind=dataset.suite_kind,
        thresholds=dataset.thresholds,
        total_cases=len(results),
        passed_cases=len(results) - len(failed_case_ids),
        failed_case_ids=failed_case_ids,
        execution_error_case_ids=execution_error_case_ids,
        passed=not failed_case_ids,
        quality_metrics=EvaluationMetricSummary(
            retrieval_recall_at_5=_mean_metric(
                results,
                "retrieval_recall_at_5",
            ),
            citation_validity=_mean_metric(results, "citation_validity"),
            citation_coverage=_mean_metric(results, "citation_coverage"),
            requirement_coverage=_mean_metric(results, "requirement_coverage"),
            gap_accuracy=_mean_metric(results, "gap_accuracy"),
        ),
        guardrail_pass_rate=guardrail_pass_rate,
        results=results,
    )


async def evaluate_dataset(path: Path) -> EvaluationReport:
    dataset = load_evaluation_dataset(path)
    results: list[EvaluationCaseResult] = []
    with TemporaryDirectory(prefix="agent-platform-eval-") as temporary_directory:
        database_directory = Path(temporary_directory)
        for index, case in enumerate(dataset.cases):
            try:
                result = await run_evaluation_case(
                    case,
                    thresholds=dataset.thresholds,
                    database_path=(
                        database_directory / f"{index:02d}-{case.case_id}.db"
                    ),
                )
            except Exception:  # noqa: BLE001 -- one case must not hide later failures
                result = _execution_error_result(case)
            results.append(result)

    return _build_report(dataset, results)
