import json
from pathlib import Path
from uuid import UUID

import pytest

import app.evaluation as evaluation_module
import app.openai_provider as openai_provider_module
from app.evaluation import (
    EvaluationDatasetError,
    EvaluationExecutionError,
    calculate_retrieval_metrics,
    evaluate_dataset,
    load_evaluation_dataset,
    run_evaluation_case,
)

DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "datasets"
    / "smoke-v1"
    / "cases.json"
)


def test_smoke_dataset_has_three_unique_frozen_cases() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)

    assert dataset.version == "smoke-v1"
    assert dataset.suite_kind == "smoke"
    assert [case.case_id for case in dataset.cases] == [
        "grounded-evidence",
        "no-grounded-evidence",
        "forged-citation-rejected",
    ]
    assert len({case.case_id for case in dataset.cases}) == 3


def test_dataset_rejects_duplicate_case_ids_before_execution(tmp_path: Path) -> None:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    payload["cases"][1]["case_id"] = payload["cases"][0]["case_id"]
    invalid_path = tmp_path / "duplicate-case.json"
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationDatasetError, match="invalid"):
        load_evaluation_dataset(invalid_path)


def test_dataset_rejects_supported_requirement_without_labeled_evidence(
    tmp_path: Path,
) -> None:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["expected"]["relevant_evidence"] = []
    invalid_path = tmp_path / "missing-evidence-label.json"
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationDatasetError, match="invalid"):
        load_evaluation_dataset(invalid_path)


def test_retrieval_without_expected_evidence_is_not_scored_as_one() -> None:
    recall, unexpected_count = calculate_retrieval_metrics(set(), set())

    assert recall is None
    assert unexpected_count == 0


@pytest.mark.asyncio
async def test_smoke_suite_runs_offline_and_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_openai_client_creation(*_: object, **__: object) -> None:
        raise AssertionError("evaluation attempted to create an OpenAI client")

    monkeypatch.setenv("AGENT_PLATFORM_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AGENT_PLATFORM_OPENAI_API_KEY", "unused-eval-key")
    monkeypatch.setenv("AGENT_PLATFORM_OPENAI_MODEL", "unused-eval-model")
    monkeypatch.setattr(
        openai_provider_module,
        "AsyncOpenAI",
        reject_openai_client_creation,
    )

    first = await evaluate_dataset(DATASET_PATH)
    second = await evaluate_dataset(DATASET_PATH)

    assert first == second
    assert first.passed is True
    assert first.passed_cases == 3
    assert first.failed_case_ids == []
    assert first.execution_error_case_ids == []
    assert first.quality_metrics.model_dump() == {
        "retrieval_recall_at_5": 1.0,
        "citation_validity": 1.0,
        "citation_coverage": 1.0,
        "requirement_coverage": 1.0,
        "gap_accuracy": 1.0,
    }
    assert first.guardrail_pass_rate == 1.0


@pytest.mark.asyncio
async def test_no_evidence_is_gap_and_forged_citation_is_not_published() -> None:
    report = await evaluate_dataset(DATASET_PATH)
    results = {result.case_id: result for result in report.results}

    no_evidence = results["no-grounded-evidence"]
    assert no_evidence.passed is True
    assert no_evidence.actual_terminal_status == "succeeded"
    assert no_evidence.metrics.retrieval_recall_at_5 is None
    assert no_evidence.metrics.unexpected_retrieval_count == 0
    assert no_evidence.metrics.requirement_coverage == 1.0
    assert no_evidence.metrics.gap_accuracy == 1.0

    forged = results["forged-citation-rejected"]
    assert forged.passed is True
    assert forged.actual_terminal_status == "validation_failed"
    assert forged.artifact_record_count == 0
    assert forged.guardrail_passed is True
    assert "invalid_citation_chunk_ids" in forged.validation_failure_fields
    assert forged.metrics.retrieval_recall_at_5 == 1.0
    assert forged.metrics.citation_validity is None
    assert "invalid_citation_detection_mismatch" not in forged.failures


@pytest.mark.asyncio
async def test_case_rejects_an_existing_database_path(tmp_path: Path) -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    existing_database = tmp_path / "existing.db"
    existing_database.touch()

    with pytest.raises(EvaluationExecutionError, match="must not already exist"):
        await run_evaluation_case(
            dataset.cases[0],
            thresholds=dataset.thresholds,
            database_path=existing_database,
        )


@pytest.mark.asyncio
async def test_guardrail_fails_when_detected_citation_ids_do_not_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    guardrail_case = next(
        case for case in dataset.cases if case.case_kind == "guardrail"
    )
    monkeypatch.setattr(
        evaluation_module,
        "_candidate_invalid_citation_chunk_ids",
        lambda *_: {UUID(int=0)},
    )

    result = await run_evaluation_case(
        guardrail_case,
        thresholds=dataset.thresholds,
        database_path=tmp_path / "guardrail-mismatch.db",
    )

    assert result.passed is False
    assert result.guardrail_passed is False
    assert "invalid_citation_detection_mismatch" in result.failures
