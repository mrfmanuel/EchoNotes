"""OpenTelemetry traces, metrics and logs for the key journey (#29, docs/observability.md).

Off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Privacy: only IDs, sizes, durations, counts,
status codes, provider names and languages ever reach telemetry.
"""

from app.telemetry.instruments import instruments
from app.telemetry.journey import (
    TranscriptionCreateRoute,
    TranscriptionStatus,
    annotate_transcription,
    track_export,
)
from app.telemetry.setup import (
    TelemetryExporters,
    TelemetryRuntime,
    instrument_engine,
    setup_telemetry,
)

__all__ = [
    "TelemetryExporters",
    "TelemetryRuntime",
    "TranscriptionCreateRoute",
    "TranscriptionStatus",
    "annotate_transcription",
    "instrument_engine",
    "instruments",
    "setup_telemetry",
    "track_export",
]
