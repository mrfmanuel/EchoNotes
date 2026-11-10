"""`GET /api/health` (US-17): liveness, a bounded database check and the deployed commit."""

import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.config import get_settings
from app.db.session import get_session

DB_CHECK_TIMEOUT_SECONDS = 2.0

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "error", "skipped"]
    commit: str
    environment: Literal["local", "dev", "prod"]


async def database_is_reachable(session: AsyncSession) -> bool:
    """Run `SELECT 1` with a short timeout. Logs the error class only, never the URL."""
    try:
        async with asyncio.timeout(DB_CHECK_TIMEOUT_SECONDS):
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("database health check failed", extra={"error_class": type(exc).__name__})
        return False
    return True


@router.get(
    "/api/health",
    operation_id="getHealth",
    response_model=Health,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": Health}},
)
async def health(
    response: Response, session: Annotated[AsyncSession, Depends(get_session)]
) -> Health:
    database_ok = await database_is_reachable(session)
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    settings = get_settings()
    return Health(
        status="ok" if database_ok else "degraded",
        version=__version__,
        database="ok" if database_ok else "error",
        commit=settings.deployed_commit,
        environment=settings.app_env,
    )
