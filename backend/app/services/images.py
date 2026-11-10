"""Image upload validation (US-12): bounded reads and type detection by magic bytes."""

from fastapi import status

from app.errors import ApiError
from app.services.uploads import MIB, AsyncReadable, basename

READ_CHUNK_BYTES = 64 * 1024

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
RIFF_SIGNATURE = b"RIFF"
WEBP_SIGNATURE = b"WEBP"

# Stored content type -> file extension used in exports.
IMAGE_EXTENSIONS: dict[str, str] = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
MAX_FILENAME_LENGTH = 255


def detect_image_type(data: bytes) -> str | None:
    """`image/png`, `image/jpeg` or `image/webp` from the file's magic bytes, else `None`.

    The client's filename and MIME type are never trusted.
    """
    if data.startswith(PNG_SIGNATURE):
        return "image/png"
    if data.startswith(JPEG_SIGNATURE):
        return "image/jpeg"
    if data.startswith(RIFF_SIGNATURE) and data[8:12] == WEBP_SIGNATURE:
        return "image/webp"
    return None


def image_too_large(max_bytes: int) -> ApiError:
    return ApiError(
        status.HTTP_413_CONTENT_TOO_LARGE,
        f"Image exceeds the {max_bytes // MIB} MB limit",
        "image_too_large",
    )


def unsupported_image() -> ApiError:
    return ApiError(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "Only png, jpeg and webp images are allowed",
        "unsupported_media_type",
    )


async def read_limited(source: AsyncReadable, max_bytes: int) -> bytes:
    """Read `source` in chunks; raise 413 `image_too_large` as soon as it exceeds `max_bytes`."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await source.read(READ_CHUNK_BYTES):
        total += len(chunk)
        if total > max_bytes:
            raise image_too_large(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


async def read_image(source: AsyncReadable, max_bytes: int) -> tuple[bytes, str]:
    """Bytes and the content type detected from them; 413 / 415 errors otherwise."""
    data = await read_limited(source, max_bytes)
    content_type = detect_image_type(data)
    if content_type is None:
        raise unsupported_image()
    return data, content_type


def clean_filename(filename: str | None, content_type: str) -> str:
    """Base name of the client's filename (no directories), at most 255 chars.

    Falls back to `screenshot.<ext>` when the client sends no usable name (e.g. a paste).
    """
    name = basename(filename)
    if not name:
        name = f"screenshot.{IMAGE_EXTENSIONS[content_type]}"
    return name[:MAX_FILENAME_LENGTH]
