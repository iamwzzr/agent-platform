"""Idempotently fill the three named demo workspaces with synthetic Job rows."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid5

ALLOWED_WORKSPACES = frozenset({"docker-acceptance", "test-gap", "test-grounded"})
SEED_NAMESPACE = UUID("3f6348f5-c70d-4695-a050-1f6f7f0509b8")
ROLE_SCENARIOS = (
    (
        "AI Platform Engineer",
        "Build Python APIs for model-serving workflows and operate containerized services.",
    ),
    (
        "Backend Engineer",
        "Develop reliable HTTP services, database workflows, and automated checks.",
    ),
    (
        "ML Platform Intern",
        "Integrate inference tasks, inspect service health, and document operations.",
    ),
    (
        "Cloud Platform Intern",
        "Maintain Linux services, troubleshoot ports, and improve Docker workflows.",
    ),
    (
        "Frontend Platform Intern",
        "Build React status views, loading states, error recovery, and polling flows.",
    ),
)


class SeedError(RuntimeError):
    """Raised when a database is unsafe or cannot be filled to the requested target."""


def _synthetic_job(workspace_id: str, ordinal: int) -> tuple[str, str, str, str]:
    role, requirement = ROLE_SCENARIOS[(ordinal - 1) % len(ROLE_SCENARIOS)]
    job_id = uuid5(
        SEED_NAMESPACE,
        f"agent-platform:synthetic-demo-job:v1:{workspace_id}:{ordinal}",
    ).hex
    title = f"Synthetic demo JD {ordinal:03d} — {role}"
    description = (
        "SYNTHETIC DEMO DATA — not a real vacancy, application, or model evaluation. "
        f"Scenario {ordinal:03d}: {requirement} "
        "Use only fictional evidence when exercising this record."
    )
    created_at = (
        (datetime(2026, 9, 9, tzinfo=timezone.utc) + timedelta(seconds=ordinal))
        .replace(tzinfo=None)
        .isoformat(sep=" ", timespec="seconds")
    )
    return job_id, title, description, created_at


def _connect_existing(database: Path) -> sqlite3.Connection:
    resolved = database.expanduser().resolve()
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=rw", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        connection.close()
        raise SeedError("Database integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        connection.close()
        raise SeedError("Database foreign-key check failed")
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
    }
    required_columns = {"id", "workspace_id", "title", "description", "created_at"}
    if not required_columns.issubset(columns):
        connection.close()
        raise SeedError("Database does not contain the expected jobs table")
    return connection


def seed_demo_jobs(
    database: Path,
    workspace_ids: list[str],
    *,
    target_per_workspace: int = 100,
    apply: bool = False,
) -> dict[str, object]:
    unknown = sorted(set(workspace_ids) - ALLOWED_WORKSPACES)
    if unknown:
        raise SeedError("Unsupported demo workspace: " + ", ".join(unknown))
    if not workspace_ids or len(set(workspace_ids)) != len(workspace_ids):
        raise SeedError("Provide one or more unique demo workspaces")
    if not 1 <= target_per_workspace <= 10_000:
        raise SeedError("Target per workspace must be between 1 and 10000")

    connection = _connect_existing(database)
    summaries: list[dict[str, object]] = []
    try:
        connection.execute("BEGIN IMMEDIATE")
        for workspace_id in workspace_ids:
            before = connection.execute(
                "SELECT count(*) FROM jobs WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()[0]
            if before > target_per_workspace:
                raise SeedError(
                    f"{workspace_id} already has {before} jobs; refusing to delete rows"
                )

            rows_to_insert: list[tuple[str, str, str, str, str]] = []
            ordinal = 1
            while before + len(rows_to_insert) < target_per_workspace:
                job_id, title, description, created_at = _synthetic_job(
                    workspace_id, ordinal
                )
                existing = connection.execute(
                    "SELECT workspace_id, title, description FROM jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if existing is not None:
                    if tuple(existing) != (workspace_id, title, description):
                        raise SeedError(
                            f"Synthetic Job ID collision at ordinal {ordinal}"
                        )
                else:
                    rows_to_insert.append(
                        (job_id, workspace_id, title, description, created_at)
                    )
                ordinal += 1

            if apply:
                connection.executemany(
                    "INSERT INTO jobs "
                    "(id, workspace_id, title, description, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    rows_to_insert,
                )
            summaries.append(
                {
                    "workspace_id": workspace_id,
                    "before": before,
                    "planned": len(rows_to_insert),
                    "after": before + (len(rows_to_insert) if apply else 0),
                    "after_if_applied": before + len(rows_to_insert),
                }
            )

        if apply:
            connection.commit()
        else:
            connection.rollback()

        if apply:
            for summary in summaries:
                actual = connection.execute(
                    "SELECT count(*) FROM jobs WHERE workspace_id = ?",
                    (summary["workspace_id"],),
                ).fetchone()[0]
                if actual != target_per_workspace:
                    raise SeedError("Post-commit workspace count verification failed")
        return {
            "database": str(database.expanduser().resolve()),
            "mode": "apply" if apply else "dry-run",
            "target_per_workspace": target_per_workspace,
            "workspaces": summaries,
        }
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fill named demo workspaces with clearly marked synthetic JD records."
    )
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--workspace", action="append", required=True)
    parser.add_argument("--target-per-workspace", type=int, default=100)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit inserts. Without this flag, only print the plan.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = seed_demo_jobs(
            args.database,
            args.workspace,
            target_per_workspace=args.target_per_workspace,
            apply=args.apply,
        )
    except (OSError, sqlite3.Error, SeedError) as error:
        print(f"Synthetic demo seed failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
