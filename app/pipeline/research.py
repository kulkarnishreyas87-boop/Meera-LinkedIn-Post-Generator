"""AI call #2a: find ONE current, real news item or industry data point via Google Search grounding.

A source is only accepted if it appears in the grounding metadata Google returns. The model's
own claim about a URL is never trusted on its own, so a source cannot be fabricated.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import date
from urllib.parse import urlparse

import httpx

from app.pipeline import gemini

log = logging.getLogger(__name__)


@dataclass
class NewsAngle:
    found: bool
    title: str | None = None
    source: str | None = None
    url: str | None = None
    summary: str | None = None
    note: str | None = None  # relevance, or why no angle was used

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class GroundedSource:
    title: str  # Google usually puts the publisher domain here
    uri: str  # often a vertexaisearch redirect


RESEARCH_PROMPT = """\
Today is {today}. Search the web for ONE current, real news item or industry data point that a
science-led Indian skincare founder could reference in a LinkedIn post on the topic below.

Preferences, in order:
1. Published in the last 12 months (the last 3 months is better).
2. Relevant to India (CDSCO / BIS / Indian regulation, Indian D2C beauty market, Indian climate
   or consumers). Global regulatory or scientific news is acceptable if nothing Indian fits.
3. From a credible outlet: regulators, peer-reviewed journals, established business or trade press.
   Not brand press releases, not influencer content.

Topic category: {category}
Core insight of the post: {insight}
Raw note: \"\"\"{note}\"\"\"

Reply with ONLY a JSON object, no prose:
{{"found": true/false, "title": "headline", "publisher": "outlet name", "url": "article URL",
  "published_date": "YYYY-MM-DD or approximate", "summary": "2-3 factual sentences on what it says",
  "relevance": "one sentence on how it connects to the note"}}
If nothing credible and relevant turns up, reply {{"found": false, "relevance": "why not"}}.
Never invent a headline, outlet, figure or URL. The url must be the article's page on the
publisher's own site as found in your search results (not a doi.org or shortened link).
"""


def _parse_json_object(raw: str) -> dict:
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip(), flags=re.IGNORECASE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def grounded_sources(resp) -> list[GroundedSource]:
    out: list[GroundedSource] = []
    for cand in resp.candidates or []:
        meta = getattr(cand, "grounding_metadata", None)
        for chunk in (getattr(meta, "grounding_chunks", None) or []) if meta else []:
            web = getattr(chunk, "web", None)
            if web and web.uri:
                out.append(GroundedSource(title=web.title or "", uri=web.uri))
    return out


def cited_source(resp, title: str | None, sources: list[GroundedSource]) -> GroundedSource | None:
    """The grounded source Google cites for the headline, else the most-cited one."""
    supports = []
    for cand in resp.candidates or []:
        meta = getattr(cand, "grounding_metadata", None)
        for sup in (getattr(meta, "grounding_supports", None) or []) if meta else []:
            idx = list(getattr(sup, "grounding_chunk_indices", None) or [])
            text = getattr(getattr(sup, "segment", None), "text", "") or ""
            supports.append((idx, text))
    if not supports or not sources:
        return None
    key = (title or "")[:40].strip()
    for idx, text in supports:
        if key and key in text and idx and idx[0] < len(sources):
            return sources[idx[0]]
    counts: dict[int, int] = {}
    for idx, _ in supports:
        for i in idx:
            counts[i] = counts.get(i, 0) + 1
    best = max(counts, key=counts.get, default=None)
    return sources[best] if best is not None and best < len(sources) else None


def _domain(url: str | None) -> str:
    if not url:
        return ""
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def resolve_redirect(uri: str) -> str:
    """Grounding URIs are often vertexaisearch redirects; follow one hop to get the real article URL."""
    if "vertexaisearch.cloud.google.com" not in uri:
        return uri
    try:
        r = httpx.head(uri, follow_redirects=False, timeout=8)
        loc = r.headers.get("location")
        if loc and loc.startswith("http"):
            return loc
    except httpx.HTTPError as exc:
        log.info("Could not resolve grounding redirect: %s", exc)
    return uri


def follow_url(url: str) -> str:
    """Final URL after redirects (DOI links, short links). Returns the input on any failure."""
    if not url.startswith(("http://", "https://")):
        return url
    try:
        r = httpx.get(url, follow_redirects=True, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        return str(r.url)
    except httpx.HTTPError as exc:
        log.info("Could not follow %s: %s", url, exc)
        return url


def match_source(claimed_url: str | None, claimed_publisher: str | None, sources: list[GroundedSource]) -> GroundedSource | None:
    """Return the grounded source that backs the model's claim, if any."""
    want = _domain(claimed_url)
    for s in sources:
        title_dom = s.title.lower().removeprefix("www.")
        if want and (title_dom == want or want.endswith("." + title_dom) or title_dom.endswith("." + want)):
            return s
        if want and _domain(s.uri) == want:
            return s
    # Fall back to publisher name vs. a whole domain label, e.g. "The Economic Times" ~
    # economictimes.indiatimes.com. Short or partial names never match.
    pub = re.sub(r"[^a-z0-9]", "", (claimed_publisher or "").lower().removeprefix("the "))
    if len(pub) < 5:
        return None
    for s in sources:
        labels = [lbl for lbl in s.title.lower().removeprefix("www.").split(".")[:-1] if len(lbl) >= 5]
        if any(lbl == pub or (len(pub) >= 8 and (lbl in pub or pub in lbl)) for lbl in labels):
            return s
    return None


