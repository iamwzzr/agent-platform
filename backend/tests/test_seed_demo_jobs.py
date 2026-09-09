import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed-demo-jobs.py"


def _create_database(path: Path, rows: int = 1) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE jobs ("
            "id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, title TEXT NOT NULL, "
            "description TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        for index in range(rows):
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?)",
                (
                    f"existing-{index}",
                    "test-grounded",
                    f"Existing {index}",
                    "Existing demonstration record",
                    "2026-09-09 00:00:00",
                ),
            )


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def test_seed_requires_apply_and_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "demo.db"
    _create_database(database)
    arguments = (
        "--database",
        str(database),
        "--workspace",
        "test-grounded",
        "--target-per-workspace",
        "4",
    )

    preview = _run(*arguments)
    assert preview.returncode == 0
    assert '"mode": "dry-run"' in preview.stdout
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1

    applied = _run(*arguments, "--apply")
    assert applied.returncode == 0
    assert '"planned": 3' in applied.stdout
    second = _run(*arguments, "--apply")
    assert second.returncode == 0
    assert '"planned": 0' in second.stdout

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT id, title, description FROM jobs ORDER BY title"
        ).fetchall()
    assert len(rows) == 4
    synthetic = [row for row in rows if row[0] != "existing-0"]
    assert all(len(row[0]) == 32 for row in synthetic)
    assert all("Synthetic demo JD" in row[1] for row in synthetic)
    assert all("not a real vacancy" in row[2] for row in synthetic)


def test_seed_refuses_unknown_workspace_and_overtarget_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "demo.db"
    _create_database(database, rows=2)

    unknown = _run(
        "--database",
        str(database),
        "--workspace",
        "production",
        "--apply",
    )
    assert unknown.returncode == 2
    assert "Unsupported demo workspace" in unknown.stderr

    overtarget = _run(
        "--database",
        str(database),
        "--workspace",
        "test-grounded",
        "--target-per-workspace",
        "1",
        "--apply",
    )
    assert overtarget.returncode == 2
    assert "refusing to delete rows" in overtarget.stderr


def test_seed_module_opens_only_an_existing_database(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("seed_demo_jobs", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        module.seed_demo_jobs(missing, ["test-gap"], apply=True)
    assert not missing.exists()
