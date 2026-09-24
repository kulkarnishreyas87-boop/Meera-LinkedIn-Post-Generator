"""Deterministic checks of a draft against the skill's Format rules and self-check.

Covers everything a regex can decide (length, formatting, dashes, spelling, hype words,
question hooks, [VERIFY] markers). The judgement questions (e.g. "is Meera part of the
problem, not the hero?") are answered by the model self-check in draft.py.
"""

from __future__ import annotations

import re
from typing import Any

# From skills/SKILL.md -> Format
WORD_MIN, WORD_MAX = 400, 550

VERIFY_RE = re.compile(r"\[VERIFY:[^\]]*\]", re.IGNORECASE)
OTHER_BRACKET_RE = re.compile(r"\[(?!VERIFY:)[^\]\n]{2,}\]", re.IGNORECASE)
HASHTAG_RE = re.compile(r"(?<![\w&/])#[A-Za-z]\w*")
BULLET_RE = re.compile(r"^\s*(?:[-*•▪●–—>]|\d{1,2}[.)])\s+", re.MULTILINE)
BOLD_RE = re.compile(r"\*\*[^*]+\*\*|__[^_]+__|(?<!\w)\*[^*\s][^*]*\*(?!\w)")
HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s", re.MULTILINE)
EM_EN_DASH_RE = re.compile(r"[—–]")
EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001faff"  # symbols, pictographs, emoticons, transport, supplemental
    "\U00002600-\U000027bf"  # misc symbols + dingbats (includes check marks, stars)
    "\U0001f1e6-\U0001f1ff"  # flags
    "⭐⬆⬇⬅➡✅❌✨"
    "]"
)

HYPE_WORDS = [
    "game-changer", "game changer", "revolutionary", "thrilled", "excited to share",
    "journey", "passionate", "unlock", "supercharge", "next-level", "must-have",
    "holy grail", "miracle", "groundbreaking", "cutting-edge", "transformative",
]
CTA_PHRASES = [
    "follow me", "follow for more", "comment below", "let me know in the comments",
    "dm me", "drop a comment", "like and share", "link in bio", "share your thoughts",
    "what do you think?", "agree?",
]
# American -> British (skill: British/Indian English spelling)
US_SPELLINGS = {
    r"\boxidiz": "oxidis", r"\bsensitiz": "sensitis", r"\bmoisturizer": "moisturiser",
    r"\bbehavior": "behaviour", r"\bcolor": "colour", r"\boptimiz": "optimis",
    r"\bfavorite": "favourite", r"\bcenter\b": "centre", r"\bstandardiz": "standardis",
    r"\borganiz": "organis", r"\brealiz": "realis", r"\bstabiliz": "stabilis",
    r"\bneutraliz": "neutralis", r"\bemphasiz": "emphasis", r"\bminimiz": "minimis",
    r"\bmaximiz": "maximis", r"\bflavor": "flavour", r"\banalyz": "analys",
    r"\blicense\b": "licence (noun)", r"\bfiber": "fibre", r"\bliter\b": "litre",
}


def strip_verify(text: str) -> str:
    return VERIFY_RE.sub(" ", text)


def word_count(text: str) -> int:
    """Words in the post, counting a [VERIFY: ...] marker as one word."""
    return len(re.findall(r"[A-Za-z0-9À-ɏ]+(?:['’.,%-][A-Za-z0-9]+)*", VERIFY_RE.sub(" X ", text)))


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


def first_sentence(text: str) -> str:
    body = text.strip()
    m = re.search(r"(.+?[.?!])(\s|$)", body, re.DOTALL)
    return (m.group(1) if m else body).strip()


def sentence_count(paragraph: str) -> int:
    return max(1, len(re.findall(r"[.?!](?:\s|$)", strip_verify(paragraph))))


def _check(cid: str, label: str, passed: bool, detail: str = "", severity: str = "error") -> dict[str, Any]:
    return {"id": cid, "label": label, "passed": passed, "detail": detail, "severity": severity}


