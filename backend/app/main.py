from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import health, projects
from app.config import get_settings
from app.db.session import dispose_engine
from app.errors import register_error_handlers
from app.logging import configure_logging
from app.middleware import RequestContextMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()  # fails fast on invalid configuration
    configure_logging(settings.log_level)

    app = FastAPI(title="EchoNotes API", version=__version__, lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(projects.router)
    return app


app = create_app()
