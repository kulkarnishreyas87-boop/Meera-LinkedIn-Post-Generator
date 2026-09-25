"""AI call #2b/c: draft the post with SKILL.md as the system instruction, then self-check it."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.pipeline import gemini
from app.pipeline.checklist import autofix, run_checklist
from app.pipeline.research import NewsAngle
from app.pipeline.skill import load_skill_text, system_instruction

log = logging.getLogger(__name__)


# ---------- self-check questions, read verbatim from SKILL.md ----------

def self_check_questions(skill_text: str | None = None) -> list[str]:
    """The numbered questions under the skill's 'Self-check before returning a draft' heading."""
    text = skill_text if skill_text is not None else load_skill_text()
    m = re.search(r"^##\s*Self-check[^\n]*\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        return []
    return [q.strip() for q in re.findall(r"^\s*\d+\.\s+(.+)$", m.group(1), re.MULTILINE)]


# ---------- prompts ----------

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "post": {"type": "string", "description": "The LinkedIn post only, plain prose paragraphs separated by blank lines."},
        "reviewer_notes": {"type": "string", "description": "Short note: placeholders to fill and claims to verify."},
    },
    "required": ["post", "reviewer_notes"],
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "passed": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["n", "passed", "note"],
            },
        },
        "voice_score": {
            "type": "integer",
            "minimum": 0,
            "maximum": 10,
            "description": "0-10: would a regular reader of her published posts believe Meera wrote this, and is it strong enough to post under her name?",
        },
        "top_issue": {"type": "string", "description": "The single most important improvement, or 'none'."},
        "invented_claims": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Scenes, events, conversations, documents or numbers attributed to Meera or Skinstinct that are NOT in the raw note or the fact sheet. Empty if none.",
        },
    },
    "required": ["answers", "voice_score", "top_issue", "invented_claims"],
}


class _DraftOut(BaseModel):
    post: str
    reviewer_notes: str = ""


class _ReviewAnswer(BaseModel):
    n: int
    passed: bool
    note: str = ""


def _news_block(angle: NewsAngle | None) -> str:
    if angle is None or not angle.found:
        reason = angle.note if angle else "No search was run."
        return (
            "NEWS ANGLE: none. " + reason + "\n"
            "Do not reference any news item, report, survey or statistic that is not in the note or the fact sheet."
        )
    when = f" on {angle.published}" if angle.published else ""
    credible = f" ({angle.tier_label})" if angle.tier_label else ""
    if angle.summary and angle.summary_verified:
        what = f"- What it reports (verified from search results): {angle.summary}\n"
    elif angle.summary:
        what = f"- Summary (NOT verified - treat as uncertain): {angle.summary}\n"
    else:
        what = "- No verified summary: use only what the headline itself states.\n"
    return (
        f"NEWS ANGLE (a real article found via {'Google News' if angle.via == 'google_news' else 'Google Search'} - "
        "use it, don't invent beyond it):\n"
        f"- Headline: {angle.title}\n- Outlet: {angle.source}{credible}, published{when or ' recently'}\n"
        f"- URL (do not put the URL in the post): {angle.url}\n{what}"
        f"- Why it's relevant: {angle.note or ''}\n"
        "Work it in naturally, usually in the hook or where the mechanism meets the real world, and name the "
        "outlet in prose (for example 'reported by <outlet> this month'). Only state figures that appear above; "
        "if you need anything more from the article, use a [VERIFY: ...] marker. It must not take over the post - "
        "the note's insight is the spine."
    )


