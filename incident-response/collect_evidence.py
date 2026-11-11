#!/usr/bin/env python3
"""Collect a bounded, read-only, allowlisted evidence packet for one incident -> evidence.json.

Runs BEFORE any model is involved. Every source is a fixed query (no free-form input from the
alert or the model reaches a query string), every HTTP call is a GET with a short timeout and a
response size cap, and the packet is scrubbed (allowlisted fields + secret patterns) before it
is written.

Sources
  - app:        GET {APP_URL}/api/health                      -> deployed version/commit/env
  - prometheus: Grafana datasource proxy uid `prometheus`      -> failure ratio, by status, p95
  - loki:       Grafana datasource proxy uid `loki`            -> last N (<= 50) error lines
  - tempo:      Grafana datasource proxy uid `tempo`           -> 1-3 failing traces
  - container:  `docker compose -p <project> logs app` (only if Loki returned nothing)
  - git:        recent commits up to the deployed commit and the files it touched

Environment (all optional):
  APP_URL            default http://localhost:${APP_PORT:-8001}
  GRAFANA_URL        default http://localhost:${GRAFANA_PORT:-3001}
  GRAFANA_USER / GRAFANA_PASSWORD   default admin / admin (local stack only)
  COMPOSE_PROJECT    default echonotes-incident
  EVIDENCE_WINDOW_MINUTES  default 15
  EVIDENCE_LOKI_QUERY      LogQL tried first (the documented "API error logs" query)

Usage:
  python incident-response/collect_evidence.py --incident-id INC-x --out path/evidence.json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HTTP_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_LOG_LINES = 50
MAX_TRACES = 3
MAX_STACK_CHARS = 4000
MAX_FULL_STACKS = 5
MAX_SPANS_PER_TRACE = 40
SERVICE = "echonotes-api"

# The ONLY HTTP paths this script may call (Grafana datasource proxy + the app health check).
ALLOWED_GRAFANA_PATHS = (
    "/api/datasources/proxy/uid/prometheus/api/v1/query",
    "/api/datasources/proxy/uid/loki/loki/api/v1/query_range",
    "/api/datasources/proxy/uid/tempo/api/search",
    "/api/datasources/proxy/uid/tempo/api/traces/",
)

FAILED = 'status=~"provider_error|timeout|server_error"'
PROM_QUERIES: dict[str, str] = {
    # `or vector(0)`: the numerator is empty (not 0) when nothing failed.
    "failure_ratio_2m": (
        f"(sum(increase(echonotes_transcriptions_total{{{FAILED}}}[2m])) or vector(0))"
        " / sum(increase(echonotes_transcriptions_total[2m]))"
    ),
    "transcriptions_by_status_5m": (
        "sum by (provider, status) (increase(echonotes_transcriptions_total[5m]))"
    ),
    "transcription_p95_seconds_5m": (
        "histogram_quantile(0.95, sum by (le) "
        "(rate(echonotes_transcription_duration_seconds_bucket[5m])))"
    ),
    "exports_by_status_5m": "sum by (status) (increase(echonotes_exports_total[5m]))",
    "deployed_revision": (
        f'max by (vcs_ref_head_revision, service_version) (target_info{{service_name="{SERVICE}"}})'
    ),
}
# Index labels are only service_name/deployment_environment*; severity_text, trace_id, exc_type,
# stack_trace ... are structured metadata (filter after the selector, no `| json`; OTLP maps
# CRITICAL to FATAL). Verified by #29 in grafana/otel-lgtm:0.40.0.
LOKI_FALLBACK_QUERIES = (
    f'{{service_name="{SERVICE}"}} | severity_text=~"ERROR|FATAL"',
    f'{{service_name="{SERVICE}"}} | detected_level="error"',
)
TEMPO_TRACEQL = (
    f'{{resource.service.name="{SERVICE}" && name="transcription.create" && status=error}}'
)

# --- scrubbing ---------------------------------------------------------------------------------

# Fields kept from a log record (after normalising `.` to `_`). Everything else is dropped.
LOG_FIELDS = frozenset(
    {
        "timestamp",
        "level",
        "severity_text",
        "detected_level",
        "logger",
        "scope_name",
        "message",
        "exc_type",
        "exception_type",
        "stack_trace",
        "exception_stacktrace",
        "trace_id",
        "span_id",
        "request_id",
        "method",
        "route",
        "status",
        "status_code",
        "duration_ms",
        "provider",
        "size_bytes",
        "project_id",
        "transcript_id",
        "code_filepath",
        "code_file_path",
        "code_lineno",
        "code_line_number",
        "code_function",
        "code_function_name",
    }
)
SPAN_ATTR_EXACT = frozenset(
    {
        "http.route",
        "http.method",
        "http.request.method",
        "http.status_code",
        "http.response.status_code",
        "error.type",
        "exception.type",
        "exception.stacktrace",
        "exception.escaped",
        "db.system",
        "db.operation",
        "db.operation.name",
    }
)
SPAN_ATTR_PREFIXES = ("echonotes.", "code.")
# Keys that are dropped wherever they appear (user content, credentials).
DENIED_KEYS = frozenset(
    {
        "text",
        "title",
        "filename",
        "source_filename",
        "body",
        "exception.message",
        "exception_message",
        "authorization",
        "cookie",
        "password",
        "api_key",
        "groq_api_key",
        "database_url",
        "db.statement",
        "url.full",
        "url.query",
        "http.url",
        "http.target",
    }
)
SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"gsk_[A-Za-z0-9]{10,}"), "[REDACTED_GROQ_KEY]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"), "[REDACTED_ANTHROPIC_KEY]"),
    (re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"rnd_[A-Za-z0-9]{16,}"), "[REDACTED_RENDER_KEY]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED]@"),
    (
        re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd)\s*[=:]\s*[^\s,;\"']+"),
        r"\1=[REDACTED]",
    ),
)


def scrub_text(value: str) -> str:
    for pattern, replacement in SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def scrub(obj: Any) -> Any:
    """Recursively drop denied keys and redact secret-looking substrings."""
    if isinstance(obj, dict):
        return {
            key: scrub(value)
            for key, value in obj.items()
            if not (isinstance(key, str) and key.lower() in DENIED_KEYS)
        }
    if isinstance(obj, list):
        return [scrub(item) for item in obj]
    if isinstance(obj, str):
        return scrub_text(obj)
    return obj


def _norm_key(key: str) -> str:
    return key.replace(".", "_").replace("-", "_").lower()


def allowlisted_log(record: dict[str, Any]) -> dict[str, Any]:
    """Only LOG_FIELDS survive; stack traces are truncated."""
    kept: dict[str, Any] = {}
    for key, value in record.items():
        norm = _norm_key(str(key))
        if norm in LOG_FIELDS and value not in (None, ""):
            kept[norm] = value
    for key in ("stack_trace", "exception_stacktrace"):
        if isinstance(kept.get(key), str) and len(kept[key]) > MAX_STACK_CHARS:
            kept[key] = "...(truncated)\n" + kept[key][-MAX_STACK_CHARS:]
    return kept


def allowlisted_span_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in attrs.items()
        if key in SPAN_ATTR_EXACT or key.startswith(SPAN_ATTR_PREFIXES)
    }


# --- parsers (pure; unit tested with canned responses) -------------------------------------------


def parse_prometheus(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("data", {}).get("result", [])
    series = []
    for item in result if isinstance(result, list) else []:
        value = item.get("value", [None, None])[1]
        try:
            number: float | None = float(value)
        except (TypeError, ValueError):
            number = None
        if number is not None and number != number:  # NaN (0/0 when there is no traffic)
            number = None
        series.append({"labels": item.get("metric", {}), "value": number})
    return series


def parse_loki(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Loki query_range streams -> allowlisted records, newest first."""
    records: list[tuple[int, dict[str, Any]]] = []
    for stream in payload.get("data", {}).get("result", []) or []:
        labels = stream.get("stream", {}) or {}
        for ts, line, *extra in stream.get("values", []) or []:
            record: dict[str, Any] = dict(labels)
            if extra and isinstance(extra[0], dict):  # categorized structured metadata
                for group in extra[0].values():
                    if isinstance(group, dict):
                        record.update(group)
            try:
                parsed = json.loads(line)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                record.update(parsed)
            else:
                record["message"] = line
            record.setdefault("timestamp", datetime.fromtimestamp(int(ts) / 1e9, UTC).isoformat())
            records.append((int(ts), allowlisted_log(record)))
    records.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _ts, record in records[:MAX_LOG_LINES]]


