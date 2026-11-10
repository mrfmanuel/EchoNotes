"""#12 upload validation: accepted audio types, size-capped reading, default titles."""

import pytest

from app.errors import ApiError
from app.services.transcriptions import default_title, resolve_title
from app.services.uploads import AudioType, read_capped, require_non_empty, resolve_audio_type

pytestmark = pytest.mark.anyio


class CountingStream:
    """An endless upload that records how many bytes were read."""

    def __init__(self, total: int) -> None:
        self.remaining = total
        self.bytes_read = 0

    async def read(self, size: int = -1) -> bytes:
        n = self.remaining if size < 0 else min(size, self.remaining)
        self.remaining -= n
        self.bytes_read += n
        return b"a" * n


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("talk.mp3", AudioType("talk.mp3", "audio/mpeg")),
        ("TALK.WAV", AudioType("TALK.WAV", "audio/wav")),
        ("talk.M4a", AudioType("talk.M4a", "audio/mp4")),
        ("talk.ogg", AudioType("talk.ogg", "audio/ogg")),
        ("talk.webm", AudioType("talk.webm", "audio/webm")),
        ("C:\\Users\\me\\talk.mp3", AudioType("talk.mp3", "audio/mpeg")),
    ],
)
def test_supported_extension_is_accepted_case_insensitively(
    filename: str, expected: AudioType
) -> None:
    assert resolve_audio_type(filename, "application/octet-stream") == expected


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("blob", "audio/webm;codecs=opus", AudioType("blob.webm", "audio/webm")),
        ("recording", "video/webm", AudioType("recording.webm", "video/webm")),
        ("", "audio/ogg; codecs=opus", AudioType("audio.ogg", "audio/ogg")),
        ("voice.note", "AUDIO/MPEG", AudioType("voice.note.mp3", "audio/mpeg")),
        ("x", "audio/x-wav", AudioType("x.wav", "audio/x-wav")),
        ("x", "audio/x-m4a", AudioType("x.m4a", "audio/x-m4a")),
        ("x", "audio/mp4", AudioType("x.m4a", "audio/mp4")),
        ("x", "audio/wav", AudioType("x.wav", "audio/wav")),
    ],
)
def test_missing_or_unknown_extension_falls_back_to_audio_content_type(
    filename: str, content_type: str, expected: AudioType
) -> None:
    assert resolve_audio_type(filename, content_type) == expected


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("notes.txt", "text/plain"),
        ("photo.png", "image/png"),
        ("song.flac", "audio/flac"),
        ("blob", None),
        ("blob", "application/octet-stream"),
    ],
)
def test_other_types_are_rejected_with_415(filename: str, content_type: str | None) -> None:
    with pytest.raises(ApiError) as info:
        resolve_audio_type(filename, content_type)

    assert (info.value.status_code, info.value.code) == (415, "unsupported_media_type")


async def test_read_capped_returns_bytes_up_to_the_limit() -> None:
    stream = CountingStream(1000)

    assert await read_capped(stream, 1000) == b"a" * 1000


async def test_read_capped_stops_at_limit_plus_one_byte_and_raises_413() -> None:
    stream = CountingStream(10 * 1024 * 1024)

    with pytest.raises(ApiError) as info:
        await read_capped(stream, 3 * 1024 * 1024)

    assert (info.value.status_code, info.value.code) == (413, "audio_too_large")
    assert stream.bytes_read == 3 * 1024 * 1024 + 1


def test_empty_audio_is_rejected_with_422() -> None:
    with pytest.raises(ApiError) as info:
        require_non_empty(b"")

    assert (info.value.status_code, info.value.code) == (422, "validation_error")


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Lecture 1.m4a", "Lecture 1"),
        ("archive.tar.mp3", "archive.tar"),
        ("blob", "blob"),
        (".mp3", "Untitled"),
        ("", "Untitled"),
        (None, "Untitled"),
        ("dir/sub/talk.ogg", "talk"),
        ("x" * 300 + ".mp3", "x" * 200),
    ],
)
def test_default_title_is_filename_without_extension(filename: str | None, expected: str) -> None:
    assert default_title(filename) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [("  My talk  ", "My talk"), ("   ", "talk"), (None, "talk"), ("", "talk")],
)
def test_title_is_trimmed_and_blank_falls_back_to_filename(
    title: str | None, expected: str
) -> None:
    assert resolve_title(title, "talk.mp3") == expected
