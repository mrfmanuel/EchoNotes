"""#14 / US-12: magic-byte detection, bounded reads and filename cleanup (pure functions)."""

import io

import pytest

from app.errors import ApiError
from app.services.images import (
    READ_CHUNK_BYTES,
    clean_filename,
    detect_image_type,
    read_image,
    read_limited,
)
from tests.image_utils import GIF, JPEG, MAX_IMAGE_BYTES, PNG, TEXT, WEBP, png_of_size

pytestmark = pytest.mark.anyio


class FakeUpload:
    """Async `read(size)` over in-memory bytes that records every requested chunk size."""

    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)
        self.requested: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.requested.append(size)
        return self._buffer.read(size)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        pytest.param(PNG, "image/png", id="png"),
        pytest.param(JPEG, "image/jpeg", id="jpeg"),
        pytest.param(WEBP, "image/webp", id="webp"),
    ],
)
def test_detect_image_type_accepts_png_jpeg_webp_by_magic_bytes(data: bytes, expected: str) -> None:
    assert detect_image_type(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(GIF, id="gif"),
        pytest.param(TEXT, id="text-named-png"),
        pytest.param(b"", id="empty"),
        pytest.param(b"RIFF\x00\x00\x00\x00WAVEfmt ", id="riff-wave-not-webp"),
        pytest.param(b"\x89PNG", id="truncated-png-signature"),
        pytest.param(b"\x00" + PNG, id="png-signature-not-at-start"),
    ],
)
def test_detect_image_type_rejects_other_content(data: bytes) -> None:
    assert detect_image_type(data) is None


async def test_read_limited_accepts_exactly_the_limit() -> None:
    data = await read_limited(FakeUpload(png_of_size(MAX_IMAGE_BYTES)), MAX_IMAGE_BYTES)

    assert len(data) == MAX_IMAGE_BYTES


async def test_read_limited_rejects_one_byte_over_the_limit_with_413() -> None:
    with pytest.raises(ApiError) as caught:
        await read_limited(FakeUpload(png_of_size(MAX_IMAGE_BYTES + 1)), MAX_IMAGE_BYTES)

    assert (caught.value.status_code, caught.value.code) == (413, "image_too_large")
    assert caught.value.detail == "Image exceeds the 5 MB limit"


async def test_read_limited_reads_in_bounded_chunks_and_stops_early() -> None:
    source = FakeUpload(png_of_size(4 * MAX_IMAGE_BYTES))

    with pytest.raises(ApiError):
        await read_limited(source, MAX_IMAGE_BYTES)

    assert set(source.requested) == {READ_CHUNK_BYTES}
    assert len(source.requested) <= MAX_IMAGE_BYTES // READ_CHUNK_BYTES + 1


async def test_read_image_rejects_non_image_bytes_with_415() -> None:
    with pytest.raises(ApiError) as caught:
        await read_image(FakeUpload(TEXT), MAX_IMAGE_BYTES)

    assert (caught.value.status_code, caught.value.code) == (415, "unsupported_media_type")


async def test_read_image_returns_bytes_and_detected_type() -> None:
    assert await read_image(FakeUpload(WEBP), MAX_IMAGE_BYTES) == (WEBP, "image/webp")


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        pytest.param("slide.png", "slide.png", id="plain"),
        pytest.param("C:\\Users\\me\\shot.png", "shot.png", id="windows-path"),
        pytest.param("../../etc/passwd.png", "passwd.png", id="posix-path"),
        pytest.param(None, "screenshot.jpg", id="missing"),
        pytest.param("   ", "screenshot.jpg", id="blank"),
    ],
)
def test_clean_filename_keeps_the_base_name_or_falls_back(
    filename: str | None, expected: str
) -> None:
    assert clean_filename(filename, "image/jpeg") == expected


def test_clean_filename_truncates_to_255_chars() -> None:
    assert len(clean_filename("a" * 300 + ".png", "image/png")) == 255
