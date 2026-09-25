"""Source check: verify a draft's factual claims and build a citable, credible source list.

1. Gemini extracts up to MAX_CLAIMS checkable claims (science, figures, regulation, market) -
   not Meera's own experience, not [VERIFY] placeholders.
2. Each claim gets a Google-Search-grounded check: supported / contradicted / unclear.
   The supporting source must come from the grounding metadata and pass the credibility filter
   (press-release wires, social media and blogs are never cited).
3. The news angle and the supporting sources become the draft's "Sources" list, ready for the
   first comment on LinkedIn.
"""

from __future__ import annotations

import html
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from app.pipeline import gemini, news_rss
from app.pipeline.checklist import VERIFY_RE
from app.pipeline.research import NewsAngle, grounded_sources, resolve_redirect

log = logging.getLogger(__name__)
MAX_CLAIMS = 3

CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {"claims": {"type": "array", "items": {"type": "string"}}},
    "required": ["claims"],
}
VERDICTS = {"supported", "contradicted", "unclear"}


def extract_claims(body: str, limit: int = MAX_CLAIMS) -> list[str]:
    text = VERIFY_RE.sub("[placeholder]", body)
    prompt = (
        f"List up to {limit} factual claims in this LinkedIn post that a reader could check against "
        "published sources: scientific facts, figures, thresholds, regulations, market data, or what a "
        "named report says. Skip opinions, advice, the author's own experiences and anything about the "
        "author's company, and skip [placeholder] items. Quote or closely paraphrase each claim in one "
        "sentence. Most important first. Return an empty list if there are none.\n\n"
        f"POST:\n\"\"\"\n{text}\n\"\"\""
    )
    try:
        resp = gemini.generate(prompt, json_schema=CLAIMS_SCHEMA, temperature=0.0)
        claims = json.loads(gemini.response_text(resp)).get("claims", [])
    except (gemini.GeminiUnavailable, json.JSONDecodeError, AttributeError) as exc:
        log.warning("Claim extraction failed: %s", exc)
        return []
    return [c.strip() for c in claims if isinstance(c, str) and c.strip()][:limit]


# Step 1 is a plain question: asking for JSON-only output makes Gemini skip the search entirely.
SEARCH_PROMPT = """\
What do authoritative sources (regulators, peer-reviewed research, established press) say about
the following claim? Is it accurate? Answer in 2-3 sentences and give the correct figure if the
claim is off.

CLAIM: {claim}
"""
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": sorted(VERDICTS)},
        "explanation": {"type": "string", "description": "One sentence, with the correct figure if the claim is off."},
    },
    "required": ["verdict", "explanation"],
}
MIN_CLAIM_SOURCE_SCORE = 7  # trade press or better; wikis, blogs and unknown sites are never cited


def _classify(claim: str, findings: str) -> tuple[str, str]:
    prompt = (
        "Based ONLY on these search findings, is the claim supported, contradicted, or unclear?\n\n"
        f"CLAIM: {claim}\n\nFINDINGS: {findings}"
    )
    try:
        data = json.loads(gemini.response_text(gemini.generate(prompt, json_schema=VERDICT_SCHEMA, temperature=0.0)))
    except (gemini.GeminiUnavailable, json.JSONDecodeError):
        return "unclear", findings[:240]
    verdict = str(data.get("verdict", "unclear")).lower()
    return (verdict if verdict in VERDICTS else "unclear"), str(data.get("explanation") or "").strip()


