"""AI project summary endpoints (tag `summaries`, US-22)."""

import asyncio
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import schemas
from app.config import get_settings
from app.db.session import get_session, get_session_factory
from app.services import summaries as service
from app.summarization import Summarizer, get_summarizer

router = APIRouter(prefix="/api", tags=["summaries"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
SummarizerDep = Annotated[Summarizer, Depends(get_summarizer)]
ProjectIdPath = Annotated[uuid.UUID, Path(alias="projectId")]
SummaryIdPath = Annotated[uuid.UUID, Path(alias="summaryId")]

_ERROR = {"model": schemas.Error}
NOT_FOUND = {**_ERROR, "description": "Resource not found"}
SUMMARY_FILENAME = "summary.html"


def summary_tasks(request: Request) -> set[asyncio.Task[None]]:
    """Strong references to running jobs, cancelled at shutdown (see `app.main.lifespan`)."""
    tasks: set[asyncio.Task[None]] = request.app.state.summary_tasks
    return tasks


@router.post(
    "/projects/{projectId}/summaries",
    operation_id="createSummary",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=schemas.Summary,
    responses={
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_409_CONFLICT: {**_ERROR, "description": "The project has no transcripts"},
    },
)
async def create_summary(
    project_id: ProjectIdPath,
    request: Request,
    session: SessionDep,
    factory: SessionFactoryDep,
    summarizer: SummarizerDep,
) -> schemas.Summary:
    summary, created = await service.start_summary(session, project_id, summarizer.name)
    response = schemas.to_summary(summary)
    # Release the request's connection before the job opens its own sessions.
    await session.close()
    if created:
        service.schedule_summary(
            summary_tasks(request), factory, summarizer, summary, get_settings()
        )
    return response


@router.get(
    "/projects/{projectId}/summaries/latest",
    operation_id="getLatestSummary",
    response_model=schemas.Summary,
    responses={status.HTTP_404_NOT_FOUND: NOT_FOUND},
)
async def get_latest_summary(project_id: ProjectIdPath, session: SessionDep) -> schemas.Summary:
    return schemas.to_summary(await service.latest_summary(session, project_id))


@router.get(
    "/projects/{projectId}/summaries/{summaryId}/download",
    operation_id="downloadSummary",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "description": "summary.html attachment",
            "content": {"text/html": {}},
        },
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_409_CONFLICT: {**_ERROR, "description": "The summary is not ready"},
    },
)
async def download_summary(
    project_id: ProjectIdPath, summary_id: SummaryIdPath, session: SessionDep
) -> Response:
    summary = await service.downloadable_summary(session, project_id, summary_id)
    assert summary.html is not None  # guaranteed by `downloadable_summary`
    logger.info(
        "summary downloaded",
        extra={"summary_id": str(summary_id), "project_id": str(project_id)},
    )
    return Response(
        content=service.summary_html_bytes(summary.html),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{SUMMARY_FILENAME}"'},
    )