def parse_container_logs(text: str) -> list[dict[str, Any]]:
    """`docker compose logs` output (prefix `app-1  | {json}`) -> allowlisted ERROR records."""
    records = []
    for raw in text.splitlines():
        start = raw.find("{")
        if start < 0:
            continue
        try:
            parsed = json.loads(raw[start:])
        except ValueError:
            continue
        if isinstance(parsed, dict) and str(parsed.get("level", "")).upper() in {
            "ERROR",
            "CRITICAL",
        }:
            records.append(allowlisted_log(parsed))
    return list(reversed(records))[:MAX_LOG_LINES]


def limit_stacks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first MAX_FULL_STACKS distinct stack traces; later duplicates are dropped."""
    seen: set[str] = set()
    out = []
    for record in records:
        stack = record.get("stack_trace") or record.get("exception_stacktrace")
        if isinstance(stack, str):
            if stack in seen or len(seen) >= MAX_FULL_STACKS:
                record = {
                    k: v
                    for k, v in record.items()
                    if k not in ("stack_trace", "exception_stacktrace")
                }
                record["stack_trace_omitted"] = "duplicate" if stack in seen else "limit"
            else:
                seen.add(stack)
        out.append(record)
    return out


def _otlp_value(value: dict[str, Any]) -> Any:
    for kind in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if kind in value:
            return value[kind]
    return None


def _otlp_attrs(items: Iterable[dict[str, Any]] | None) -> dict[str, Any]:
    return {item.get("key", ""): _otlp_value(item.get("value", {})) for item in items or []}


def _hex_id(value: str | None) -> str | None:
    if not value:
        return None
    if re.fullmatch(r"[0-9a-fA-F]+", value):
        return value.lower()
    try:
        return base64.b64decode(value).hex()
    except ValueError:
        return None


def reduce_trace(trace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Tempo trace (OTLP JSON, `batches` or `resourceSpans`) -> small allowlisted summary."""
    spans = []
    for batch in payload.get("batches") or payload.get("resourceSpans") or []:
        scopes = batch.get("scopeSpans") or batch.get("instrumentationLibrarySpans") or []
        for scope in scopes:
            for span in scope.get("spans", []) or []:
                start = int(span.get("startTimeUnixNano", 0) or 0)
                end = int(span.get("endTimeUnixNano", 0) or 0)
                status = span.get("status", {}) or {}
                events = []
                for event in span.get("events", []) or []:
                    attrs = allowlisted_span_attrs(_otlp_attrs(event.get("attributes")))
                    events.append({"name": event.get("name"), "attributes": attrs})
                spans.append(
                    {
                        "span_id": _hex_id(span.get("spanId")),
                        "parent_span_id": _hex_id(span.get("parentSpanId")),
                        "name": span.get("name"),
                        "kind": span.get("kind"),
                        "status": status.get("code"),
                        "duration_ms": round((end - start) / 1e6, 2) if end >= start else None,
                        "attributes": allowlisted_span_attrs(_otlp_attrs(span.get("attributes"))),
                        "events": events,
                        "_start": start,
                    }
                )
    spans.sort(key=lambda s: s.pop("_start"))
    return {"trace_id": trace_id, "span_count": len(spans), "spans": spans[:MAX_SPANS_PER_TRACE]}


