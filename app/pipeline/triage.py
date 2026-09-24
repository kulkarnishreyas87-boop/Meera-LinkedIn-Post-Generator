"""AI call #1: score a raw note and decide whether it is worth developing into a post."""

from __future__ import annotations

import json
import logging
import re
from typing import Literal, get_args

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.db.models import CATEGORIES
from app.pipeline import gemini
from app.pipeline.skill import system_instruction

log = logging.getLogger(__name__)

Category = Literal["Ingredient Deep-Dive", "Founder Story", "India-Specific Context", "Industry Transparency"]
HookType = Literal["counterintuitive claim", "dated scene", "hard data point", "observed anecdote"]
assert list(get_args(Category)) == CATEGORIES  # keep in sync with the skill's pillars


class TriageResult(BaseModel):
    score: int = Field(ge=0, le=10)
    publishable: bool
    category: Category
    core_insight: str = Field(min_length=1)
    suggested_hook_type: HookType
    missing_facts: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @field_validator("score", mode="before")
    @classmethod
    def _round_score(cls, v):
        # Models sometimes return 7.5 or "8"; accept and round.
        if isinstance(v, str):
            v = float(v.strip())
        if isinstance(v, float):
            v = round(v)
        return v


class TriageParseError(ValueError):
    pass


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_triage(raw: str) -> TriageResult:
    """Parse and validate the model's JSON. Tolerates code fences and surrounding prose."""
    text = _FENCE.sub("", raw.strip())
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise TriageParseError(f"No JSON object in response: {raw[:200]!r}")
        text = text[start : end + 1]
    try:
        return TriageResult.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise TriageParseError(str(exc)) from exc


TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 10},
        "publishable": {"type": "boolean"},
        "category": {"type": "string", "enum": CATEGORIES},
        "core_insight": {"type": "string"},
        "suggested_hook_type": {"type": "string", "enum": list(get_args(HookType))},
        "missing_facts": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["score", "publishable", "category", "core_insight", "suggested_hook_type", "missing_facts", "reason"],
}

TRIAGE_PROMPT = """\
You are triaging one of Meera Pillai's raw notes (an observation, two-liner or voice-note
transcription) to decide whether it is worth developing into a LinkedIn post in her voice,
as defined by the skill in your system instruction.

Score the note 0-10 on these criteria, weighted roughly equally:
1. A specific fact, number, date or scene (her voice runs on specifics).
2. A clear thesis - one plain claim the post could argue.
3. Fit with her stated positions and content pillars (and no contradiction of her facts).
4. Enough substance for a 400-550 word post with a full mechanism section.

Rules:
- category must be exactly one content pillar from the skill.
- suggested_hook_type must be one of the four hook moves in the skill.
- missing_facts lists Skinstinct-specific numbers, dates or events the post would need but the
  note does not supply and the fact sheet does not contain. Do not invent them.
- publishable is true only if the note could become a strong post now (score {threshold}+).
- reason is one sentence Meera can read at a glance.

Return only the JSON object.

NOTE:
\"\"\"
{note}
\"\"\"
"""


def triage_text(note_text: str, threshold: int) -> TriageResult:
    """Call Gemini, validate JSON, retry once on a parse failure."""
    prompt = TRIAGE_PROMPT.format(note=note_text.strip(), threshold=threshold)
    last_error: Exception | None = None
    for attempt in (1, 2):
        resp = gemini.generate(prompt, system=system_instruction(), json_schema=TRIAGE_SCHEMA, temperature=0.2)
        raw = gemini.response_text(resp)
        try:
            return parse_triage(raw)
        except TriageParseError as exc:
            last_error = exc
            log.warning("Triage JSON parse failed (attempt %d): %s", attempt, exc)
            prompt += "\n\nYour previous reply was not valid JSON for the schema. Return only the JSON object."
    raise TriageParseError(f"Triage failed after retry: {last_error}")


def is_publishable(result: TriageResult, threshold: int) -> bool:
    return result.publishable and result.score >= threshold
