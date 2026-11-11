"""OpenTelemetry SDK setup (#29): traces, metrics and logs over OTLP http/protobuf.

Only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Otherwise nothing is set up at all and the
app behaves exactly as before (tests, CI and Render prod). Nothing happens at import time.

Providers are passed explicitly to every instrumentation instead of being installed as the
process-wide globals, so tests can set up and shut down telemetry repeatedly.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Literal

from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy.engine import EngineTracer
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    LogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from sqlalchemy.ext.asyncio import AsyncEngine

from app import __version__
from app.config import Settings
from app.telemetry.instruments import NOOP_INSTRUMENTS, Instruments, use_instruments
from app.telemetry.logs import OtlpLogHandler
from app.telemetry.redaction import RedactingSpanProcessor

logger = logging.getLogger(__name__)

SEMCONV_OPT_IN_ENV = "OTEL_SEMCONV_STABILITY_OPT_IN"
# Stable HTTP semantic conventions: `http.server.request.duration` in seconds and
# `http.route` / `http.response.status_code` attributes (no full URLs).
SEMCONV_OPT_IN_DEFAULT = "http"
DB_CONNECTIONS_METRIC = "db.client.connections.usage"
# ASGI `receive`/`send` child spans only add noise to every request.
EXCLUDED_ASGI_SPANS: list[Literal["receive", "send"]] = ["receive", "send"]


@dataclass
class TelemetryExporters:
    """Where the three signals go. `batch=False` (tests) exports synchronously."""

    spans: SpanExporter
    metrics: MetricReader
    logs: LogRecordExporter
    batch: bool = True


def otlp_endpoints(base: str) -> dict[str, str]:
    """Per-signal OTLP/HTTP URLs, as the spec derives them from the base endpoint."""
    root = base.strip().rstrip("/")
    return {signal: f"{root}/v1/{signal}" for signal in ("traces", "metrics", "logs")}


def otlp_exporters(settings: Settings) -> TelemetryExporters:
    # Headers (OTEL_EXPORTER_OTLP_HEADERS, may hold a credential) are read by the exporters.
    urls = otlp_endpoints(settings.otel_exporter_otlp_endpoint)
    return TelemetryExporters(
        spans=OTLPSpanExporter(endpoint=urls["traces"]),
        metrics=PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=urls["metrics"]),
            export_interval_millis=settings.otel_metric_export_interval,
        ),
        logs=OTLPLogExporter(endpoint=urls["logs"]),
    )


def build_resource(settings: Settings) -> Resource:
    return Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": __version__,
            "deployment.environment": settings.app_env,
            "deployment.environment.name": settings.app_env,
            "vcs.ref.head.revision": settings.deployed_commit,
        }
    )


@dataclass
class TelemetryRuntime:
    app: FastAPI
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider
    log_handler: OtlpLogHandler
    _engine_tracers: list[EngineTracer] = field(default_factory=list)
    _closed: bool = False

    def instrument_engine(self, engine: AsyncEngine) -> None:
        """SQLAlchemy spans (statements with placeholders only, never parameters)."""
        if self._closed:
            return
        meter = self.meter_provider.get_meter("opentelemetry.instrumentation.sqlalchemy")
        usage = meter.create_up_down_counter(DB_CONNECTIONS_METRIC, unit="connections")
        tracer = self.tracer_provider.get_tracer("opentelemetry.instrumentation.sqlalchemy")
        self._engine_tracers.append(EngineTracer(tracer, engine.sync_engine, usage))

    def force_flush(self) -> None:
        self.tracer_provider.force_flush()
        self.meter_provider.force_flush()
        self.logger_provider.force_flush()

    def shutdown(self) -> None:
        """Flush and stop all exporters; the app keeps working with telemetry off. Idempotent."""
        global _active
        if self._closed:
            return
        self._closed = True
        logging.getLogger().removeHandler(self.log_handler)
        use_instruments(NOOP_INSTRUMENTS)
        if _active is self:
            _active = None
        FastAPIInstrumentor.uninstrument_app(self.app)
        if self._engine_tracers:
            EngineTracer.remove_all_event_listeners()
            self._engine_tracers.clear()
        self.logger_provider.shutdown()
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()


_active: TelemetryRuntime | None = None


def instrument_engine(engine: AsyncEngine) -> None:
    """Called for every engine the app creates; a no-op while telemetry is off."""
    if _active is not None:
        _active.instrument_engine(engine)


def setup_telemetry(
    app: FastAPI, settings: Settings, exporters: TelemetryExporters | None = None
) -> TelemetryRuntime | None:
    """Set up the SDK and instrument `app`. Returns `None` (and does nothing) when off.

    Must run before the app serves its first request (the middleware stack is built then).
    """
    global _active
    if exporters is None:
        if not settings.telemetry_enabled:
            return None
        exporters = otlp_exporters(settings)
    os.environ.setdefault(SEMCONV_OPT_IN_ENV, SEMCONV_OPT_IN_DEFAULT)

    resource = build_resource(settings)
    span_processor = (
        BatchSpanProcessor(exporters.spans)
        if exporters.batch
        else SimpleSpanProcessor(exporters.spans)
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(RedactingSpanProcessor(span_processor))
    meter_provider = MeterProvider(resource=resource, metric_readers=[exporters.metrics])
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(exporters.logs)
        if exporters.batch
        else SimpleLogRecordProcessor(exporters.logs)
    )

    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, OtlpLogHandler):
            root.removeHandler(handler)
    log_handler = OtlpLogHandler(logger_provider)
    root.addHandler(log_handler)

    use_instruments(Instruments.create(tracer_provider, meter_provider))
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        exclude_spans=EXCLUDED_ASGI_SPANS,
    )
    runtime = TelemetryRuntime(app, tracer_provider, meter_provider, logger_provider, log_handler)
    _active = runtime
    logger.info(
        "telemetry enabled",
        extra={
            "service_name": settings.otel_service_name,
            "metric_export_interval_ms": settings.otel_metric_export_interval,
        },
    )
    return runtime
