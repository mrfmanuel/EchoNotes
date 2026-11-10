"""Minimal byte payloads with real magic bytes, plus small API helpers for screenshots tests."""

import io
import zipfile
from typing import Any

import httpx2

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 24
WEBP = b"RIFF" + (20).to_bytes(4, "little") + b"WEBPVP8 " + b"\x00" * 12
GIF = b"GIF89a" + b"\x00" * 24
TEXT = b"definitely not an image"
MIB = 1024 * 1024
MAX_IMAGE_BYTES = 5 * MIB


def png_of_size(size: int) -> bytes:
    """A payload with PNG magic bytes padded to exactly `size` bytes."""
    return PNG[:8] + b"\x00" * (size - 8)


async def upload(
    client: httpx2.AsyncClient,
    project_id: str,
    data: bytes = PNG,
    filename: str = "slide.png",
    mime: str = "image/png",
    transcript_id: str | None = None,
) -> httpx2.Response:
    form = {"transcript_id": transcript_id} if transcript_id else None
    return await client.post(
        f"/api/projects/{project_id}/screenshots",
        files={"file": (filename, data, mime)},
        data=form,
    )


async def create_project(client: httpx2.AsyncClient, name: str = "Notes") -> dict[str, Any]:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def unzip(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert archive.testzip() is None
        return {name: archive.read(name) for name in archive.namelist()}
