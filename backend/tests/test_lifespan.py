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

    monkeypatch.setattr(main_module, "engine", fake_engine)
    monkeypatch.setattr(
        main_module,
        "create_tables",
        create_tables_mock,
    )

    async with main_module.app.router.lifespan_context(
        main_module.app
    ):
        create_tables_mock.assert_awaited_once_with(fake_engine)
        fake_engine.dispose.assert_not_awaited()

    fake_engine.dispose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_lifespan_disposes_engine_when_startup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = SimpleNamespace(dispose=AsyncMock())
    create_tables_mock = AsyncMock(
        side_effect=RuntimeError("database unavailable")
    )

    monkeypatch.setattr(main_module, "engine", fake_engine)
    monkeypatch.setattr(
        main_module,
        "create_tables",
        create_tables_mock,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        async with main_module.app.router.lifespan_context(
            main_module.app
        ):
            pass

    fake_engine.dispose.assert_awaited_once_with()
