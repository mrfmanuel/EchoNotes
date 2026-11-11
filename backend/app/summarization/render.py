"""Turn the untrusted model fragment into the stored, self-contained `summary.html`.

1. Strip a markdown code fence if the model added one.
2. Sanitize with `nh3` against a tag allowlist. The only attribute kept anywhere is
   `data-screenshot` on `figure`; no links, images, styles, event handlers or URLs survive,
   and `script`/`style`/`iframe`/... are removed with their content (US-22 AC20).
3. Replace each `<figure data-screenshot="N">` whose N is a screenshot we sent with our own
   `<figure><img src="data:..."><figcaption>` (caption reduced to plain text). Others are
   dropped.
4. Wrap it in our template: a strict CSP meta tag, inline CSS (light/dark), a header with the
   escaped project name, the generation time, provider/model and a truncation note.
"""

import base64
import html
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import nh3

from app.summarization.base import SummaryImage
from app.summarization.prompt import ALLOWED_TAGS

CLEAN_CONTENT_TAGS = frozenset(
    {
        "script",
        "style",
        "iframe",
        "frame",
        "frameset",
        "object",
        "embed",
        "svg",
        "math",
        "noscript",
        "template",
        "textarea",
        "select",
        "title",
        "head",
    }
)
_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)
_FIGURE = re.compile(r'<figure data-screenshot="([^"]*)">(.*?)</figure>', re.DOTALL)
_CAPTION = re.compile(r"<figcaption>(.*?)</figcaption>", re.DOTALL)

CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
TRUNCATION_NOTE = (
    "This summary covers truncated content: some transcript text or screenshots were left out "
    "to fit the size limits."
)
STYLE = """
:root { color-scheme: light dark; --fg: #1f2328; --bg: #ffffff; --muted: #59636e;
  --border: #d1d9e0; --note: #fff8c5; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #e6edf3; --bg: #0d1117; --muted: #9198a1; --border: #3d444d; --note: #3b2e00; }
}
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 52rem; margin: 0 auto; padding: 1.5rem; }
header.meta { color: var(--muted); font-size: 0.875rem; border-bottom: 1px solid var(--border);
  padding-bottom: 0.75rem; margin-bottom: 1.5rem; }
header.meta strong { color: var(--fg); font-size: 1rem; }
.note { background: var(--note); border: 1px solid var(--border); border-radius: 6px;
  padding: 0.5rem 0.75rem; margin-top: 0.5rem; color: var(--fg); }
figure { margin: 1.5rem 0; }
figure img { max-width: 100%; height: auto; border: 1px solid var(--border); border-radius: 6px; }
figcaption { color: var(--muted); font-size: 0.875rem; margin-top: 0.25rem; }
blockquote { margin: 0; padding-left: 1rem; border-left: 3px solid var(--border);
  color: var(--muted); }
table { border-collapse: collapse; }
th, td { border: 1px solid var(--border); padding: 0.25rem 0.5rem; }
code { font-family: ui-monospace, Consolas, monospace; font-size: 0.9em; }
"""


@dataclass(frozen=True)
class RenderContext:
    project_name: str
    provider: str
    model: str
    generated_at: datetime
    truncated: bool


def strip_code_fence(fragment: str) -> str:
    match = _FENCE.match(fragment)
    return match.group(1) if match else fragment


def sanitize_fragment(fragment: str) -> str:
    """Allowlist sanitizing; `data-screenshot` on `figure` is the only attribute kept."""
    return nh3.clean(
        strip_code_fence(fragment),
        tags=set(ALLOWED_TAGS),
        clean_content_tags=set(CLEAN_CONTENT_TAGS),
        attributes={"figure": {"data-screenshot"}, "*": set()},
        url_schemes=set(),
        link_rel=None,
        strip_comments=True,
    )


def _plain_text(fragment: str) -> str:
    """Sanitized HTML reduced to escaped text (no tags at all)."""
    return nh3.clean(fragment, tags=set(), clean_content_tags=set(CLEAN_CONTENT_TAGS))


def embed_screenshots(sanitized: str, images: Mapping[int, SummaryImage]) -> str:
    """Swap `figure[data-screenshot=N]` for our own figure with a `data:` image; drop bad N."""

    def replace(match: re.Match[str]) -> str:
        number = match.group(1)
        image = images.get(int(number)) if number.isdigit() else None
        if image is None:
            return ""
        caption_match = _CAPTION.search(match.group(2))
        caption = _plain_text(caption_match.group(1)).strip() if caption_match else ""
        data = base64.b64encode(image.data).decode("ascii")
        return (
            f'<figure><img src="data:{image.mime_type};base64,{data}" '
            f'alt="Screenshot {image.n}"><figcaption>{caption or f"Screenshot {image.n}"}'
            "</figcaption></figure>"
        )

    return _FIGURE.sub(replace, sanitized)


def render_document(fragment: str, images: Mapping[int, SummaryImage], ctx: RenderContext) -> str:
    """The full self-contained HTML document stored in the database and downloaded."""
    body = embed_screenshots(sanitize_fragment(fragment), images)
    name = html.escape(" ".join(ctx.project_name.split()))
    generated = ctx.generated_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    source = html.escape(f"{ctx.provider} / {ctx.model}")
    note = f'\n<p class="note">{TRUNCATION_NOTE}</p>' if ctx.truncated else ""
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} - summary</title>
<style>{STYLE}</style>
</head>
<body>
<main>
<header class="meta"><strong>{name}</strong><br>
AI-generated summary &middot; {generated} &middot; {source}{note}
</header>
<article>
{body}
</article>
</main>
</body>
</html>
"""
