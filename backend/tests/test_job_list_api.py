from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient

from app.db import Base, build_engine, build_session_factory, get_session
from app.main import app
from app.models.job import Job


async def create_test_client():
    test_engine = build_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = build_session_factory(test_engine)

    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_get_session():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return test_engine, test_session_factory


@pytest.mark.asyncio
async def test_list_jobs_returns_an_empty_page_for_a_new_workspace() -> None:
    test_engine, _ = await create_test_client()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/workspaces/new-workspace/jobs")

        assert response.status_code == 200
        assert response.json() == {
            "items": [],
            "limit": 20,
            "offset": 0,
            "has_more": False,
        }
    finally:
        app.dependency_overrides.pop(get_session, None)
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_list_jobs_scopes_search_escapes_wildcards_and_paginates() -> None:
    test_engine, test_session_factory = await create_test_client()
    created_at = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)

    try:
        async with test_session_factory() as session:
            session.add_all(
                [
                    Job(
                        workspace_id="workspace-1",
                        title="Rust service owner",
                        description="Own a Rust service.",
                        created_at=created_at,
                    ),
                    Job(
                        workspace_id="workspace-1",
                        title="Python API foundations",
                        description="Build Python APIs.",
                        created_at=created_at + timedelta(minutes=1),
                    ),
                    Job(
                        workspace_id="workspace-1",
                        title="Python 100%_ complete",
                        description="Build reliable Python services.",
                        created_at=created_at + timedelta(minutes=2),
                    ),
                    Job(
                        workspace_id="workspace-2",
                        title="Python 100%_ private",
                        description="Must not leak into workspace-1.",
                        created_at=created_at + timedelta(minutes=3),
                    ),
                ]
            )
            await session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            literal_search = await client.get(
                "/api/v1/workspaces/workspace-1/jobs",
                params={"q": "  100%_  "},
            )
            first_page = await client.get(
                "/api/v1/workspaces/workspace-1/jobs",
                params={"q": "python", "limit": 1, "offset": 0},
            )
            second_page = await client.get(
                "/api/v1/workspaces/workspace-1/jobs",
                params={"q": "python", "limit": 1, "offset": 1},
            )

        assert literal_search.status_code == 200
        literal_items = literal_search.json()["items"]
        assert [item["title"] for item in literal_items] == ["Python 100%_ complete"]
        assert set(literal_items[0]) == {
            "id",
            "workspace_id",
            "title",
            "created_at",
        }

        assert first_page.status_code == 200
        assert [item["title"] for item in first_page.json()["items"]] == [
            "Python 100%_ complete"
        ]
        assert first_page.json()["has_more"] is True

        assert second_page.status_code == 200
        assert [item["title"] for item in second_page.json()["items"]] == [
            "Python API foundations"
        ]
        assert second_page.json()["has_more"] is False
    finally:
        app.dependency_overrides.pop(get_session, None)
        await test_engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"q": "x" * 201},
    ],
)
async def test_list_jobs_rejects_invalid_pagination_or_search(
    params: dict[str, int | str],
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/workspaces/workspace-1/jobs",
            params=params,
        )

    assert response.status_code == 422