def check_claim(claim: str) -> dict[str, Any]:
    out: dict[str, Any] = {"claim": claim, "verdict": "unclear", "explanation": "", "source": None}
    try:
        resp = gemini.generate(SEARCH_PROMPT.format(claim=claim), google_search=True, temperature=0.0)
        if not grounded_sources(resp):  # the model sometimes answers from memory; ask as a search once more
            resp = gemini.generate(f"Search the web: {claim} - is this accurate according to published sources?",
                                   google_search=True, temperature=0.4)
    except gemini.GeminiUnavailable as exc:
        out["explanation"] = f"Check unavailable: {exc}"
        return out
    findings = gemini.response_text(resp).strip()
    grounded = grounded_sources(resp)
    if not grounded:
        out["explanation"] = "No search results came back, so this couldn't be checked against a source."
        return out
    out["verdict"], out["explanation"] = _classify(claim, findings)

    # Best credible grounded source (never one the model named on its own)
    best = None
    for s in grounded:
        cred = news_rss.credibility(s.title)
        if cred and cred[1] >= MIN_CLAIM_SOURCE_SCORE and (best is None or cred[1] > best[1][1]):
            best = (s, cred)
    if best is None:
        if out["verdict"] == "supported":
            out["verdict"] = "unclear"
            out["explanation"] = (out["explanation"] + " (Only low-credibility sources found, so nothing to cite.)").strip()
        return out
    s, (tier, _score, label) = best
    url = resolve_redirect(s.uri)
    real = news_rss.credibility(url) if "vertexaisearch" not in url else None
    if real is not None:  # the resolved URL is more precise than Google's label (nih.gov -> PubMed Central)
        tier, _score, label = real
    publisher = news_rss.domain_of(url) if "vertexaisearch" not in url else s.title
    out["source"] = {"title": _page_title(url) or _fallback_title(url, publisher), "publisher": publisher,
                     "url": url, "tier": tier, "tier_label": label}
    return out


def _fallback_title(url: str, publisher: str) -> str:
    """Readable citation title when the page has none (e.g. a PDF): 'ASCI Codes Guidelines Book (PDF)'."""
    name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    if name.lower().endswith(".pdf"):
        words = re.sub(r"[_\-]+", " ", name[:-4]).strip()
        return f"{words} (PDF, {publisher})" if words else f"{publisher} (PDF)"
    return publisher


_BOT_PAGE = re.compile(r"captcha|checking your browser|just a moment|access denied|attention required|forbidden|"
                       r"are you a robot|security check|cloudflare|^\s*error", re.I)


def _page_title(url: str) -> str | None:
    """Fetch the page <title> so the citation names the article, not just the domain."""
    if "vertexaisearch" in url:
        return None
    try:
        r = httpx.get(url, headers=news_rss.UA, timeout=8, follow_redirects=True)
        m = re.search(r"<title[^>]*>(.*?)</title>", r.text[:20000], re.I | re.S)
    except httpx.HTTPError:
        return None
    if not m or r.status_code >= 400:
        return None
    title = " ".join(html.unescape(m.group(1)).split())
    if not title or _BOT_PAGE.search(title):
        return None
    return title[:180]


def check_post(body: str) -> dict[str, Any]:
    """Run the full claim check. Never raises."""
    claims = extract_claims(body)
    if not claims:
        return {"claims": [], "supported": 0, "contradicted": 0, "unclear": 0}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(check_claim, claims))
    counts = {v: sum(1 for r in results if r["verdict"] == v) for v in VERDICTS}
    return {"claims": results, **counts}


def source_list(angle: NewsAngle | None, claim_check: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Deduped, credibility-ordered sources for the post (news angle first)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if angle is not None and angle.found and angle.url:
        out.append({
            "role": "news angle", "title": angle.title, "publisher": angle.source, "url": angle.url,
            "published": angle.published, "tier": angle.tier, "tier_label": angle.tier_label,
            "via": angle.via, "link_is_publisher": angle.link_is_publisher,
        })
        seen.add(news_rss.domain_of(angle.url) + (angle.title or ""))
    rank = {"regulator": 0, "journal": 1, "press": 2, "trade": 3, "other": 4}
    supporting = [c for c in (claim_check or {}).get("claims", []) if c.get("verdict") == "supported" and c.get("source")]
    supporting.sort(key=lambda c: rank.get(c["source"]["tier"], 9))
    for c in supporting:
        src = c["source"]
        key = news_rss.domain_of(src["url"]) + src["title"]
        if key in seen:
            continue
        seen.add(key)
        out.append({"role": "supports a claim", "claim": c["claim"], **src, "via": "google_search",
                    "link_is_publisher": "vertexaisearch" not in src["url"]})
    return out


def first_comment_text(sources: list[dict[str, Any]]) -> str:
    """Plain text Meera can paste as the first comment under her post."""
    lines = ["Sources:"]
    for i, s in enumerate(sources, 1):
        date = f", {s['published']}" if s.get("published") else ""
        lines.append(f"{i}. {s.get('title')} - {s.get('publisher')}{date}: {s.get('url')}")
    return "\n".join(lines) if len(lines) > 1 else ""
