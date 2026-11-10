"""Projects endpoints (tag `projects`): US-01 create, US-02 list, US-03 rename, US-04 delete."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import schemas
from app.db.models import Screenshot
from app.db.session import get_session
from app.services import projects as service

router = APIRouter(prefix="/api/projects", tags=["projects"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ProjectIdPath = Annotated[uuid.UUID, Path(alias="projectId")]
NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "Resource not found"}}


def _to_project(item: service.ProjectWithCounts) -> schemas.Project:
    project = item.project
    return schemas.Project(
        id=project.id,
        name=project.name,
        slug=project.slug,
        transcript_count=item.transcript_count,
        screenshot_count=item.screenshot_count,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _to_screenshot(screenshot: Screenshot) -> schemas.Screenshot:
    return schemas.Screenshot(
        id=screenshot.id,
        project_id=screenshot.project_id,
        transcript_id=screenshot.transcript_id,
        filename=screenshot.filename,
        content_type=screenshot.content_type,
        size_bytes=screenshot.size_bytes,
        image_url=schemas.screenshot_image_url(screenshot.id),
        created_at=screenshot.created_at,
    )


@router.get("", operation_id="listProjects", response_model=list[schemas.Project])
async def list_projects(session: SessionDep) -> list[schemas.Project]:
    return [_to_project(item) for item in await service.list_projects(session)]


@router.post(
    "",
    operation_id="createProject",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.Project,
)
async def create_project(body: schemas.ProjectCreate, session: SessionDep) -> schemas.Project:
    return _to_project(await service.create_project(session, body.name))


@router.get(
    "/{projectId}",
    operation_id="getProject",
    response_model=schemas.ProjectDetail,
    responses=NOT_FOUND,
)
async def get_project(project_id: ProjectIdPath, session: SessionDep) -> schemas.ProjectDetail:
    item = await service.get_project_with_counts(session, project_id)
    contents = await service.get_project_contents(session, project_id)
    return schemas.ProjectDetail(
        **_to_project(item).model_dump(),
        transcripts=[schemas.TranscriptSummary.model_validate(t) for t in contents.transcripts],
        screenshots=[_to_screenshot(s) for s in contents.screenshots],
    )


@router.patch(
    "/{projectId}",
    operation_id="renameProject",
    response_model=schemas.Project,
    responses=NOT_FOUND,
)
async def rename_project(
    project_id: ProjectIdPath, body: schemas.ProjectUpdate, session: SessionDep
) -> schemas.Project:
    return _to_project(await service.rename_project(session, project_id, body.name))


@router.delete(
    "/{projectId}",
    operation_id="deleteProject",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=NOT_FOUND,
)
async def delete_project(project_id: ProjectIdPath, session: SessionDep) -> Response:
    await service.delete_project(session, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
