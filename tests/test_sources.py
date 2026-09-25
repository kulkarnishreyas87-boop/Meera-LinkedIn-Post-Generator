"""Google News RSS, source credibility, claim checking and the Sources list. No network."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from app.pipeline import autoreview, news_rss, research, sources

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>test</title>
<item><title>CDSCO flags 2 creams over heavy metals - The Times of India</title>
  <link>https://news.google.com/rss/articles/AAA?oc=5</link>
  <pubDate>Wed, 16 Sep 2026 02:19:00 GMT</pubDate>
  <source url="https://timesofindia.indiatimes.com">The Times of India</source></item>
<item><title>Rheology of cosmetic products - MDPI</title>
  <link>https://news.google.com/rss/articles/BBB?oc=5</link>
  <pubDate>Thu, 17 Sep 2026 00:00:00 GMT</pubDate>
  <source url="https://www.mdpi.com">MDPI</source></item>
<item><title>Brand X launches miracle serum - PR Newswire</title>
  <link>https://news.google.com/rss/articles/CCC?oc=5</link>
  <pubDate>Fri, 18 Sep 2026 00:00:00 GMT</pubDate>
  <source url="https://www.prnewswire.com">PR Newswire</source></item>
<item><title>Sponsored: best serums of 2026 - Some Site</title>
  <link>https://news.google.com/rss/articles/DDD?oc=5</link>
  <pubDate>Fri, 18 Sep 2026 00:00:00 GMT</pubDate>
  <source url="https://somesite.example">Some Site</source></item>
<item><title>Old sunscreen study - Old Blog</title>
  <link>https://news.google.com/rss/articles/EEE?oc=5</link>
  <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
  <source url="https://oldblog.example">Old Blog</source></item>
</channel></rss>"""


# ---------------- credibility ----------------

@pytest.mark.parametrize(
    "domain, tier",
    [
        ("cdsco.gov.in", "regulator"),
        ("https://www.ascionline.in/x", "regulator"),
        ("something.nic.in", "regulator"),
        ("pubmed.ncbi.nlm.nih.gov", "journal"),  # PubMed, even though it is under nih.gov
        ("www.fda.gov", "regulator"),
        ("www.mdpi.com", "journal"),
        ("economictimes.indiatimes.com", "press"),
        ("retail.economictimes.indiatimes.com", "press"),
        ("afaqs.com", "trade"),
        ("unknown-site.example", "other"),
    ],
)
def test_credibility_tiers(domain, tier):
    assert news_rss.credibility(domain)[0] == tier


@pytest.mark.parametrize("domain", ["prnewswire.com", "medium.com", "x.blogspot.com", "youtube.com", "linkedin.com", "msn.com"])
def test_blocked_sources_are_never_cited(domain):
    assert news_rss.credibility(domain) is None


# ---------------- feed parsing and ranking ----------------

def test_parse_feed_extracts_real_attributed_items_and_drops_junk():
    items = news_rss.parse_feed(FEED, now=NOW)
    titles = [i.title for i in items]
    assert "CDSCO flags 2 creams over heavy metals" in titles  # " - Publisher" suffix removed
    assert not any("PR Newswire" in i.publisher for i in items)  # press-release wire blocked
    assert not any(t.lower().startswith("sponsored") for t in titles)  # promotional title blocked
    toi = next(i for i in items if i.publisher == "The Times of India")
    assert toi.published == "2026-09-16" and toi.age_days == 7 and toi.tier == "press"


def test_rank_prefers_credible_and_recent():
    ranked = news_rss.rank(news_rss.parse_feed(FEED, now=NOW))
    assert [i.publisher for i in ranked][:2] == ["MDPI", "The Times of India"]  # journal > press, both recent
    assert ranked[-1].publisher == "Old Blog"  # unknown + 2 years old


def test_rank_dedupes_same_story():
    items = news_rss.parse_feed(FEED, now=NOW)
    assert len(news_rss.rank(items + items)) == len(items)


def test_bad_xml_is_safe():
    assert news_rss.parse_feed("<not rss") == []


def test_decoded_link_must_match_publisher_domain(monkeypatch):
    page = NS(text='<div data-n-a-sg="SIG" data-n-a-ts="123"></div>')
    inner = json.dumps([None, "https://evil.example/article"])
    post = NS(text=")]}'\n\n" + json.dumps([["wrb.fr", "Fbv4je", inner]]))
    monkeypatch.setattr(news_rss.httpx, "get", lambda *a, **k: page)
    monkeypatch.setattr(news_rss.httpx, "post", lambda *a, **k: post)
    assert news_rss.decode_link("https://news.google.com/rss/articles/AAA?oc=5", "https://www.mdpi.com") is None
    inner_ok = json.dumps([None, "https://www.mdpi.com/2227-9717/14/18/2971"])
    monkeypatch.setattr(news_rss.httpx, "post", lambda *a, **k: NS(text=")]}'\n\n" + json.dumps([["wrb.fr", "Fbv4je", inner_ok]])))
    assert news_rss.decode_link("https://news.google.com/rss/articles/AAA?oc=5", "https://www.mdpi.com").startswith("https://www.mdpi.com/")


