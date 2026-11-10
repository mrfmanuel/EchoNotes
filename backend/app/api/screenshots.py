"""Screenshots endpoints (tag `screenshots`): US-12 upload, US-14 link, US-15 gallery/delete."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import schemas
from app.config import get_settings
from app.db.session import get_session
from app.services import screenshots as service
from app.services.images import MIB, clean_filename, read_image

router = APIRouter(tags=["screenshots"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ProjectIdPath = Annotated[uuid.UUID, Path(alias="projectId")]
ScreenshotIdPath = Annotated[uuid.UUID, Path(alias="screenshotId")]
IMAGE_CACHE_CONTROL = "private, max-age=31536000, immutable"


def _error(description: str) -> dict[str, str]:
    return {"description": description}


NOT_FOUND = {status.HTTP_404_NOT_FOUND: _error("Resource not found")}
UPLOAD_ERRORS = {
    **NOT_FOUND,
    status.HTTP_413_CONTENT_TOO_LARGE: _error("File exceeds the size limit"),
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: _error("File type not allowed"),
}


@router.get(
    "/api/projects/{projectId}/screenshots",
    operation_id="listScreenshots",
    response_model=list[schemas.Screenshot],
    responses=NOT_FOUND,
)
async def list_screenshots(
    project_id: ProjectIdPath, session: SessionDep
) -> list[schemas.Screenshot]:
    return [schemas.to_screenshot(s) for s in await service.list_screenshots(session, project_id)]


@router.post(
    "/api/projects/{projectId}/screenshots",
    operation_id="uploadScreenshot",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.Screenshot,
    responses=UPLOAD_ERRORS,
)
async def upload_screenshot(
    project_id: ProjectIdPath,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    transcript_id: Annotated[uuid.UUID | None, Form()] = None,
) -> schemas.Screenshot:
    await service.ensure_project(session, project_id)
    try:
        data, content_type = await read_image(file, get_settings().max_image_mb * MIB)
    finally:
        await file.close()
    new = service.NewScreenshot(
        filename=clean_filename(file.filename, content_type),
        content_type=content_type,
        data=data,
        transcript_id=transcript_id,
    )
    return schemas.to_screenshot(await service.create_screenshot(session, project_id, new))


@router.patch(
    "/api/screenshots/{screenshotId}",
    operation_id="updateScreenshot",
    response_model=schemas.Screenshot,
    responses=NOT_FOUND,
)
async def update_screenshot(
    screenshot_id: ScreenshotIdPath, body: schemas.ScreenshotUpdate, session: SessionDep
) -> schemas.Screenshot:
    if "transcript_id" not in body.model_fields_set:  # nothing to change
        return schemas.to_screenshot(await service.get_screenshot(session, screenshot_id))
    screenshot = await service.link_screenshot(session, screenshot_id, body.transcript_id)
    return schemas.to_screenshot(screenshot)


@router.delete(
    "/api/screenshots/{screenshotId}",
    operation_id="deleteScreenshot",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=NOT_FOUND,
)
async def delete_screenshot(screenshot_id: ScreenshotIdPath, session: SessionDep) -> Response:
    await service.delete_screenshot(session, screenshot_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/api/screenshots/{screenshotId}/image",
    operation_id="getScreenshotImage",
    response_class=Response,
    responses=NOT_FOUND,
)
async def get_screenshot_image(screenshot_id: ScreenshotIdPath, session: SessionDep) -> Response:
    data, content_type = await service.get_image(session, screenshot_id)
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": IMAGE_CACHE_CONTROL, "X-Content-Type-Options": "nosniff"},
    )
