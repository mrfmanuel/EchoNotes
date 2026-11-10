from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from app import __version__


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "error", "skipped"]


def create_app() -> FastAPI:
    app = FastAPI(title="EchoNotes API", version=__version__)

    @app.get("/api/health", response_model=Health, tags=["health"])
    async def health() -> Health:
        # The database check arrives with the persistence layer (issue #16).
        return Health(status="ok", version=__version__, database="skipped")

    return app


app = create_app()
