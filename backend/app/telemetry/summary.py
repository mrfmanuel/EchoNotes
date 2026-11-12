"""Telemetry for the AI summary job (US-22 AC17, NFR-AI-Summary).

One `summary.generate` span per job plus `echonotes.summaries{provider,status}` and the
`echonotes.summary.duration{provider,status}` histogram. Attributes are safe only: IDs,
provider, model, counts, sizes, truncated flag, duration and status. Never transcript text,
titles, filenames, prompts, model output or image bytes.
"""

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum

from opentelemetry.trace import Span, Status, StatusCode

from app.telemetry.instruments import instruments

SUMMARY_SPAN = "summary.generate"


class SummaryMetricStatus(StrEnum):
    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"  # 429 also from the fallback model -> error_code provider_error
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    INTERNAL_ERROR = "internal_error"
    # The row was no longer active (stale-marked `interrupted` or deleted): result discarded.
    INTERRUPTED = "interrupted"


@dataclass
class SummaryTrack:
    span: Span
    provider: str
    status: SummaryMetricStatus = SummaryMetricStatus.INTERNAL_ERROR
    cancelled: bool = False  # app shutdown: no metric (startup recovery marks it interrupted)
    started: float = field(default_factory=time.perf_counter)

    def annotate(self, **attributes: str | int | bool | None) -> None:
        """Set `summary.<name>` attributes (`model` goes to `summarizer.model`)."""
        for name, value in attributes.items():
            if value is None:
                continue
            key = "summarizer.model" if name == "model" else f"summary.{name}"
            self.span.set_attribute(key, value)

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started


@contextmanager
def track_summary(
    project_id: uuid.UUID, summary_id: uuid.UUID, provider: str
) -> Iterator[SummaryTrack]:
    """Span + counter + histogram around one job; the caller sets `track.status`."""
    with instruments().tracer.start_as_current_span(
        SUMMARY_SPAN,
        attributes={
            "echonotes.project.id": str(project_id),
            "summary.id": str(summary_id),
            "summarizer.provider": provider,
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        track = SummaryTrack(span, provider)
        try:
            yield track
        finally:
            _finish(track)


def _finish(track: SummaryTrack) -> None:
    span = track.span
    span.set_attribute("summary.duration_ms", round(track.elapsed * 1000, 2))
    if track.cancelled:
        span.set_attribute("summary.status", "cancelled")
        return
    span.set_attribute("summary.status", track.status.value)
    if track.status is not SummaryMetricStatus.SUCCESS:
        span.set_status(Status(StatusCode.ERROR))
    labels = {"provider": track.provider, "status": track.status.value}
    tools = instruments()
    tools.summaries.add(1, labels)
    tools.summary_duration.record(track.elapsed, labels)
