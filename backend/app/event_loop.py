"""Event loop selection for native Windows (#41).

psycopg's async driver cannot run on the Windows Proactor event loop, which is what uvicorn
creates on Windows when it runs without `--reload`. uvicorn >= 0.36 creates the loop through an
explicit loop factory *before* it imports the app, so changing the asyncio policy from the app
module is too late for uvicorn. Two pieces fix it:

* `new_event_loop` is a custom uvicorn loop factory: start uvicorn with
  `--loop app.event_loop:new_event_loop` (documented in README / AGENTS.md). It returns a
  selector loop on Windows and uvicorn's default (`auto`: uvloop if installed) elsewhere.
* `use_selector_event_loop_policy` sets the selector policy on Windows when `app` is imported,
  so any other runner that asks asyncio for a new loop (scripts, `--loop none`) also works.

Both are no-ops on Linux and macOS.
"""

import asyncio
import sys

from uvicorn.loops.auto import auto_loop_factory

UVICORN_LOOP_OPTION = "app.event_loop:new_event_loop"


def is_windows() -> bool:
    return sys.platform == "win32"


def use_selector_event_loop_policy() -> None:
    """On Windows, make asyncio create selector loops (psycopg async needs `add_reader`)."""
    if not is_windows():
        return
    policy_class = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_class is not None and not isinstance(asyncio.get_event_loop_policy(), policy_class):
        asyncio.set_event_loop_policy(policy_class())


def new_event_loop() -> asyncio.AbstractEventLoop:
    """uvicorn `--loop` factory: a selector loop on Windows, uvicorn's default elsewhere."""
    if is_windows():
        return asyncio.SelectorEventLoop()
    return auto_loop_factory(use_subprocess=False)()


def is_proactor_loop(loop: asyncio.AbstractEventLoop) -> bool:
    proactor = getattr(asyncio, "ProactorEventLoop", None)
    return proactor is not None and isinstance(loop, proactor)
