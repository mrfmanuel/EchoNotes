"""Export endpoint (tag `exports`): US-16 download the whole project as a ZIP."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.db.session import get_session
from app.services.export import export_project as build_export

router = APIRouter(tags=["exports"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ProjectIdPath = Annotated[uuid.UUID, Path(alias="projectId")]


@router.get(
    "/api/projects/{projectId}/export",
    operation_id="exportProject",
    response_class=StreamingResponse,
    responses={
        status.HTTP_200_OK: {"content": {"application/zip": {}}},
        status.HTTP_404_NOT_FOUND: {"description": "Resource not found"},
    },
)
async def export_project(project_id: ProjectIdPath, session: SessionDep) -> StreamingResponse:
    archive = await build_export(session, project_id)
    return StreamingResponse(
        archive.chunks(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{archive.filename}"',
            "Content-Length": str(archive.size_bytes),
        },
        # Also discards the temp file if the client disconnects before the stream ends.
        background=BackgroundTask(archive.close),
    )
