import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import exports, health, projects, screenshots, summaries, transcriptions
from app.config import get_settings
from app.db.session import dispose_engine, get_session_factory
from app.errors import register_error_handlers
from app.event_loop import UVICORN_LOOP_OPTION, is_proactor_loop, use_selector_event_loop_policy
from app.logging import configure_logging
from app.middleware import RequestContextMiddleware
from app.services.summaries import cancel_summary_tasks, recover_interrupted
from app.spa import mount_spa
from app.summarization import build_summarizer
from app.telemetry import setup_telemetry
from app.transcription import build_transcriber

# Windows (#41): before any loop exists, make asyncio hand out selector loops (no-op elsewhere).
use_selector_event_loop_policy()

logger = logging.getLogger(__name__)


def warn_if_proactor_loop() -> None:
    """psycopg async fails on the Windows Proactor loop: say how to start uvicorn instead."""
    if is_proactor_loop(asyncio.get_running_loop()):
        logger.error(
            "Proactor event loop detected: database calls will fail on Windows",
            extra={"fix": f"start uvicorn with --loop {UVICORN_LOOP_OPTION}"},
        )


async def recover_summaries(app: FastAPI) -> None:
    """US-22 AC18: jobs a dead process left pending/running become `failed` (`interrupted`).

    Never blocks startup on a database problem: the app still starts (health reports it)."""
    factory = app.dependency_overrides.get(get_session_factory, get_session_factory)()
    try:
        await recover_interrupted(factory)
    except Exception as exc:
        logger.warning("summary recovery skipped", extra={"error_type": type(exc).__name__})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    warn_if_proactor_loop()
    await recover_summaries(app)
    yield
    await cancel_summary_tasks(app.state.summary_tasks)
    await dispose_engine()
    if app.state.telemetry is not None:
        app.state.telemetry.shutdown()  # flush the last spans, metrics and logs


def create_app() -> FastAPI:
    settings = get_settings()  # fails fast on invalid configuration
    configure_logging(settings.log_level)

    transcriber = build_transcriber(settings)  # fails fast: groq without GROQ_API_KEY
    summarizer = build_summarizer(settings)  # fails fast: explicit provider without its key

    app = FastAPI(title="EchoNotes API", version=__version__, lifespan=lifespan)
    app.state.transcriber = transcriber
    app.state.summarizer = summarizer
    app.state.summary_tasks = set()
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(transcriptions.router)
    app.include_router(screenshots.router)
    app.include_router(exports.router)
    app.include_router(summaries.router)
    # Keep last: the SPA catch-all must come after every API router.
    mount_spa(app, settings.static_dir)
    # Off (None) unless OTEL_EXPORTER_OTLP_ENDPOINT is set; before the first request on purpose.
    app.state.telemetry = setup_telemetry(app, settings)
    return app


app = create_app()
