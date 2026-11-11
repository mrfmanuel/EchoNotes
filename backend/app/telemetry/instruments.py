"""The app's own tracer and metric instruments (#29).

They are no-ops until `app.telemetry.setup.setup_telemetry` swaps in SDK-backed ones, so code
on the journey can always call them, with telemetry off they cost nothing and export nothing.

Instrument names are chosen so that the OTLP -> Prometheus translation in the local
`grafana/otel-lgtm` stack yields exactly (verified, see docs/observability.md):

    echonotes_transcriptions_total{provider, status}
    echonotes_transcription_duration_seconds_bucket|_sum|_count{provider, status}
    echonotes_exports_total{status}
    echonotes_summaries_total{provider, status}
    echonotes_summary_duration_seconds_bucket|_sum|_count{provider, status}

Labels are low-cardinality and safe: never IDs, titles, filenames or text.
"""

from dataclasses import dataclass

from opentelemetry.metrics import Counter, Histogram, MeterProvider, NoOpMeterProvider
from opentelemetry.trace import NoOpTracerProvider, Tracer, TracerProvider

from app import __version__

SCOPE = "echonotes"

TRANSCRIPTIONS_COUNTER = "echonotes.transcriptions"
TRANSCRIPTION_DURATION_HISTOGRAM = "echonotes.transcription.duration"
EXPORTS_COUNTER = "echonotes.exports"
SUMMARIES_COUNTER = "echonotes.summaries"
SUMMARY_DURATION_HISTOGRAM = "echonotes.summary.duration"

# Seconds; covers the fast fake provider (ms) up to the 120 s provider timeout.
TRANSCRIPTION_DURATION_BUCKETS = (
    0.01,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
)

# Seconds; a summary job is bounded by SUMMARY_TIMEOUT_SECONDS (default 90).
SUMMARY_DURATION_BUCKETS = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0)


@dataclass(frozen=True)
class Instruments:
    tracer: Tracer
    transcriptions: Counter
    transcription_duration: Histogram
    exports: Counter
    summaries: Counter
    summary_duration: Histogram

    @classmethod
    def create(
        cls, tracer_provider: TracerProvider, meter_provider: MeterProvider
    ) -> "Instruments":
        meter = meter_provider.get_meter(SCOPE, __version__)
        return cls(
            tracer=tracer_provider.get_tracer(SCOPE, __version__),
            transcriptions=meter.create_counter(
                TRANSCRIPTIONS_COUNTER,
                unit="{transcription}",
                description="Transcription requests (POST /api/projects/{id}/transcriptions)",
            ),
            transcription_duration=meter.create_histogram(
                TRANSCRIPTION_DURATION_HISTOGRAM,
                unit="s",
                description="Duration of the whole transcription create flow",
                explicit_bucket_boundaries_advisory=list(TRANSCRIPTION_DURATION_BUCKETS),
            ),
            exports=meter.create_counter(
                EXPORTS_COUNTER, unit="{export}", description="Project ZIP exports"
            ),
            summaries=meter.create_counter(
                SUMMARIES_COUNTER,
                unit="{summary}",
                description="Finished AI project summary jobs (US-22)",
            ),
            summary_duration=meter.create_histogram(
                SUMMARY_DURATION_HISTOGRAM,
                unit="s",
                description="Duration of an AI project summary job",
                explicit_bucket_boundaries_advisory=list(SUMMARY_DURATION_BUCKETS),
            ),
        )


NOOP_INSTRUMENTS = Instruments.create(NoOpTracerProvider(), NoOpMeterProvider())
_current = NOOP_INSTRUMENTS


def instruments() -> Instruments:
    return _current


def use_instruments(value: Instruments) -> None:
    global _current
    _current = value
