from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import main as main_module


@pytest.mark.asyncio
async def test_lifespan_runs_startup_and_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = SimpleNamespace(dispose=AsyncMock())
    create_tables_mock = AsyncMock()
    close_run_service_mock = AsyncMock()

    monkeypatch.setattr(main_module, "engine", fake_engine)
    monkeypatch.setattr(
        main_module,
        "create_tables",
        create_tables_mock,
    )
    monkeypatch.setattr(
        main_module,
        "close_default_run_service",
        close_run_service_mock,
    )

    async with main_module.app.router.lifespan_context(main_module.app):
        create_tables_mock.assert_awaited_once_with(fake_engine)
        close_run_service_mock.assert_not_awaited()
        fake_engine.dispose.assert_not_awaited()

    close_run_service_mock.assert_awaited_once_with()
    fake_engine.dispose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_lifespan_disposes_engine_when_startup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = SimpleNamespace(dispose=AsyncMock())
    create_tables_mock = AsyncMock(side_effect=RuntimeError("database unavailable"))
    close_run_service_mock = AsyncMock()

    monkeypatch.setattr(main_module, "engine", fake_engine)
    monkeypatch.setattr(
        main_module,
        "create_tables",
        create_tables_mock,
    )
    monkeypatch.setattr(
        main_module,
        "close_default_run_service",
        close_run_service_mock,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        async with main_module.app.router.lifespan_context(main_module.app):
            pass

    close_run_service_mock.assert_awaited_once_with()
    fake_engine.dispose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_lifespan_disposes_engine_when_run_service_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = SimpleNamespace(dispose=AsyncMock())
    close_run_service_mock = AsyncMock(
        side_effect=RuntimeError("provider close failed")
    )

    monkeypatch.setattr(main_module, "engine", fake_engine)
    monkeypatch.setattr(main_module, "create_tables", AsyncMock())
    monkeypatch.setattr(
        main_module,
        "close_default_run_service",
        close_run_service_mock,
    )

    with pytest.raises(RuntimeError, match="provider close failed"):
        async with main_module.app.router.lifespan_context(main_module.app):
            pass

    fake_engine.dispose.assert_awaited_once_with()