def find_news_angle(note_text: str, category: str | None, insight: str | None) -> NewsAngle:
    prompt = RESEARCH_PROMPT.format(
        today=date.today().isoformat(),
        category=category or "unknown",
        insight=insight or "(not triaged)",
        note=note_text.strip()[:2000],
    )
    try:
        resp = gemini.generate(prompt, google_search=True, temperature=0.2)
    except gemini.GeminiUnavailable as exc:
        log.warning("News search failed: %s", exc)
        return NewsAngle(found=False, note="News search was unavailable, so this draft has no news angle.")

    sources = grounded_sources(resp)
    data = _parse_json_object(gemini.response_text(resp))

    if not sources:
        return NewsAngle(found=False, note="Search returned no grounded sources, so this draft has no news angle.")
    if not data.get("found"):
        reason = data.get("relevance") or "Nothing credible and relevant turned up."
        return NewsAngle(found=False, note=f"No news angle used: {reason}")

    backing = match_source(data.get("url"), data.get("publisher"), sources)
    if backing is None and data.get("url"):
        # e.g. doi.org/10.3390/... -> mdpi.com/...; still must match a grounded source
        final = follow_url(data["url"])
        if final != data["url"]:
            backing = match_source(final, None, sources)
            if backing is not None:
                data["url"] = final
    via_citation = False
    if backing is None:
        # The model's URL is unreliable; use the source Google's citations attach to its answer.
        backing = cited_source(resp, data.get("title"), sources)
        via_citation = backing is not None
    if backing is None:
        log.warning("Model cited %r but it is not in grounding metadata; discarding.", data.get("url"))
        return NewsAngle(
            found=False,
            note="The search suggested a source that could not be matched to a verified search result, so it was dropped.",
        )

    url = resolve_redirect(backing.uri)
    claimed = data.get("url")
    if not via_citation and claimed and _domain(claimed) and _domain(claimed) == _domain(url):
        url = claimed  # same verified domain: prefer the article URL over a homepage
    note = (data.get("relevance") or "").strip()
    if via_citation:
        publisher = backing.title
        note = (note + " " if note else "") + "(Source taken from Google's search citations - check the headline against the link.)"
    else:
        publisher = (data.get("publisher") or backing.title).strip()
    return NewsAngle(
        found=True,
        title=(data.get("title") or backing.title).strip(),
        source=publisher,
        url=url,
        summary=(data.get("summary") or "").strip() or None,
        note=note or None,
    )
