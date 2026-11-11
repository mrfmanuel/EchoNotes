"""In-memory OpenTelemetry capture for the #29 tests (never a real collector)."""

from dataclasses import dataclass, field
from typing import Any

from opentelemetry.sdk._logs import ReadableLogRecord
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import (
    HistogramDataPoint,
    InMemoryMetricReader,
    MetricsData,
    NumberDataPoint,
)
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.telemetry import TelemetryExporters, TelemetryRuntime


@dataclass
class Capture:
    spans_exporter: InMemorySpanExporter = field(default_factory=InMemorySpanExporter)
    reader: InMemoryMetricReader = field(default_factory=InMemoryMetricReader)
    logs_exporter: InMemoryLogRecordExporter = field(default_factory=InMemoryLogRecordExporter)
    runtime: TelemetryRuntime | None = None
    _metrics: MetricsData | None = None

    @property
    def exporters(self) -> TelemetryExporters:
        return TelemetryExporters(self.spans_exporter, self.reader, self.logs_exporter, batch=False)

    def spans(self, name: str | None = None) -> list[ReadableSpan]:
        spans = list(self.spans_exporter.get_finished_spans())
        return [s for s in spans if name is None or s.name == name]

    def span(self, name: str) -> ReadableSpan:
        matches = self.spans(name)
        assert len(matches) == 1, [s.name for s in self.spans()]
        return matches[0]

    def logs(self) -> list[ReadableLogRecord]:
        return list(self.logs_exporter.get_finished_logs())

    def metrics(self) -> MetricsData:
        """Collect once per call (cumulative), keeping the last result for `metrics_json`."""
        data = self.reader.get_metrics_data()
        assert data is not None
        self._metrics = data
        return data

    def metric_names(self) -> set[str]:
        return {
            metric.name
            for rm in self.metrics().resource_metrics
            for sm in rm.scope_metrics
            for metric in sm.metrics
        }

    def points(self, name: str) -> list[tuple[dict[str, Any], float]]:
        """`(attributes, value)` per data point; the value of a histogram is its count."""
        found: list[tuple[dict[str, Any], float]] = []
        for rm in self.metrics().resource_metrics:
            for sm in rm.scope_metrics:
                for metric in sm.metrics:
                    if metric.name != name:
                        continue
                    for point in metric.data.data_points:
                        if isinstance(point, HistogramDataPoint):
                            found.append((dict(point.attributes or {}), point.count))
                        elif isinstance(point, NumberDataPoint):
                            found.append((dict(point.attributes or {}), point.value))
        return found

    def counts(self, name: str) -> dict[tuple[tuple[str, Any], ...], float]:
        return {tuple(sorted(attrs.items())): value for attrs, value in self.points(name)}

    def everything_as_text(self) -> str:
        """Every exported span, metric (names + labels) and OTLP log record, serialized."""
        parts = [span.to_json() for span in self.spans()]
        parts += [record.to_json() for record in self.logs()]
        parts.append(self.metrics().to_json())
        return "\n".join(parts)
