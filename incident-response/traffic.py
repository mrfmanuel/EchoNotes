#!/usr/bin/env python3
"""Synthetic traffic for the key journey (upload audio -> transcript -> export), fake provider only.

Used by `test-incident.sh` (to make the alert fire) and `runbooks/verify-recovery.sh` (fresh
traffic after the fix). Stdlib only, so it runs with any Python 3.10+.

Traffic mix (deterministic, no randomness): 3 of every 5 uploads are a normal 1 s WAV voice
note; 2 of every 5 are "accidental taps", a WAV with a header and no samples (44 bytes), the
kind of clip a browser produces when the user hits record and stop immediately. Both are valid
uploads that `main` transcribes with 201.

Privacy: prints only counts, HTTP status codes and timings. Never response bodies or text.
Usage:
  python incident-response/traffic.py --base-url http://localhost:8001 --requests 20
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave
from collections import Counter
from datetime import UTC, datetime

NORMAL_SECONDS = 1
SAMPLE_RATE = 16000
SHORT_PATTERN = (1, 3)  # positions (mod 5) that send an accidental tap -> 40 % of uploads


def make_wav(seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(b"\x00\x00" * int(SAMPLE_RATE * seconds))
    return buffer.getvalue()


def is_short(index: int) -> bool:
    return index % 5 in SHORT_PATTERN


def _request(
    method: str, url: str, body: bytes | None = None, headers: dict[str, str] | None = None
) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - local URL only
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0, b""


def _multipart(filename: str, audio: bytes, language: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: audio/wav\r\n\r\n".encode(),
        audio,
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="language"\r\n\r\n'
        f"{language}\r\n--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def run(base_url: str, requests: int, interval: float) -> dict[str, object]:
    base = base_url.rstrip("/")
    name = f"incident-traffic-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    status, body = _request(
        "POST",
        f"{base}/api/projects",
        json.dumps({"name": name}).encode(),
        {"Content-Type": "application/json"},
    )
    if status != 201:
        return {"error": f"create project HTTP {status}", "uploads": 0}
    project_id = json.loads(body)["id"]
    normal, tap = make_wav(NORMAL_SECONDS), make_wav(0)
    by_status: Counter[str] = Counter()
    by_kind: dict[str, Counter[str]] = {"normal": Counter(), "short": Counter()}
    started = time.monotonic()
    try:
        for index in range(requests):
            kind = "short" if is_short(index) else "normal"
            payload, content_type = _multipart(
                f"{kind}-{index}.wav", tap if kind == "short" else normal, "en"
            )
            code, _ = _request(
                "POST",
                f"{base}/api/projects/{project_id}/transcriptions",
                payload,
                {"Content-Type": content_type},
            )
            by_status[str(code)] += 1
            by_kind[kind][str(code)] += 1
            if interval:
                time.sleep(interval)
        export_status, _ = _request("GET", f"{base}/api/projects/{project_id}/export")
    finally:
        delete_status, _ = _request("DELETE", f"{base}/api/projects/{project_id}")
    failed = sum(n for code, n in by_status.items() if code == "0" or code.startswith("5"))
    return {
        "uploads": requests,
        "by_status": dict(by_status),
        "by_kind": {kind: dict(counts) for kind, counts in by_kind.items()},
        "failed_5xx": failed,
        "failure_ratio": round(failed / requests, 3) if requests else 0.0,
        "export_status": export_status,
        "cleanup_status": delete_status,
        "seconds": round(time.monotonic() - started, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--interval", type=float, default=0.2, help="seconds between uploads")
    args = parser.parse_args(argv)
    summary = run(args.base_url, args.requests, args.interval)
    print(json.dumps(summary))
    return 1 if "error" in summary else 0


if __name__ == "__main__":
    sys.exit(main())
