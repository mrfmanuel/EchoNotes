"""Upload validation: accepted audio types and size-capped reading (US-05 AC2/AC3)."""

from dataclasses import dataclass
from typing import Protocol

from fastapi import status

from app.errors import ApiError

MIB = 1024 * 1024
READ_CHUNK_BYTES = MIB

# Extension → content type sent to the provider.
AUDIO_EXTENSIONS: dict[str, str] = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "webm": "audio/webm",
}
# Accepted part content types (parameters such as `;codecs=opus` are ignored) → extension.
AUDIO_CONTENT_TYPES: dict[str, str] = {
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
    "video/webm": "webm",
}
DEFAULT_AUDIO_BASENAME = "audio"


class AsyncReadable(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True)
class AudioType:
    """What the provider receives: a filename with a known extension and its content type."""

    filename: str
    content_type: str


def basename(filename: str | None) -> str:
    """The last path component of a client-supplied filename (browsers may send paths)."""
    return (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()


def split_extension(name: str) -> tuple[str, str]:
    """`("lecture", "m4a")` for `lecture.m4a`; the extension is lowercased, `""` if absent."""
    stem, dot, extension = name.rpartition(".")
    if not dot:
        return name, ""
    return stem, extension.lower()


def _media_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def resolve_audio_type(filename: str | None, content_type: str | None) -> AudioType:
    """Accept by extension (case-insensitive), else by an audio content type; else 415."""
    name = basename(filename)
    stem, extension = split_extension(name)
    if extension in AUDIO_EXTENSIONS:
        return AudioType(name, AUDIO_EXTENSIONS[extension])
    media_type = _media_type(content_type)
    if media_type in AUDIO_CONTENT_TYPES:
        extension = AUDIO_CONTENT_TYPES[media_type]
        return AudioType(f"{name or DEFAULT_AUDIO_BASENAME}.{extension}", media_type)
    raise ApiError(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "Unsupported audio type. Use mp3, wav, m4a, ogg or webm.",
        "unsupported_media_type",
    )


def require_non_empty(audio: bytes) -> bytes:
    if not audio:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The audio file is empty.", "validation_error"
        )
    return audio


async def read_capped(upload: AsyncReadable, max_bytes: int) -> bytes:
    """Read the whole upload into memory, stopping at `max_bytes + 1` bytes (→ 413)."""
    buffer = bytearray()
    try:
        while len(buffer) <= max_bytes:
            chunk = await upload.read(min(READ_CHUNK_BYTES, max_bytes + 1 - len(buffer)))
            if not chunk:
                break
            buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise ApiError(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"Audio file is larger than {max_bytes // MIB} MB.",
                "audio_too_large",
            )
        return bytes(buffer)
    finally:
        buffer.clear()
