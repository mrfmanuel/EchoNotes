#!/usr/bin/env python3
"""Recovery checks after a fix was rebuilt (called by verify-recovery.sh). Stdlib only.

1. /api/health answers 200 and reports the expected (fixed) commit.
2. Fresh traffic with the same mix that triggered the incident: the HTTP failure ratio (5xx) of
   these requests is below the threshold.
3. Prometheus (through the Grafana proxy) saw those requests: the failure ratio of the counter
   DELTA (after - before, so the incident's old failures do not count) is below the threshold.
4. Optional, non-fatal: the Grafana alert rule returns to Normal within --alert-wait seconds.

Prints a Markdown section; exit code 0 only if checks 1-3 pass.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import traffic  # noqa: E402

FAILED = {"provider_error", "timeout", "server_error"}
ALERT_TITLE = "EchoNotes transcription failure ratio high"
COUNTER_QUERY = "sum by (status) (echonotes_transcriptions_total)"


def _get(url: str, auth: str | None = None) -> tuple[int, Any]:
    headers = {"Authorization": auth} if auth else {}
    try:
        with urllib.request.urlopen(  # noqa: S310 - local URLs only
            urllib.request.Request(url, headers=headers), timeout=10
        ) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
        return 0, None


class Grafana:
    def __init__(self) -> None:
        port = os.environ.get("GRAFANA_PORT", "3001")
        self.url = (os.environ.get("GRAFANA_URL") or f"http://localhost:{port}").rstrip("/")
        user = os.environ.get("GRAFANA_USER", "admin")
        password = os.environ.get("GRAFANA_PASSWORD", "admin")
        self.auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()

    def counters(self) -> dict[str, float] | None:
        query = urllib.parse.urlencode({"query": COUNTER_QUERY})
        status, body = _get(
            f"{self.url}/api/datasources/proxy/uid/prometheus/api/v1/query?{query}", self.auth
        )
        if status != 200 or not isinstance(body, dict):
            return None
        return {
            item["metric"].get("status", ""): float(item["value"][1])
            for item in body.get("data", {}).get("result", [])
        }

    def alert_state(self) -> str | None:
        status, body = _get(f"{self.url}/api/prometheus/grafana/api/v1/rules", self.auth)
        if status != 200 or not isinstance(body, dict):
            return None
        for group in body.get("data", {}).get("groups", []):
            for rule in group.get("rules", []):
                if rule.get("name") == ALERT_TITLE:
                    return str(rule.get("state"))
        return None


def delta(before: dict[str, float], after: dict[str, float]) -> tuple[float, float]:
    """(total, failed) increase between two counter snapshots, by status."""
    total = failed = 0.0
    for status in set(before) | set(after):
        diff = max(0.0, after.get(status, 0.0) - before.get(status, 0.0))
        total += diff
        if status in FAILED:
            failed += diff
    return total, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--expect-commit", default="")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.2)
    parser.add_argument("--health-timeout", type=int, default=180)
    parser.add_argument("--metrics-timeout", type=int, default=120)
    parser.add_argument("--alert-wait", type=int, default=0)
    args = parser.parse_args(argv)
    base = args.app_url.rstrip("/")
    ok = True
    out = ["## Recovery checks", "", "| Check | Result | Detail |", "|---|---|---|"]

    def row(name: str, passed: bool | None, detail: str) -> None:
        mark = "PASS" if passed else "FAIL" if passed is False else "INFO"
        out.append(f"| {name} | {mark} | {detail} |")
        print(f"{mark}  {name}: {detail}", file=sys.stderr, flush=True)

    # 1. health + commit
    deadline, commit, code = time.monotonic() + args.health_timeout, "", 0
    while time.monotonic() < deadline:
        code, body = _get(f"{base}/api/health")
        commit = (body or {}).get("commit", "") if isinstance(body, dict) else ""
        if code == 200 and (not args.expect_commit or commit == args.expect_commit):
            break
        time.sleep(3)
    healthy = code == 200 and (not args.expect_commit or commit == args.expect_commit)
    row("health_and_commit", healthy, f"HTTP {code}, commit `{commit[:12]}`")
    ok &= healthy

    grafana = Grafana()
    before = grafana.counters()

    # 2. fresh traffic, HTTP level
    summary = traffic.run(base, args.requests, interval=0.1)
    ratio = float(summary.get("failure_ratio", 1.0)) if "error" not in summary else 1.0
    http_ok = "error" not in summary and ratio < args.threshold
    row(
        "http_failure_ratio",
        http_ok,
        f"{summary.get('failed_5xx')}/{summary.get('uploads')} 5xx = {ratio}"
        f" (threshold {args.threshold}); by kind {summary.get('by_kind')}",
    )
    ok &= http_ok

    # 3. Prometheus counter delta
    if before is None:
        row("prometheus_failure_ratio", False, "Prometheus not reachable through Grafana")
        ok = False
    else:
        deadline, total, failed = time.monotonic() + args.metrics_timeout, 0.0, 0.0
        while time.monotonic() < deadline:
            after = grafana.counters() or {}
            total, failed = delta(before, after)
            if total >= args.requests:
                break
            time.sleep(5)
        prom_ratio = round(failed / total, 3) if total else None
        prom_ok = total >= args.requests and prom_ratio is not None and prom_ratio < args.threshold
        row(
            "prometheus_failure_ratio",
            prom_ok,
            f"delta {failed:.0f} failed / {total:.0f} total = {prom_ratio}",
        )
        ok &= prom_ok

    # 4. alert back to Normal (informational)
    if args.alert_wait > 0:
        deadline, state = time.monotonic() + args.alert_wait, None
        while time.monotonic() < deadline:
            state = grafana.alert_state()
            if state in {"inactive", "normal", "Normal"}:
                break
            time.sleep(10)
        row("alert_back_to_normal", None, f"Grafana rule state: {state}")

    print("\n".join(out))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
