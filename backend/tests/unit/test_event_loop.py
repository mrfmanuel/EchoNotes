"""#41: native Windows runs the app on a selector event loop (psycopg async needs one).

The tests monkeypatch `sys.platform`, so they also run (and pass) on Linux CI.
"""

import asyncio
import importlib
import logging
import sys
from collections.abc import Iterator

import pytest
from uvicorn.config import Config

import app.main
from app import event_loop
from app.event_loop import (
    UVICORN_LOOP_OPTION,
    is_proactor_loop,
    new_event_loop,
    use_selector_event_loop_policy,
)


class FakeSelectorPolicy(asyncio.DefaultEventLoopPolicy):
    """Stands in for `asyncio.WindowsSelectorEventLoopPolicy`, which only exists on Windows."""


class FakeProactorLoop(asyncio.SelectorEventLoop):
    """Stands in for `asyncio.ProactorEventLoop` on non-Windows platforms."""


@pytest.fixture
def restore_policy() -> Iterator[None]:
    original = asyncio.get_event_loop_policy()
    yield
    asyncio.set_event_loop_policy(original)


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch, restore_policy: None) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    if not hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        monkeypatch.setattr(asyncio, "WindowsSelectorEventLoopPolicy", FakeSelectorPolicy, False)


def test_policy_helper_on_windows_sets_the_selector_policy(windows: None) -> None:
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

    use_selector_event_loop_policy()

    assert isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy)


def test_importing_the_app_module_on_windows_sets_the_selector_policy(windows: None) -> None:
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

    importlib.reload(app.main)

    assert isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy)


def test_policy_helper_does_nothing_on_linux(
    monkeypatch: pytest.MonkeyPatch, restore_policy: None
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    policy = asyncio.DefaultEventLoopPolicy()
    asyncio.set_event_loop_policy(policy)

    use_selector_event_loop_policy()

    assert asyncio.get_event_loop_policy() is policy


def test_uvicorn_loop_factory_on_windows_is_a_selector_loop(windows: None) -> None:
    loop = new_event_loop()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
        assert not is_proactor_loop(loop)
    finally:
        loop.close()


def test_uvicorn_loop_factory_elsewhere_uses_uvicorns_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    sentinel = asyncio.SelectorEventLoop()
    monkeypatch.setattr(event_loop, "auto_loop_factory", lambda use_subprocess: lambda: sentinel)
    try:
        assert new_event_loop() is sentinel
    finally:
        sentinel.close()


def test_documented_uvicorn_loop_option_resolves_to_the_factory() -> None:
    config = Config("app.main:app", loop=UVICORN_LOOP_OPTION)

    assert config.get_loop_factory() is new_event_loop


def test_proactor_loop_at_startup_logs_how_to_fix_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(asyncio, "ProactorEventLoop", FakeProactorLoop, False)

    async def start() -> None:
        app.main.warn_if_proactor_loop()

    with asyncio.Runner(loop_factory=FakeProactorLoop) as runner:
        runner.run(start())

    (record,) = [r for r in caplog.records if r.name == "app.main"]
    assert record.levelno == logging.ERROR
    assert UVICORN_LOOP_OPTION in record.__dict__["fix"]


def test_selector_loop_at_startup_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    async def start() -> None:
        app.main.warn_if_proactor_loop()

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(start())

    assert [r for r in caplog.records if r.name == "app.main"] == []
