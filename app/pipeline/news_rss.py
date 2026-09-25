"""Google News RSS: real, dated, attributed news items, ranked by source credibility and recency.

Every candidate comes from Google News with a publisher name and domain, so the model can only
choose among real articles - it never supplies a headline or URL itself.
"""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, quote_plus, urlparse

import httpx

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (compatible; SkinstinctDraftLab/1.0)"}
FEED = "https://news.google.com/rss/search?q={q}+when:{days}d&hl=en-IN&gl=IN&ceid=IN:en"

# ---------------- credibility ----------------

TIERS: dict[str, tuple[int, str]] = {
    "regulator": (10, "Regulator / standards body"),
    "journal": (9, "Peer-reviewed journal"),
    "press": (8, "Established press"),
    "trade": (7, "Industry trade press"),
    "other": (4, "Other publisher"),
}

REGULATORS = {
    "cdsco.gov.in", "bis.gov.in", "fssai.gov.in", "mohfw.gov.in", "pib.gov.in", "ascionline.in",
    "who.int", "fda.gov", "ec.europa.eu", "echa.europa.eu", "nih.gov", "iso.org", "cosmeticseurope.eu",
}
JOURNALS = {
    "nature.com", "sciencedirect.com", "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "mdpi.com", "wiley.com",
    "onlinelibrary.wiley.com", "springer.com", "link.springer.com", "jaad.org", "tandfonline.com", "bmj.com",
    "thelancet.com", "jamanetwork.com", "frontiersin.org", "cureus.com", "academic.oup.com", "karger.com",
    "ijdvl.com", "journals.lww.com", "cell.com", "science.org", "plos.org", "journals.plos.org", "sagepub.com",
}
PRESS = {
    "reuters.com", "bloomberg.com", "economictimes.indiatimes.com", "livemint.com", "business-standard.com",
    "thehindubusinessline.com", "thehindu.com", "indianexpress.com", "hindustantimes.com", "financialexpress.com",
    "moneycontrol.com", "timesofindia.indiatimes.com", "ndtv.com", "scroll.in", "theprint.in", "inc42.com",
    "bbc.com", "bbc.co.uk", "ft.com", "wsj.com", "nytimes.com", "theguardian.com", "cnbc.com", "forbesindia.com",
    "fortuneindia.com", "the-ken.com", "entrackr.com", "deccanherald.com", "telegraphindia.com", "newindianexpress.com",
    "apnews.com", "businesstoday.in", "outlookbusiness.com", "yourstory.com",
}
TRADE = {
    "afaqs.com", "exchange4media.com", "cosmeticsdesign-asia.com", "cosmeticsdesign-europe.com", "cosmeticsdesign.com",
    "cosmeticsbusiness.com", "happi.com", "personalcaremagazine.com", "globalcosmeticsnews.com", "beautymatter.com",
    "businessoffashion.com", "voguebusiness.com", "pharmabiz.com", "medicaldialogues.in", "expresspharma.in",
    "professionalbeauty.in", "cosmeticsandtoiletries.com", "premiumbeautynews.com", "wwd.com", "glossy.co",
    "indianretailer.com", "packagingsouthasia.com", "cosmeticsdesign-usa.com", "chemistryworld.com", "cen.acs.org",
}
BLOCKED = {
    "prnewswire.com", "businesswire.com", "globenewswire.com", "einpresswire.com", "openpr.com", "prlog.org",
    "medium.com", "blogspot.com", "wordpress.com", "substack.com", "quora.com", "reddit.com", "youtube.com",
    "instagram.com", "facebook.com", "x.com", "twitter.com", "linkedin.com", "pinterest.com", "tiktok.com",
    "msn.com", "yahoo.com", "newsbreak.com", "latestly.com", "dailyhunt.in",
}
BLOCKED_TITLE = re.compile(r"press release|sponsored|brand\s?(post|spotlight|desk)|partner content|advertorial", re.I)


