from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.evaluation import EvaluationDatasetError, evaluate_dataset
from app.schemas.evaluation import EvaluationReport

DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "datasets"
    / "smoke-v1"
    / "cases.json"
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the fixed offline application evaluation suite."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="Path to a versioned evaluation dataset.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output a human-readable summary or stable JSON.",
    )
    return parser.parse_args(argv)


def report_as_json(report: EvaluationReport) -> str:
    return json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def report_as_text(report: EvaluationReport) -> str:
    lines = [
        f"dataset={report.dataset_version} suite={report.suite_kind}",
        f"passed={report.passed_cases}/{report.total_cases}",
    ]
    for result in report.results:
        outcome = "PASS" if result.passed else "FAIL"
        line = f"{outcome} {result.case_id} status={result.actual_terminal_status}"
        if result.failures:
            line += " failures=" + "; ".join(result.failures)
        lines.append(line)

    metrics = report.quality_metrics
    lines.append(
        "quality_metrics="
        + ", ".join(
            f"{name}:{'N/A' if value is None else f'{value:.4f}'}"
            for name, value in metrics.model_dump().items()
        )
    )
    guardrail = (
        "N/A"
        if report.guardrail_pass_rate is None
        else f"{report.guardrail_pass_rate:.4f}"
    )
    lines.append(f"guardrail_pass_rate={guardrail}")
    if report.failed_case_ids:
        lines.append("failed_cases=" + ",".join(report.failed_case_ids))
    if report.execution_error_case_ids:
        lines.append(
            "execution_error_cases=" + ",".join(report.execution_error_case_ids)
        )
    return "\n".join(lines)


async def _run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = await evaluate_dataset(args.dataset)
    except EvaluationDatasetError:
        print("Evaluation dataset is invalid or unavailable.", file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 -- sanitize the public CLI failure boundary
        print("Evaluation execution failed.", file=sys.stderr)
        return 2

    output = report_as_json(report) if args.format == "json" else report_as_text(report)
    print(output)
    if report.execution_error_case_ids:
        return 2
    return 0 if report.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_run(argv))


if __name__ == "__main__":
    raise SystemExit(main())