# ---------------- research: RSS path ----------------

class R:
    def __init__(self, text, sources=()):
        self.text = text
        chunks = [NS(web=NS(title=d, uri=f"https://{d}/a")) for d in sources]
        self.candidates = [NS(grounding_metadata=NS(grounding_chunks=chunks, grounding_supports=[]))]


def _rss_env(monkeypatch, pick_index, summary_domain="mdpi.com"):
    items = news_rss.rank(news_rss.parse_feed(FEED, now=NOW))

    def gen(prompt, *, json_schema=None, google_search=False, **kw):
        if json_schema is research.QUERY_SCHEMA:
            return R(json.dumps({"queries": ["cosmetic stability testing", "CDSCO cosmetics"]}))
        if json_schema is research.PICK_SCHEMA:
            return R(json.dumps({"index": pick_index, "relevance": "same issue"}))
        if google_search:
            return R(json.dumps({"found": True, "summary": "Reviews in-use stability."}), sources=[summary_domain])
        raise AssertionError("unexpected")

    monkeypatch.setattr(research.gemini, "generate", gen)
    monkeypatch.setattr(research.news_rss, "search", lambda qs, **k: items)
    monkeypatch.setattr(research.news_rss, "decode_link", lambda link, dom: "https://www.mdpi.com/2227-9717/14/18/2971")
    monkeypatch.setattr(research, "resolve_redirect", lambda u: u)
    return items


def test_rss_angle_is_one_of_the_real_candidates(monkeypatch):
    items = _rss_env(monkeypatch, pick_index=1)
    angle = research.find_news_angle("note", "Industry Transparency", "insight")
    assert angle.found and angle.via == "google_news"
    assert angle.title == items[0].title and angle.source == items[0].publisher  # copied, never model-written
    assert angle.published == items[0].published and angle.tier == items[0].tier
    assert angle.link_is_publisher and angle.url.startswith("https://www.mdpi.com/")
    assert angle.summary_verified


def test_rss_out_of_range_pick_falls_back_to_grounded_search(monkeypatch):
    _rss_env(monkeypatch, pick_index=99)
    called = {}
    monkeypatch.setattr(research, "find_news_angle_grounded",
                        lambda *a: called.setdefault("fallback", research.NewsAngle(found=False, note="nothing")))
    angle = research.find_news_angle("note", None, None)
    assert "fallback" in called and not angle.found
    assert "none was relevant enough" in angle.note


def test_rss_summary_from_other_domain_is_marked_unverified(monkeypatch):
    _rss_env(monkeypatch, pick_index=1, summary_domain="randomblog.example")
    angle = research.find_news_angle("note", None, None)
    assert angle.found and not angle.summary_verified


