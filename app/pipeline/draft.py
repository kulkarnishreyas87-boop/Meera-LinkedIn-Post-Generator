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
        }
    },
    "required": ["answers"],
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
    return (
        "NEWS ANGLE (verified via Google Search - use it, don't invent beyond it):\n"
        f"- Headline: {angle.title}\n- Outlet: {angle.source}\n- URL (do not put the URL in the post): {angle.url}\n"
        f"- What it says: {angle.summary or '(no summary)'}\n- Why it's relevant: {angle.note or ''}\n"
        "Work it in naturally, usually in the hook or where the mechanism meets the real world, and name the "
        "outlet in prose. Only state figures from it that appear above; if you need a figure from it that is "
        "not above, use a [VERIFY: ...] marker. It must not take over the post - the note's insight is the spine."
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


def self_review(body: str, questions: list[str]) -> list[dict[str, Any]]:
    """Model answers the skill's self-check questions for this draft."""
    if not questions:
        return []
    qs = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    prompt = (
        "Review this draft strictly against the skill's self-check questions. Be critical: "
        "answer passed=false if there is any real doubt, and say why in one short sentence.\n\n"
        f"QUESTIONS:\n{qs}\n\nDRAFT:\n\"\"\"\n{body}\n\"\"\""
    )
    try:
        resp = gemini.generate(prompt, system=system_instruction(), json_schema=REVIEW_SCHEMA, temperature=0.1)
        data = json.loads(gemini.response_text(resp))
        answers = {a.n: a for a in (_ReviewAnswer.model_validate(x) for x in data.get("answers", []))}
    except (json.JSONDecodeError, ValidationError, gemini.GeminiUnavailable) as exc:
        log.warning("Self-review failed: %s", exc)
        return [{"n": i, "question": q, "passed": None, "note": "Self-review unavailable"} for i, q in enumerate(questions, 1)]
    return [
        {
            "n": i,
            "question": q,
            "passed": answers[i].passed if i in answers else None,
            "note": answers[i].note if i in answers else "",
        }
        for i, q in enumerate(questions, 1)
    ]


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
    return out


def evaluate(body: str) -> dict[str, Any]:
    check = run_checklist(body)
    check["self_check"] = self_review(body, self_check_questions())
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
    check = evaluate(body)
    revised = False

    problems = _problems(check, check["self_check"])
    if problems:
        log.info("Draft failed %d check(s); revising once: %s", len(problems), problems)
        new_body = autofix(revise(body, problems))
        if new_body != body:
            body, revised = new_body, True
            check = evaluate(body)

    check["revised"] = revised
    return DraftResult(body=body, reviewer_notes=out.reviewer_notes.strip(), checklist=check, revised=revised)