# --- collectors ----------------------------------------------------------------------------------

HttpGet = Callable[[str, dict[str, str] | None], tuple[int, Any]]


class Collector:
    def __init__(self, env: dict[str, str], http_get: HttpGet | None = None) -> None:
        self.app_url = env.get("APP_URL") or f"http://localhost:{env.get('APP_PORT', '8001')}"
        self.grafana_url = (
            env.get("GRAFANA_URL") or f"http://localhost:{env.get('GRAFANA_PORT', '3001')}"
        ).rstrip("/")
        user = env.get("GRAFANA_USER", "admin")
        password = env.get("GRAFANA_PASSWORD", "admin")
        self._auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self.compose_project = env.get("COMPOSE_PROJECT", "echonotes-incident")
        self.window_minutes = int(env.get("EVIDENCE_WINDOW_MINUTES", "15"))
        self.loki_query = env.get("EVIDENCE_LOKI_QUERY", "")
        self.http_get = http_get or self._http_get
        self.errors: list[str] = []
        self.sources: list[dict[str, Any]] = []

    # Every network call goes through here: GET only, timeout, size cap.
    def _http_get(self, url: str, headers: dict[str, str] | None) -> tuple[int, Any]:
        request = urllib.request.Request(url, method="GET", headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    return 0, {"error": "response too large"}
                return resp.status, json.loads(raw or b"null")
        except urllib.error.HTTPError as exc:
            return exc.code, None
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
            return 0, {"error": type(exc).__name__}

    def _grafana(self, path: str, params: dict[str, str] | None = None) -> Any:
        if not any(
            path == allowed or (allowed.endswith("/") and path.startswith(allowed))
            for allowed in ALLOWED_GRAFANA_PATHS
        ):
            raise ValueError(f"path not allowlisted: {path}")
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        status, body = self.http_get(
            f"{self.grafana_url}{path}{query}", {"Authorization": self._auth}
        )
        self.sources.append({"source": "grafana", "path": path, "status": status})
        if status != 200:
            self.errors.append(f"grafana {path}: HTTP {status}")
            return None
        return body

    def health(self) -> dict[str, Any]:
        status, body = self.http_get(f"{self.app_url.rstrip('/')}/api/health", None)
        self.sources.append({"source": "app", "path": "/api/health", "status": status})
        if not isinstance(body, dict):
            self.errors.append(f"app /api/health: HTTP {status}")
            return {"http_status": status}
        keep = ("status", "version", "database", "commit", "environment")
        return {"http_status": status, **{k: body.get(k) for k in keep}}

    def metrics(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, promql in PROM_QUERIES.items():
            body = self._grafana(
                "/api/datasources/proxy/uid/prometheus/api/v1/query", {"query": promql}
            )
            out[name] = {"query": promql, "series": parse_prometheus(body) if body else []}
        return out

    def logs(self) -> dict[str, Any]:
        end = time.time_ns()
        start = end - self.window_minutes * 60 * 10**9
        queries = [q for q in (self.loki_query, *LOKI_FALLBACK_QUERIES) if q]
        for logql in queries:
            body = self._grafana(
                "/api/datasources/proxy/uid/loki/loki/api/v1/query_range",
                {
                    "query": logql,
                    "start": str(start),
                    "end": str(end),
                    "limit": str(MAX_LOG_LINES),
                    "direction": "backward",
                },
            )
            lines = parse_loki(body) if isinstance(body, dict) else []
            if lines:
                return {"source": "loki", "query": logql, "lines": limit_stacks(lines)}
        return self.container_logs()

    def container_logs(self) -> dict[str, Any]:
        argv = [
            "docker",
            "compose",
            "-p",
            self.compose_project,
            "logs",
            "--no-color",
            "--since",
            f"{self.window_minutes}m",
            "app",
        ]
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.errors.append(f"container logs: {type(exc).__name__}")
            return {"source": "none", "lines": []}
        self.sources.append({"source": "container", "argv": argv, "exit_code": proc.returncode})
        lines = parse_container_logs(proc.stdout)
        return {"source": "container", "query": " ".join(argv), "lines": limit_stacks(lines)}

    def traces(self, log_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ids: list[str] = []
        for line in log_lines:
            trace_id = line.get("trace_id")
            valid = isinstance(trace_id, str) and re.fullmatch(r"[0-9a-f]{32}", trace_id)
            if valid and trace_id not in ids and trace_id != "0" * 32:
                ids.append(trace_id)
        if len(ids) < MAX_TRACES:
            now = int(time.time())
            body = self._grafana(
                "/api/datasources/proxy/uid/tempo/api/search",
                {
                    "q": TEMPO_TRACEQL,
                    "limit": str(MAX_TRACES),
                    "start": str(now - self.window_minutes * 60),
                    "end": str(now),
                },
            )
            for item in (body or {}).get("traces", []) if isinstance(body, dict) else []:
                trace_id = _hex_id(item.get("traceID"))
                if trace_id and trace_id not in ids:
                    ids.append(trace_id)
        traces = []
        for trace_id in ids[:MAX_TRACES]:
            body = self._grafana(f"/api/datasources/proxy/uid/tempo/api/traces/{trace_id}")
            if isinstance(body, dict):
                traces.append(reduce_trace(trace_id, body))
        return traces


def git_evidence(repo: Path, commit: str | None) -> dict[str, Any]:
    """Recent commit subjects up to the deployed commit and the files that commit touched."""

    def git(*args: str) -> str:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return proc.stdout if proc.returncode == 0 else ""

    ref = commit if commit and re.fullmatch(r"[0-9a-f]{7,40}", commit) else "HEAD"
    resolved = git("rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    log = git("log", "-n", "10", "--format=%H%x09%s", resolved or "HEAD")
    commits = [
        {"sha": sha, "subject": subject}
        for sha, _, subject in (line.partition("\t") for line in log.splitlines())
    ]
    files = git("show", "--name-only", "--format=", resolved or "HEAD").split()
    return {
        "deployed_commit": commit,
        "deployed_commit_known_locally": bool(resolved),
        "recent_commits": commits,
        "files_touched_by_deployed_commit": files[:50],
    }


def collect(
    incident_id: str,
    repo: Path,
    env: dict[str, str] | None = None,
    http_get: HttpGet | None = None,
    alert: dict[str, Any] | None = None,
) -> dict[str, Any]:
    collector = Collector(dict(os.environ) if env is None else env, http_get)
    health = collector.health()
    metrics = collector.metrics()
    logs = collector.logs()
    traces = collector.traces(logs.get("lines", []))
    evidence = {
        "incident_id": incident_id,
        "collected_at": datetime.now(UTC).isoformat(),
        "window_minutes": collector.window_minutes,
        "alert": _alert_summary(alert or {}),
        "deployment": health,
        "metrics": metrics,
        "logs": logs,
        "traces": traces,
        "git": git_evidence(repo, health.get("commit")),
        "sources": collector.sources,
        "collection_errors": collector.errors,
    }
    return scrub(evidence)


def _alert_summary(alert: dict[str, Any]) -> dict[str, Any]:
    first = (alert.get("alerts") or [{}])[0]
    labels = first.get("labels", {}) or {}
    annotations = first.get("annotations", {}) or {}
    return {
        "status": alert.get("status"),
        "alertname": labels.get("alertname"),
        "severity": labels.get("severity"),
        "journey": labels.get("journey"),
        "starts_at": first.get("startsAt"),
        "summary": annotations.get("summary"),
        "runbook_url": annotations.get("runbook_url"),
        "values": first.get("values"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect the incident evidence packet.")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--alert", type=Path, help="alert.json of the incident (optional)")
    args = parser.parse_args(argv)
    alert = json.loads(args.alert.read_text(encoding="utf-8")) if args.alert else None
    evidence = collect(args.incident_id, args.repo, alert=alert)
    args.out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(args.out),
                "log_lines": len(evidence["logs"].get("lines", [])),
                "log_source": evidence["logs"].get("source"),
                "traces": len(evidence["traces"]),
                "errors": len(evidence["collection_errors"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
