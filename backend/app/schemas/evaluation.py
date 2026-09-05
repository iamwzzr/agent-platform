from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.schemas.artifact import Requirement

EvaluationIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    ),
]

EvaluationShortText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=800,
    ),
]

EvaluationLongText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=20_000,
    ),
]

EvaluationCaseKind = Literal["quality", "guardrail"]
EvaluationProviderScenario = Literal["deterministic", "forged_citation"]
EvaluationTerminalStatus = Literal["succeeded", "validation_failed"]
EvaluationActualStatus = Literal[
    "succeeded",
    "validation_failed",
    "failed",
    "execution_error",
]
ValidationFailureField = Literal[
    "invalid_citation_chunk_ids",
    "unsupported_claim_ids",
    "unsupported_requirement_ids",
    "unsupported_resume_bullet_indexes",
    "unsupported_cover_letter",
    "uncovered_requirement_ids",
    "conflicting_requirement_ids",
    "mismatched_requirement_ids",
    "duplicate_requirement_ids",
    "unknown_gap_requirement_ids",
    "evidenced_gap_requirement_ids",
    "duplicate_gap_requirement_ids",
    "duplicate_claim_ids",
    "unsupported_citation_chunk_ids",
    "run_id_mismatch",
]


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationThresholds(EvaluationModel):
    retrieval_recall_at_5: float = Field(ge=0.0, le=1.0)
    citation_validity: float = Field(ge=0.0, le=1.0)
    citation_coverage: float = Field(ge=0.0, le=1.0)
    requirement_coverage: float = Field(ge=0.0, le=1.0)
    gap_accuracy: float = Field(ge=0.0, le=1.0)


class EvaluationJob(EvaluationModel):
    title: EvaluationShortText
    description: EvaluationLongText


class EvaluationDocument(EvaluationModel):
    document_ref: EvaluationIdentifier
    name: EvaluationShortText
    content: EvaluationLongText


class EvaluationEvidenceRef(EvaluationModel):
    requirement_id: EvaluationIdentifier
    document_ref: EvaluationIdentifier
    chunk_position: int = Field(ge=0)


class EvaluationExpected(EvaluationModel):
    terminal_status: EvaluationTerminalStatus
    requirements: list[Requirement] = Field(min_length=1, max_length=20)
    relevant_evidence: list[EvaluationEvidenceRef] = Field(default_factory=list)
    supported_requirement_ids: list[EvaluationIdentifier] = Field(default_factory=list)
    gap_requirement_ids: list[EvaluationIdentifier] = Field(default_factory=list)
    artifact_record_count: Literal[0, 1]
    validation_failure_fields: list[ValidationFailureField] = Field(
        default_factory=list
    )


class EvaluationCase(EvaluationModel):
    case_id: EvaluationIdentifier
    case_kind: EvaluationCaseKind
    provider_scenario: EvaluationProviderScenario = "deterministic"
    job: EvaluationJob
    documents: list[EvaluationDocument] = Field(min_length=1, max_length=20)
    expected: EvaluationExpected

    @model_validator(mode="after")
    def validate_case_contract(self) -> Self:
        document_refs = [document.document_ref for document in self.documents]
        if len(document_refs) != len(set(document_refs)):
            raise ValueError("Evaluation document refs must be unique within a case")

        requirements = self.expected.requirements
        requirement_ids = [requirement.id for requirement in requirements]
        requirement_id_set = set(requirement_ids)
        if len(requirement_ids) != len(requirement_id_set):
            raise ValueError("Evaluation requirement IDs must be unique within a case")

        supported_ids = self.expected.supported_requirement_ids
        gap_ids = self.expected.gap_requirement_ids
        if len(supported_ids) != len(set(supported_ids)) or len(gap_ids) != len(
            set(gap_ids)
        ):
            raise ValueError("Expected requirement classifications must be unique")

        supported_id_set = set(supported_ids)
        gap_id_set = set(gap_ids)
        if supported_id_set & gap_id_set:
            raise ValueError("A requirement cannot be both supported and a gap")
        if supported_id_set | gap_id_set != requirement_id_set:
            raise ValueError("Every expected requirement must be classified")

        relevant_keys = [
            (
                item.requirement_id,
                item.document_ref,
                item.chunk_position,
            )
            for item in self.expected.relevant_evidence
        ]
        if len(relevant_keys) != len(set(relevant_keys)):
            raise ValueError("Expected relevant evidence refs must be unique")
        known_document_refs = set(document_refs)
        for item in self.expected.relevant_evidence:
            if item.document_ref not in known_document_refs:
                raise ValueError("Expected evidence references an unknown document")
            if item.requirement_id not in requirement_id_set:
                raise ValueError("Expected evidence references an unknown requirement")
            if item.requirement_id not in supported_id_set:
                raise ValueError(
                    "Expected evidence must belong to a supported requirement"
                )
        relevant_requirement_ids = {
            item.requirement_id for item in self.expected.relevant_evidence
        }
        if relevant_requirement_ids != supported_id_set:
            raise ValueError(
                "Every supported requirement must have labeled relevant evidence"
            )

        if self.case_kind == "quality":
            if self.provider_scenario != "deterministic":
                raise ValueError("Quality cases must use the deterministic provider")
            if self.expected.terminal_status != "succeeded":
                raise ValueError("Quality cases must expect a succeeded run")
            if self.expected.artifact_record_count != 1:
                raise ValueError("Quality cases must expect one persisted artifact")
            if self.expected.validation_failure_fields:
                raise ValueError("Quality cases cannot expect validation failures")
        else:
            if self.provider_scenario != "forged_citation":
                raise ValueError("Guardrail cases must use an adversarial scenario")
            if not supported_id_set:
                raise ValueError(
                    "Forged-citation guardrails require a supported requirement"
                )
            if self.expected.terminal_status != "validation_failed":
                raise ValueError("Guardrail cases must expect validation failure")
            if self.expected.artifact_record_count != 0:
                raise ValueError("Guardrail cases cannot expect a published artifact")
            if not self.expected.validation_failure_fields:
                raise ValueError("Guardrail cases must name a validation failure")

        return self


