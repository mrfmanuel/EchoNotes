"""Deterministic offline summarizer for local development, tests and CI (never the network).

It echoes the transcripts **unescaped** on purpose: the fragment is untrusted like any model
output, so tests can prove that the sanitizer removes markup injected through a transcript.
"""

from app.summarization.base import SummaryRequest, SummaryResult

FAKE_MODEL = "fake-summarizer"
FAKE_EXCERPT_CHARS = 300


class FakeSummarizer:
    name = "fake"

    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        count = len(request.transcript_titles)
        parts = [
            "<h1>Project summary</h1>",
            f"<p>Deterministic summary of {count} transcript(s) and "
            f"{len(request.images)} screenshot(s).</p>",
            "<h2>Key points</h2>",
            "<ul>",
            *(f"<li>{title}</li>" for title in request.transcript_titles),
            "</ul>",
            "<h2>Decisions and action items</h2>",
            "<p>None (fake provider).</p>",
        ]
        for title, text in zip(request.transcript_titles, request.transcript_texts, strict=True):
            parts += [f"<h2>{title}</h2>", f"<p>{text[:FAKE_EXCERPT_CHARS]}</p>"]
        parts += [
            f'<figure data-screenshot="{image.n}"><figcaption>Screenshot {image.n}</figcaption>'
            "</figure>"
            for image in request.images
        ]
        return SummaryResult(fragment="".join(parts), model=FAKE_MODEL)