def build_draft_prompt(
    note_text: str,
    triage: dict[str, Any],
    angle: NewsAngle | None,
    recent_posts: list[str],
    instruction: str | None = None,
    previous_body: str | None = None,
) -> str:
    recent = "\n".join(f"- {p[:220].strip()}..." for p in recent_posts) or "- (none yet)"
    parts = [
        "Write one LinkedIn post in Meera Pillai's voice, following the skill in your system instruction "
        "exactly: its post architecture, sentence-level rules, format, 'never does' list and self-check.",
        f"RAW NOTE FROM MEERA:\n\"\"\"\n{note_text.strip()}\n\"\"\"",
        "TRIAGE:\n" + json.dumps(triage, indent=2, ensure_ascii=False),
        _news_block(angle),
        "RECENTLY APPROVED POSTS (do not repeat their topic, hook or examples):\n" + recent,
    ]
    if previous_body:
        parts.append(f"PREVIOUS DRAFT (being redrafted):\n\"\"\"\n{previous_body}\n\"\"\"")
    if instruction:
        parts.append(f"MEERA'S REDRAFT INSTRUCTION: {instruction.strip()}")
    elif previous_body:
        parts.append("Meera asked for a redraft without specific instructions: write a noticeably different take.")
    parts.append(
        "Output: 'post' is the post text only (no title, no sign-off, paragraphs separated by one blank line). "
        "'reviewer_notes' lists any [VERIFY: ...] items and claims she should check, in one or two sentences."
    )
    return "\n\n".join(parts)


def _parse_model(raw: str, model: type[BaseModel]) -> BaseModel:
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip(), flags=re.IGNORECASE).strip()
    return model.model_validate(json.loads(text))


def write_draft(prompt: str) -> _DraftOut:
    last: Exception | None = None
    for attempt in (1, 2):
        resp = gemini.generate(prompt, system=system_instruction(), json_schema=DRAFT_SCHEMA, temperature=0.8)
        try:
            out = _parse_model(gemini.response_text(resp), _DraftOut)
            if out.post.strip():
                return out
            raise ValueError("empty post")
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last = exc
            log.warning("Draft JSON parse failed (attempt %d): %s", attempt, exc)
    raise RuntimeError(f"Draft generation failed: {last}")


NO_REVIEW = {"voice_score": None, "top_issue": None, "invented_claims": []}

REVIEW_RUBRIC = """\
You are a sceptical editor who has read every post Meera has published, reviewing a draft written
by someone else. Your job is to protect her name, not to encourage the writer.

1. Answer each self-check question. passed=false if there is any real doubt; say why in one sentence.
2. invented_claims: compare the draft with the RAW NOTE below and the fact sheet in your
   instructions. List every scene, event, conversation, document, date or number that the draft
   presents as Meera's or Skinstinct's own experience but that is NOT in the raw note or the fact
   sheet. [VERIFY: ...] markers are fine - they are honest placeholders, not claims. General,
   well-established science is fine. If the note is thin and the draft fills it with a vivid
   first-person anecdote, that anecdote is invented.
3. voice_score, anchored:
   9-10  indistinguishable from her published posts AND built on real substance from the note
   7-8   clearly her voice, minor issues
   5-6   competent but generic, or padded far beyond what the note supports
   0-4   off-voice, hype, or mostly invented
   Most first drafts are 6-8. Reserve 9+ for drafts you would publish under her name unchanged.
4. top_issue: the single most important fix, or 'none'.
"""