def run_checklist(text: str) -> dict[str, Any]:
    """Return {word_count, verify_count, checks: [...], hard_failures: [...], passed}."""
    clean = strip_verify(text)
    lower = clean.lower()
    wc = word_count(text)
    paras = paragraphs(text)
    verify = VERIFY_RE.findall(text)
    emojis = EMOJI_RE.findall(clean)
    hashtags = HASHTAG_RE.findall(clean)
    bullets = BULLET_RE.findall(text)
    bold = BOLD_RE.findall(clean)
    headers = HEADER_RE.findall(text)
    dashes = EM_EN_DASH_RE.findall(text)
    hype = [w for w in HYPE_WORDS if re.search(r"\b" + re.escape(w) + r"\b", lower)]
    ctas = [c for c in CTA_PHRASES if c in lower]
    us = sorted({f"{m.group(0)} -> {brit}" for pat, brit in US_SPELLINGS.items() for m in re.finditer(pat, lower)})
    first = first_sentence(clean)
    single_sentence_paras = sum(1 for p in paras if sentence_count(p) == 1)
    choppy = len(paras) >= 4 and single_sentence_paras / len(paras) > 0.5
    unmarked = OTHER_BRACKET_RE.findall(text)

    checks = [
        _check("word_count", f"{WORD_MIN}-{WORD_MAX} words", WORD_MIN <= wc <= WORD_MAX, f"{wc} words"),
        _check("no_emojis", "No emojis", not emojis, " ".join(emojis[:5])),
        _check("no_hashtags", "No hashtags", not hashtags, " ".join(hashtags[:5])),
        _check("no_bullets", "No bullets or numbered lists", not bullets, f"{len(bullets)} list line(s)" if bullets else ""),
        _check("no_bold_headers", "No bold, italics or headers", not (bold or headers),
               f"{len(bold)} bold/italic, {len(headers)} header(s)" if (bold or headers) else ""),
        _check("spaced_hyphens", "Spaced hyphens, no em/en dashes", not dashes, f"{len(dashes)} dash(es)" if dashes else ""),
        _check("no_question_hook", "Hook is not a question", not first.endswith("?"), first[:120]),
        _check("prose_paragraphs", "Prose paragraphs, not one-liners", not choppy,
               f"{single_sentence_paras}/{len(paras)} single-sentence paragraphs"),
        _check("no_hype", "No hype words", not hype, ", ".join(hype)),
        _check("no_cta", "No call to follow/like/comment/DM", not ctas, ", ".join(ctas)),
        _check("british_spelling", "British spelling", not us, "; ".join(us[:6]), severity="warning"),
        _check("placeholders_marked", "Placeholders use [VERIFY: ...]", not unmarked, " ".join(unmarked[:3]), severity="warning"),
        _check("verify_markers", "[VERIFY] markers to resolve", len(verify) == 0,
               f"{len(verify)} to resolve before posting", severity="info"),
    ]
    hard = [c["id"] for c in checks if not c["passed"] and c["severity"] == "error"]
    return {
        "word_count": wc,
        "word_range": [WORD_MIN, WORD_MAX],
        "verify_count": len(verify),
        "verify_items": [v[len("[VERIFY:"):-1].strip() for v in verify],
        "paragraph_count": len(paras),
        "emojis": len(emojis),
        "hashtags": len(hashtags),
        "bullets": len(bullets),
        "checks": checks,
        "hard_failures": hard,
        "passed": not hard,
    }


def autofix(text: str) -> str:
    """Safe mechanical fixes only: dashes to spaced hyphens, strip stray markdown emphasis."""
    text = re.sub(r"(?<=\d)[–—](?=\d)", "-", text)  # ranges: 5.5–5.8 -> 5.5-5.8
    text = re.sub(r"\s*[—–]\s*", " - ", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text.strip()
