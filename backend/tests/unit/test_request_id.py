"""#35 X-Request-ID middleware and the access log."""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator

import httpx2
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from tests.log_utils import access_lines, parse_json_logs

pytestmark = pytest.mark.anyio

MARKER = "SECRET-TITLE-123"
handler_logger = logging.getLogger("app.test.handler")


class Item(BaseModel):
    name: str
    size: int


@pytest.fixture
def routed_app(app: FastAPI) -> FastAPI:
    """The real app plus a few probe routes."""

    @app.get("/api/items/{item_id}")
    async def get_item(item_id: str) -> dict[str, str]:
        handler_logger.info("handling item")
        return {"id": item_id}

    @app.post("/api/items")
    async def create_item(item: Item) -> dict[str, int]:
        return {"size": item.size}

    @app.get("/api/boom")
    async def boom() -> None:
        raise RuntimeError(MARKER)

    @app.get("/api/wait/{name}")
    async def wait(name: str) -> dict[str, str]:
        handler_logger.info("before wait")
        await asyncio.sleep(0.05)
        handler_logger.info("after wait")
        return {"name": name}

    return app


@pytest.fixture
async def probe(
    routed_app: FastAPI, capsys: pytest.CaptureFixture[str]
) -> AsyncIterator[httpx2.AsyncClient]:
    capsys.readouterr()
    transport = httpx2.ASGITransport(app=routed_app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _is_uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4
    except ValueError:
        return False


async def test_incoming_request_id_is_echoed_and_used_in_every_log_record(
    probe: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    response = await probe.get("/api/items/42", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"
    records = parse_json_logs(capsys.readouterr().out)
    assert len(records) == 2  # handler line + access line
    assert all(r["request_id"] == "abc-123" for r in records)


@pytest.mark.parametrize("header", [None, "", "x" * 129, "bad id!", "a/b", "ok;drop"])
async def test_missing_or_invalid_request_id_gets_a_new_uuid4(
    probe: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str], header: str | None
) -> None:
    headers = {} if header is None else {"X-Request-ID": header}

    response = await probe.get("/api/items/1", headers=headers)

    request_id = response.headers["X-Request-ID"]
    assert _is_uuid4(request_id)
    assert request_id != header
    records = parse_json_logs(capsys.readouterr().out)
    assert records and all(r["request_id"] == request_id for r in records)


async def test_request_id_of_128_allowed_chars_is_accepted(probe: httpx2.AsyncClient) -> None:
    value = "Ab0._-" * 21 + "xy"

    response = await probe.get("/api/items/1", headers={"X-Request-ID": value})

    assert len(value) == 128
    assert response.headers["X-Request-ID"] == value


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("GET", "/does-not-exist", 404),
        ("POST", "/api/items", 422),
        ("GET", "/api/boom", 500),
    ],
)
async def test_request_id_header_is_on_error_responses(
    probe: httpx2.AsyncClient, method: str, path: str, status: int
) -> None:
    response = await probe.request(method, path, json={"bad": True}, headers={"X-Request-ID": "e1"})

    assert response.status_code == status
    assert response.headers["X-Request-ID"] == "e1"


async def test_unhandled_exception_returns_json_500_and_logs_class_only(
    probe: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    response = await probe.get("/api/boom", headers={"X-Request-ID": "boom-1"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    output = capsys.readouterr().out
    assert MARKER not in output
    records = parse_json_logs(output)
    errors = [r for r in records if r["logger"] == "app.error"]
    assert len(errors) == 1
    assert errors[0]["exc_type"] == "RuntimeError"
    assert errors[0]["request_id"] == "boom-1"
    (access,) = access_lines(records)
    assert access["status"] == 500


async def test_concurrent_requests_keep_their_own_request_id(
    probe: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = await asyncio.gather(
        probe.get("/api/wait/one", headers={"X-Request-ID": "req-one"}),
        probe.get("/api/wait/two", headers={"X-Request-ID": "req-two"}),
    )

    assert first.headers["X-Request-ID"] == "req-one"
    assert second.headers["X-Request-ID"] == "req-two"
    records = parse_json_logs(capsys.readouterr().out)
    assert len(records) == 6
    for request_id in ("req-one", "req-two"):
        assert len([r for r in records if r["request_id"] == request_id]) == 3


async def test_exactly_one_access_line_with_route_template_status_and_duration(
    probe: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    await probe.get("/api/items/42?name=x", headers={"X-Request-ID": "acc-1"})

    (line,) = access_lines(parse_json_logs(capsys.readouterr().out))
    assert line["method"] == "GET"
    assert line["route"] == "/api/items/{item_id}"
    assert line["status"] == 200
    assert isinstance(line["duration_ms"], int | float) and line["duration_ms"] >= 0
    assert line["request_id"] == "acc-1"


async def test_access_line_for_unmatched_route_uses_path_without_query(
    probe: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    await probe.get("/nope/here?token=abc")

    (line,) = access_lines(parse_json_logs(capsys.readouterr().out))
    assert line["route"] == "/nope/here"
    assert line["status"] == 404


async def test_health_access_line_uses_route_template(
    probe: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    await probe.get("/api/health")

    (line,) = access_lines(parse_json_logs(capsys.readouterr().out))
    assert line["route"] == "/api/health"
    assert line["status"] == 200


async def test_sensitive_values_in_query_body_and_headers_are_never_logged(
    probe: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    await probe.get(f"/api/items/1?name={MARKER}", headers={"Authorization": MARKER})
    await probe.post("/api/items", json={"name": MARKER, "size": 1})
    await probe.post("/api/items", json={"name": MARKER, "size": "not-a-number"})
    await probe.post(
        "/api/items", files={"file": (f"{MARKER}.png", b"bytes-" + MARKER.encode(), "image/png")}
    )

    output = capsys.readouterr().out
    assert len(access_lines(parse_json_logs(output))) == 4
    assert MARKER not in output
