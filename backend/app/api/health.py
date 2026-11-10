"""`GET /api/health` (US-17): liveness plus a bounded database check."""

import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db.session import get_session

DB_CHECK_TIMEOUT_SECONDS = 2.0

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "error", "skipped"]


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
    if await database_is_reachable(session):
        return Health(status="ok", version=__version__, database="ok")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Health(status="degraded", version=__version__, database="error")