class EvaluationDataset(EvaluationModel):
    version: EvaluationIdentifier
    suite_kind: Literal["smoke", "full"]
    thresholds: EvaluationThresholds
    cases: list[EvaluationCase] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_dataset_contract(self) -> Self:
        expected_case_count = 3 if self.suite_kind == "smoke" else 10
        if len(self.cases) != expected_case_count:
            raise ValueError(
                f"A {self.suite_kind} evaluation suite requires "
                f"exactly {expected_case_count} cases"
            )

        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Evaluation case IDs must be unique")

        quality_cases = [case for case in self.cases if case.case_kind == "quality"]
        guardrail_cases = [case for case in self.cases if case.case_kind == "guardrail"]
        if not quality_cases or not guardrail_cases:
            raise ValueError(
                "Evaluation suites require both quality and guardrail cases"
            )
        if not any(case.expected.relevant_evidence for case in quality_cases):
            raise ValueError(
                "Evaluation suites require a quality case with relevant evidence"
            )
        if not any(case.expected.gap_requirement_ids for case in quality_cases):
            raise ValueError("Evaluation suites require a quality gap case")
        return self


class EvaluationCaseMetrics(EvaluationModel):
    retrieval_recall_at_5: float | None = Field(default=None, ge=0.0, le=1.0)
    unexpected_retrieval_count: int = Field(default=0, ge=0)
    citation_validity: float | None = Field(default=None, ge=0.0, le=1.0)
    citation_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    requirement_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    gap_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)


class EvaluationCaseResult(EvaluationModel):
    case_id: EvaluationIdentifier
    case_kind: EvaluationCaseKind
    passed: bool
    expected_terminal_status: EvaluationTerminalStatus
    actual_terminal_status: EvaluationActualStatus
    artifact_record_count: int = Field(ge=0)
    validation_failure_fields: list[ValidationFailureField] = Field(
        default_factory=list
    )
    guardrail_passed: bool | None = None
    metrics: EvaluationCaseMetrics
    failures: list[str] = Field(default_factory=list)


class EvaluationMetricSummary(EvaluationModel):
    retrieval_recall_at_5: float | None = Field(default=None, ge=0.0, le=1.0)
    citation_validity: float | None = Field(default=None, ge=0.0, le=1.0)
    citation_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    requirement_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    gap_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)


class EvaluationReport(EvaluationModel):
    dataset_version: EvaluationIdentifier
    suite_kind: Literal["smoke", "full"]
    thresholds: EvaluationThresholds
    total_cases: int = Field(ge=1)
    passed_cases: int = Field(ge=0)
    failed_case_ids: list[EvaluationIdentifier] = Field(default_factory=list)
    execution_error_case_ids: list[EvaluationIdentifier] = Field(default_factory=list)
    passed: bool
    quality_metrics: EvaluationMetricSummary
    guardrail_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    results: list[EvaluationCaseResult]