def self_review(body: str, questions: list[str], note_text: str = "") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Critical review: self-check answers, anchored voice score, invented-claim check. Returns (answers, review)."""
    if not questions:
        return [], dict(NO_REVIEW)
    qs = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    prompt = (
        f"{REVIEW_RUBRIC}\nSELF-CHECK QUESTIONS:\n{qs}\n\n"
        f"RAW NOTE FROM MEERA:\n\"\"\"\n{note_text.strip() or '(not provided)'}\n\"\"\"\n\n"
        f"DRAFT:\n\"\"\"\n{body}\n\"\"\""
    )
    try:
        resp = gemini.generate(prompt, system=system_instruction(), json_schema=REVIEW_SCHEMA, temperature=0.0)
        data = json.loads(gemini.response_text(resp))
        answers = {a.n: a for a in (_ReviewAnswer.model_validate(x) for x in data.get("answers", []))}
        raw_score = data.get("voice_score")
        voice = max(0, min(10, round(float(raw_score)))) if raw_score is not None else None
        invented = [str(x).strip() for x in (data.get("invented_claims") or []) if str(x).strip()]
        review = {"voice_score": voice, "top_issue": (data.get("top_issue") or "").strip() or None, "invented_claims": invented}
    except (json.JSONDecodeError, ValidationError, gemini.GeminiUnavailable, TypeError, ValueError) as exc:
        log.warning("Self-review failed: %s", exc)
        unavailable = [{"n": i, "question": q, "passed": None, "note": "Self-review unavailable"} for i, q in enumerate(questions, 1)]
        return unavailable, dict(NO_REVIEW)
    return [
        {
            "n": i,
            "question": q,
            "passed": answers[i].passed if i in answers else None,
            "note": answers[i].note if i in answers else "",
        }
        for i, q in enumerate(questions, 1)
    ], review


def revise(body: str, problems: list[str]) -> str:
    prompt = (
        "Revise this draft so it fixes every problem listed, keeping everything else - voice, facts, "
        "[VERIFY: ...] markers and structure - the same. Do not add new facts. If a fix needs a "
        "Skinstinct-specific anecdote, number or event that is not already in the draft or the fact "
        "sheet, do NOT invent one: use a fact-sheet item, or write a [VERIFY: ...] placeholder "
        "describing what is needed.\n\n"
        "PROBLEMS:\n" + "\n".join(f"- {p}" for p in problems) + f"\n\nDRAFT:\n\"\"\"\n{body}\n\"\"\""
    )
    resp = gemini.generate(prompt, system=system_instruction(), json_schema=DRAFT_SCHEMA, temperature=0.4)
    try:
        return _parse_model(gemini.response_text(resp), _DraftOut).post.strip() or body
    except (json.JSONDecodeError, ValidationError) as exc:
        log.warning("Revision parse failed, keeping original: %s", exc)
        return body


@dataclass
class DraftResult:
    body: str
    reviewer_notes: str
    checklist: dict[str, Any] = field(default_factory=dict)
    revised: bool = False


def _problems(check: dict[str, Any], review: list[dict[str, Any]]) -> list[str]:
    out = [f"{c['label']} ({c['detail']})" for c in check["checks"] if not c["passed"] and c["severity"] == "error"]
    out += [f"Self-check #{r['n']} failed: {r['question']} - {r['note']}" for r in review if r["passed"] is False]
    out += [
        f"Invented detail not in the note or fact sheet - remove it or replace it with a [VERIFY: ...] placeholder: {c}"
        for c in (check.get("review") or {}).get("invented_claims", [])
    ]
    return out


def evaluate(body: str, note_text: str = "") -> dict[str, Any]:
    check = run_checklist(body)
    check["self_check"], check["review"] = self_review(body, self_check_questions(), note_text)
    check["passed"] = check["passed"] and all(r["passed"] is not False for r in check["self_check"])
    return check


def produce_draft(
    note_text: str,
    triage: dict[str, Any],
    angle: NewsAngle | None,
    recent_posts: list[str],
    instruction: str | None = None,
    previous_body: str | None = None,
) -> DraftResult:
    prompt = build_draft_prompt(note_text, triage, angle, recent_posts, instruction, previous_body)
    out = write_draft(prompt)
    body = autofix(out.post)
    check = evaluate(body, note_text)
    revised = False

    problems = _problems(check, check["self_check"])
    if problems:
        log.info("Draft failed %d check(s); revising once: %s", len(problems), problems)
        new_body = autofix(revise(body, problems))
        if new_body != body:
            body, revised = new_body, True
            check = evaluate(body, note_text)

    check["revised"] = revised
    return DraftResult(body=body, reviewer_notes=out.reviewer_notes.strip(), checklist=check, revised=revised)
