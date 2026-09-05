import json
import os
import subprocess
import sys
from pathlib import Path

import app.evaluation as evaluation_module
from app.eval_cli import main

DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "datasets"
    / "smoke-v1"
    / "cases.json"
)


def test_cli_returns_zero_for_passing_smoke_suite(capsys) -> None:
    exit_code = main(
        [
            "--dataset",
            str(DATASET_PATH),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert payload["passed"] is True
    assert payload["passed_cases"] == 3
    assert payload["failed_case_ids"] == []
    assert payload["execution_error_case_ids"] == []


def test_cli_returns_one_and_lists_every_failed_case(
    tmp_path: Path,
    capsys,
) -> None:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["documents"][0]["content"] = (
        "Led retail inventory reconciliation."
    )
    payload["cases"][1]["documents"][0]["content"] = "Operate Kubernetes clusters."
    failing_path = tmp_path / "failing-smoke.json"
    failing_path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = main(
        [
            "--dataset",
            str(failing_path),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert exit_code == 1
    assert captured.err == ""
    assert result["total_cases"] == 3
    assert result["failed_case_ids"] == [
        "grounded-evidence",
        "no-grounded-evidence",
    ]


def test_cli_returns_two_for_an_invalid_dataset(
    tmp_path: Path,
    capsys,
) -> None:
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{not-json", encoding="utf-8")

    exit_code = main(
        [
            "--dataset",
            str(invalid_path),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == "Evaluation dataset is invalid or unavailable.\n"
    assert "Traceback" not in captured.err


def test_cli_returns_two_after_reporting_every_execution_error(
    monkeypatch,
    capsys,
) -> None:
    called_case_ids: list[str] = []

    async def fail_case(case, **_: object) -> None:
        called_case_ids.append(case.case_id)
        raise RuntimeError("private execution detail")

    monkeypatch.setattr(evaluation_module, "run_evaluation_case", fail_case)

    exit_code = main(
        [
            "--dataset",
            str(DATASET_PATH),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert exit_code == 2
    assert captured.err == ""
    assert called_case_ids == [
        "grounded-evidence",
        "no-grounded-evidence",
        "forged-citation-rejected",
    ]
    assert result["execution_error_case_ids"] == called_case_ids
    assert "private execution detail" not in captured.out


def test_cli_cold_start_ignores_openai_provider_configuration() -> None:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("AGENT_PLATFORM_")
    }
    environment["AGENT_PLATFORM_LLM_PROVIDER"] = "openai"
    environment["AGENT_PLATFORM_OPENAI_API_KEY"] = "   "
    environment["AGENT_PLATFORM_OPENAI_MODEL"] = "   "
    environment["AGENT_PLATFORM_PROVIDER_RETRY_MAX_ATTEMPTS"] = "99"
    environment["AGENT_PLATFORM_DATABASE_URL"] = "not-a-database-url"
    backend_directory = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [sys.executable, "-m", "app.eval_cli", "--format", "json"],
        cwd=backend_directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert json.loads(completed.stdout)["passed_cases"] == 3
