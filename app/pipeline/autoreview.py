"""Auto-review: score a finished draft and decide approve / discard / needs facts / human review.

"Approved" means approved for Meera to copy and post herself. Nothing here publishes anywhere.

Draft quality score (0-10):
    45%  voice score from a sceptical reviewer (would a reader believe Meera wrote it?)
    25%  share of the skill's self-check questions passed
    30%  substance of the source note (its triage score) - a post can't beat its raw material
    -2   for each hard format failure still present (length, emojis, bullets, dashes, ...)
    -3   for each invented claim (a scene/event/number presented as Meera's but not in the note)

Decision (defaults: approve >= 8, discard < 7):
    score >= approve_min
        invented claim flagged    -> review (never auto-approved)
        hard format failure left  -> review
        [VERIFY] markers left     -> needs_facts (auto-approves once Meera fills them)
        otherwise                 -> auto_approved
    score <  discard_below        -> auto_discarded, unless Meera asked for this draft -> review
                                     (the orchestrator auto-redrafts once before discarding)
    in between, or unscorable     -> review
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.pipeline.checklist import VERIFY_RE

VOICE_WEIGHT, SELF_CHECK_WEIGHT, NOTE_WEIGHT = 0.45, 0.25, 0.30
FORMAT_PENALTY, INVENTED_PENALTY = 2, 3
DEFAULT_NOTE_SCORE = 7  # used when a note was never triaged (e.g. drafted directly)


@dataclass(frozen=True)
class Decision:
    action: str  # auto_approved | auto_discarded | needs_facts | review
    reason: str


def quality_score(checklist: dict[str, Any]) -> tuple[int | None, dict[str, Any]]:
    """Return (score, breakdown). None when the reviewer couldn't score the draft."""
    review = checklist.get("review") or {}
    voice = review.get("voice_score")
    invented = list(review.get("invented_claims") or [])
    answered = [r for r in checklist.get("self_check", []) if r.get("passed") is not None]
    hard = list(checklist.get("hard_failures", []))
    note = checklist.get("note_score")
    note = DEFAULT_NOTE_SCORE if note is None else note
    if voice is None or not answered:
        return None, {"voice": voice, "self_check": None, "note_score": note, "format_failures": len(hard),
                      "invented": len(invented), "note": "reviewer unavailable"}
    passed = sum(1 for r in answered if r["passed"])
    rate = passed / len(answered)
    raw = (VOICE_WEIGHT * voice + SELF_CHECK_WEIGHT * 10 * rate + NOTE_WEIGHT * note
           - FORMAT_PENALTY * len(hard) - INVENTED_PENALTY * len(invented))
    score = max(0, min(10, round(raw)))
    return score, {
        "voice": voice,
        "self_check": f"{passed}/{len(answered)}",
        "note_score": note,
        "format_failures": len(hard),
        "invented": len(invented),
        "formula": (f"0.45x{voice} + 0.25x{round(10 * rate, 1)} + 0.3x{note}"
                    f" - 2x{len(hard)} - 3x{len(invented)} = {round(raw, 1)}"),
    }


def decide(
    score: int | None,
    checklist: dict[str, Any],
    *,
    approve_min: int = 8,
    discard_below: int = 7,
    allow_verify: bool = False,
    requested_by_meera: bool = False,
) -> Decision:
    verify = int(checklist.get("verify_count") or 0)
    hard = checklist.get("hard_failures") or []
    top = (checklist.get("review") or {}).get("top_issue")
    top = top if top and top.lower() != "none" else None

    if score is None:
        return Decision("review", "The reviewer couldn't score this draft, so it needs your eyes.")
    invented = (checklist.get("review") or {}).get("invented_claims") or []
    if score >= approve_min:
        if invented:
            return Decision("review", f"Scored {score}/10 but may contain an invented detail: {invented[0]}")
        if hard:
            return Decision("review", f"Scored {score}/10 but still has format issues: {', '.join(hard)}.")
        if verify and not allow_verify:
            return Decision("needs_facts", f"Scored {score}/10 - approves automatically once {verify} fact(s) are filled in.")
        return Decision("auto_approved", f"Scored {score}/10 (auto-approve at {approve_min}+). Ready for you to post.")
    if score < discard_below:
        why = f" Main issue: {top}" if top else ""
        if requested_by_meera:
            return Decision("review", f"Scored {score}/10, but you asked for this redraft, so it's yours to judge.{why}")
        return Decision("auto_discarded", f"Scored {score}/10 (below {discard_below}).{why}")
    return Decision("review", f"Scored {score}/10 - in the review band, so it's your call." + (f" Main issue: {top}" if top else ""))


# ---------------- filling [VERIFY] markers from Meera's reply ----------------

_NUM_PREFIX = re.compile(r"^\s*(\d{1,2})\s*[.):\-]\s*(.*)$")
SKIP_WORDS = {"-", "skip", "same", "leave", "?"}


def verify_items(body: str) -> list[str]:
    return [m.group(0)[len("[VERIFY:"):-1].strip() for m in VERIFY_RE.finditer(body)]


def parse_fill_answers(reply: str, n_items: int) -> dict[int, str]:
    """Map item number (1-based) -> answer. Accepts '1. answer' lines or plain lines in order."""
    lines = [ln.strip() for ln in reply.strip().splitlines() if ln.strip()]
    out: dict[int, str] = {}
    numbered = [m for m in (_NUM_PREFIX.match(ln) for ln in lines) if m]
    if numbered and len(numbered) == len(lines):
        for m in numbered:
            i, ans = int(m.group(1)), m.group(2).strip()
            if 1 <= i <= n_items and ans and ans.lower() not in SKIP_WORDS:
                out[i] = ans
        return out
    if n_items == 1 and lines:  # a single fact may be written across lines
        ans = " ".join(lines)
        return {} if ans.lower() in SKIP_WORDS else {1: ans}
    for i, ans in enumerate(lines[:n_items], 1):
        if ans.lower() not in SKIP_WORDS:
            out[i] = ans
    return out


def fill_verify(body: str, answers: dict[int, str]) -> tuple[str, int]:
    """Replace the numbered [VERIFY] markers with Meera's answers, verbatim. Returns (body, filled)."""
    counter = {"i": 0, "filled": 0}

    def sub(m: re.Match) -> str:
        counter["i"] += 1
        ans = answers.get(counter["i"])
        if ans is None:
            return m.group(0)
        counter["filled"] += 1
        return ans

    new = VERIFY_RE.sub(sub, body)
    new = re.sub(r"[ \t]{2,}", " ", new)
    new = re.sub(r"[ \t]+([.,;:])", r"\1", new)
    return new, counter["filled"]
