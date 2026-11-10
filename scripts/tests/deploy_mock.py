"""Tiny mock of a Render deploy hook + an EchoNotes /api/health, for scripts/tests/test_deploy.sh.

Usage: python deploy_mock.py <port-file>
Binds 127.0.0.1 on a free port (port 0) and writes the chosen port to <port-file>.

Endpoints:
  POST|GET /hook?key=K&ref=SHA   behaves according to the current scenario
  GET      /api/health           {"status","database","version","commit","environment"}
  POST     /_reset?...           set a scenario (query params below), resets counters
  GET      /_state               JSON with counters (hook_calls, health_calls, last_ref, ...)
  POST     /_shutdown            stop the server

Scenario params for /_reset:
  key=K            the only accepted hook key (another key -> 404)
  busy=N           answer 202 to the first N hook calls, then 200
  hook_status=C    force this status for every (non-busy) hook call, e.g. 404 or 500
  flip_after=N     health keeps reporting `initial` for N health calls after a 200 hook call,
                   then reports the requested ref; -1 = never flips (timeout scenario)
  fail_first=N     the first N health calls after the hook answer 503 (rebuild / cold start)
  initial=SHA      commit reported before the deploy ("" = field missing, like pre-#47 code)
  env=dev          `environment` reported by health ("" = field missing)
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

STATE: dict[str, object] = {}
LOCK = threading.Lock()


def reset(params: dict[str, str]) -> None:
    STATE.clear()
    STATE.update(
        key=params.get("key", "testkey"),
        busy=int(params.get("busy", "0")),
        hook_status=int(params.get("hook_status", "0")),
        flip_after=int(params.get("flip_after", "1")),
        fail_first=int(params.get("fail_first", "0")),
        current=params.get("initial", "a" * 40),
        env=params.get("env", "dev"),
        target=None,
        hook_calls=0,
        health_calls=0,
        health_after_hook=0,
        last_ref=None,
        deploys=0,
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # keep the test output clean
        return

    def _send(self, code: int, body: object | None = None) -> None:
        data = b"" if body is None else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _params(self) -> tuple[str, dict[str, str]]:
        url = urlparse(self.path)
        return url.path, {k: v[-1] for k, v in parse_qs(url.query, keep_blank_values=True).items()}

    def _drain(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

    def _hook(self, params: dict[str, str]) -> None:
        with LOCK:
            STATE["hook_calls"] = int(STATE["hook_calls"]) + 1
            STATE["last_ref"] = params.get("ref")
            if params.get("key") != STATE["key"]:
                return self._send(404, {"message": "not found"})
            if int(STATE["busy"]) > 0:
                STATE["busy"] = int(STATE["busy"]) - 1
                return self._send(202)
            if int(STATE["hook_status"]):
                return self._send(int(STATE["hook_status"]), {"message": "forced"})
            STATE["target"] = params.get("ref")
            STATE["health_after_hook"] = 0
            STATE["deploys"] = int(STATE["deploys"]) + 1
            return self._send(200, {"deploy": {"id": f"dep-mock{STATE['deploys']}"}})

    def _health(self) -> None:
        with LOCK:
            STATE["health_calls"] = int(STATE["health_calls"]) + 1
            if STATE["target"] is not None:
                STATE["health_after_hook"] = int(STATE["health_after_hook"]) + 1
                seen = int(STATE["health_after_hook"])
                if seen <= int(STATE["fail_first"]):
                    return self._send(503, {"detail": "rebuilding"})
                flip = int(STATE["flip_after"])
                if flip >= 0 and seen > flip:
                    STATE["current"] = STATE["target"]
            body: dict[str, object] = {"status": "ok", "database": "ok", "version": "0.0.0"}
            if STATE["current"]:
                body["commit"] = STATE["current"]
            if STATE["env"]:
                body["environment"] = STATE["env"]
            return self._send(200, body)

    def do_GET(self) -> None:  # noqa: N802
        path, params = self._params()
        if path == "/hook":
            return self._hook(params)
        if path == "/api/health":
            return self._health()
        if path == "/_state":
            with LOCK:
                return self._send(200, dict(STATE))
        return self._send(404, {"detail": "Not Found"})

    def do_POST(self) -> None:  # noqa: N802
        self._drain()
        path, params = self._params()
        if path == "/hook":
            return self._hook(params)
        if path == "/_reset":
            with LOCK:
                reset(params)
            return self._send(200, {"ok": True})
        if path == "/_shutdown":
            self._send(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        return self._send(404, {"detail": "Not Found"})


def main() -> None:
    reset({})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        fh.write(str(server.server_address[1]))
    server.serve_forever()


if __name__ == "__main__":
    main()