def test_rss_failure_never_breaks_drafting(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(research.news_rss, "search", boom)
    monkeypatch.setattr(research.gemini, "generate", lambda *a, **k: R(json.dumps({"queries": ["x"]})))
    monkeypatch.setattr(research, "find_news_angle_grounded", lambda *a: research.NewsAngle(found=False, note="fb"))
    assert research.find_news_angle("note", None, None).note == "fb"


# ---------------- claim check ----------------

def test_claim_check_uses_most_credible_grounded_source(monkeypatch):
    resp = R(json.dumps({"verdict": "supported", "explanation": "ok", "source_title": "Solubility data"}),
             sources=["prnewswire.com", "somesite.example", "ncbi.nlm.nih.gov"])
    monkeypatch.setattr(sources.gemini, "generate", lambda *a, **k: resp)
    monkeypatch.setattr(sources, "resolve_redirect", lambda u: u)
    monkeypatch.setattr(sources, "_page_title", lambda u: None)
    out = sources.check_claim("Azelaic acid is poorly water soluble")
    assert out["verdict"] == "supported"
    assert out["source"]["publisher"] == "ncbi.nlm.nih.gov" and out["source"]["tier"] == "journal"


def test_supported_without_citable_source_becomes_unclear(monkeypatch):
    resp = R(json.dumps({"verdict": "supported", "explanation": "ok"}), sources=["prnewswire.com"])
    monkeypatch.setattr(sources.gemini, "generate", lambda *a, **k: resp)
    out = sources.check_claim("claim")
    assert out["verdict"] == "unclear" and out["source"] is None


def test_unknown_verdict_is_unclear(monkeypatch):
    monkeypatch.setattr(sources.gemini, "generate", lambda *a, **k: R(json.dumps({"verdict": "maybe"})))
    assert sources.check_claim("claim")["verdict"] == "unclear"


def test_check_post_counts(monkeypatch):
    monkeypatch.setattr(sources, "extract_claims", lambda body: ["a", "b", "c"])
    verdicts = {"a": "supported", "b": "contradicted", "c": "unclear"}
    monkeypatch.setattr(sources, "check_claim", lambda c: {"claim": c, "verdict": verdicts[c], "source": None})
    out = sources.check_post("body")
    assert (out["supported"], out["contradicted"], out["unclear"]) == (1, 1, 1)


def test_source_list_orders_by_credibility_and_dedupes():
    angle = research.NewsAngle(found=True, title="News", source="The Times of India", url="https://timesofindia.indiatimes.com/a",
                               published="2026-09-16", tier="press", tier_label="Established press", via="google_news",
                               link_is_publisher=True)
    check = {"claims": [
        {"claim": "c1", "verdict": "supported", "source": {"title": "T1", "publisher": "afaqs.com", "url": "https://afaqs.com/x", "tier": "trade", "tier_label": "Industry trade press"}},
        {"claim": "c2", "verdict": "supported", "source": {"title": "T2", "publisher": "cdsco.gov.in", "url": "https://cdsco.gov.in/y", "tier": "regulator", "tier_label": "Regulator"}},
        {"claim": "c3", "verdict": "contradicted", "source": {"title": "T3", "publisher": "x.com", "url": "https://mdpi.com/z", "tier": "journal", "tier_label": "Journal"}},
    ]}
    out = sources.source_list(angle, check)
    assert [s["publisher"] for s in out] == ["The Times of India", "cdsco.gov.in", "afaqs.com"]  # contradicted not cited
    text = sources.first_comment_text(out)
    assert text.startswith("Sources:\n1. News - The Times of India, 2026-09-16: https://timesofindia")


def test_first_comment_empty_when_no_sources():
    assert sources.first_comment_text([]) == ""


# ---------------- auto-review integration ----------------

def _checklist(**extra):
    c = {"review": {"voice_score": 9, "top_issue": "none", "invented_claims": []},
         "self_check": [{"n": i, "passed": True} for i in range(1, 9)], "hard_failures": [], "verify_count": 0, "note_score": 8}
    c.update(extra)
    return c


def test_contradicted_claim_blocks_auto_approval_without_penalty():
    """No penalty: a penalty would trigger an auto-redraft that 'corrects' what may be Meera's own position."""
    c = _checklist(claim_check={"claims": [{"claim": "SPF 50 blocks 100% of UV", "verdict": "contradicted"}]})
    score, breakdown = autoreview.quality_score(c)
    assert breakdown["contradicted"] == 1 and score == 9
    d = autoreview.decide(score, c)
    assert d.action == "review" and "contradict" in d.reason


def test_unclear_claims_do_not_penalise():
    c = _checklist(claim_check={"claims": [{"claim": "x", "verdict": "unclear"}]})
    assert autoreview.quality_score(c)[0] == 9 and autoreview.decide(9, c).action == "auto_approved"


def test_bot_check_pages_are_not_used_as_titles(monkeypatch):
    for title in ["Checking your browser - reCAPTCHA", "Just a moment...", "Access Denied"]:
        page = NS(text=f"<html><title>{title}</title></html>", status_code=200)
        monkeypatch.setattr(sources.httpx, "get", lambda *a, **k: page)
        assert sources._page_title("https://pmc.ncbi.nlm.nih.gov/articles/X/") is None
    page = NS(text="<title>Azelaic acid: properties and delivery - PMC</title>", status_code=200)
    monkeypatch.setattr(sources.httpx, "get", lambda *a, **k: page)
    assert sources._page_title("https://pmc.ncbi.nlm.nih.gov/articles/X/") == "Azelaic acid: properties and delivery - PMC"


def test_no_search_results_means_unclear_not_supported(monkeypatch):
    monkeypatch.setattr(sources.gemini, "generate", lambda *a, **k: R("It is accurate."))  # no grounding
    out = sources.check_claim("claim")
    assert out["verdict"] == "unclear" and out["source"] is None


def test_pdf_sources_get_a_readable_title():
    url = "https://www.ascionline.in/wp-content/uploads/guidelines/ASCI_Codes_Guidelines_Book.pdf"
    assert sources._fallback_title(url, "ascionline.in") == "ASCI Codes Guidelines Book (PDF, ascionline.in)"
    assert sources._fallback_title("https://example.org/page", "example.org") == "example.org"