def domain_of(url: str | None) -> str:
    if not url:
        return ""
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _in(domain: str, group: set[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in group)


def credibility(domain: str) -> tuple[str, int, str] | None:
    """(tier, score, label) for a publisher domain, or None if it should never be cited."""
    d = domain_of(domain)
    if not d or _in(d, BLOCKED):
        return None
    if _in(d, JOURNALS):  # before regulators: PubMed lives under nih.gov
        tier = "journal"
    elif _in(d, REGULATORS) or d.endswith(".gov.in") or d.endswith(".nic.in") or d.endswith(".gov"):
        tier = "regulator"
    elif _in(d, PRESS):
        tier = "press"
    elif _in(d, TRADE):
        tier = "trade"
    else:
        tier = "other"
    score, label = TIERS[tier]
    return tier, score, label


# ---------------- feed ----------------

@dataclass
class NewsItem:
    title: str
    publisher: str
    publisher_url: str
    link: str  # Google News article link
    published: str | None  # ISO date
    tier: str = "other"
    tier_label: str = ""
    credibility: int = 0
    age_days: int | None = None
    rank_score: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def _clean_title(title: str, publisher: str) -> str:
    suffix = f" - {publisher}"
    return title[: -len(suffix)].strip() if publisher and title.endswith(suffix) else title.strip()


def parse_feed(xml_text: str, now: datetime | None = None) -> list[NewsItem]:
    """Parse Google News RSS. Drops blocked publishers and promotional titles."""
    now = now or datetime.now(timezone.utc)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("Bad RSS: %s", exc)
        return []
    items: list[NewsItem] = []
    for it in root.findall("./channel/item"):
        src = it.find("source")
        publisher = (src.text or "").strip() if src is not None else ""
        pub_url = src.get("url", "") if src is not None else ""
        title = _clean_title(it.findtext("title") or "", publisher)
        if not title or BLOCKED_TITLE.search(title):
            continue
        cred = credibility(pub_url)
        if cred is None:
            continue
        published, age = None, None
        raw_date = it.findtext("pubDate")
        if raw_date:
            try:
                dt = parsedate_to_datetime(raw_date)
                dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                published, age = dt.date().isoformat(), max(0, (now - dt).days)
            except (TypeError, ValueError):
                pass
        tier, score, label = cred
        items.append(NewsItem(title=title, publisher=publisher, publisher_url=pub_url, link=it.findtext("link") or "",
                              published=published, tier=tier, tier_label=label, credibility=score, age_days=age))
    return items


def recency_score(age_days: int | None) -> float:
    if age_days is None:
        return 2
    if age_days <= 30:
        return 10
    if age_days <= 90:
        return 8
    if age_days <= 180:
        return 5
    if age_days <= 365:
        return 2
    return 0


def rank(items: list[NewsItem], limit: int = 12) -> list[NewsItem]:
    """Dedupe by title, score by credibility (60%) and recency (40%), best first."""
    seen, out = set(), []
    for it in items:
        key = re.sub(r"\W+", " ", it.title.lower()).strip()[:80]
        if key in seen:
            continue
        seen.add(key)
        it.rank_score = round(0.6 * it.credibility + 0.4 * recency_score(it.age_days), 2)
        out.append(it)
    out.sort(key=lambda x: (x.rank_score, x.published or ""), reverse=True)
    return out[:limit]


def fetch(query: str, days: int = 180, timeout: float = 15) -> list[NewsItem]:
    url = FEED.format(q=quote_plus(query), days=days)
    try:
        r = httpx.get(url, headers=UA, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Google News RSS failed for %r: %s", query, exc)
        return []
    return parse_feed(r.text)


def search(queries: list[str], days: int = 180, limit: int = 12) -> list[NewsItem]:
    items: list[NewsItem] = []
    for q in queries[:4]:
        items.extend(fetch(q, days=days))
    return rank(items, limit=limit)


# ---------------- resolving Google News links ----------------

def decode_link(link: str, expected_domain: str = "", timeout: float = 12) -> str | None:
    """Best-effort: turn a news.google.com article link into the publisher's URL.

    Uses the same two-step flow as the Google News web page. Returns None on any failure, or if
    the decoded URL is not on the publisher's own domain (an authenticity check).
    """
    if "news.google.com" not in link:
        return link
    try:
        art_id = urlparse(link).path.rstrip("/").split("/")[-1]
        page = httpx.get(link, headers=UA, timeout=timeout, follow_redirects=True).text
        sig = re.search(r'data-n-a-sg="([^"]+)"', page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not (sig and ts):
            return None
        inner = [
            "garturlreq",
            [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
             "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            art_id, int(ts.group(1)), sig.group(1),
        ]
        payload = [[["Fbv4je", json.dumps(inner), None, "generic"]]]
        r = httpx.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={**UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            content=f"f.req={quote(json.dumps(payload))}",
            timeout=timeout,
        )
        body = r.text.split("\n\n", 1)[1]
        url = json.loads(json.loads(body)[0][2])[1]
    except (httpx.HTTPError, ValueError, IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        log.info("Could not decode Google News link: %s", exc)
        return None
    if not isinstance(url, str) or not url.startswith("http"):
        return None
    want = domain_of(expected_domain)
    got = domain_of(url)
    if want and not (got == want or got.endswith("." + want) or want.endswith("." + got)):
        log.warning("Decoded URL %s does not match publisher %s; keeping Google News link", got, want)
        return None
    return url
