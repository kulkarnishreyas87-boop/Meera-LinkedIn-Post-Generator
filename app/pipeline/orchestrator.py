"""Runs the pipeline against the database. Sync core + async wrappers that notify Telegram.

Nothing here (or anywhere in this app) publishes to LinkedIn. "Approve" only records that
Meera has approved a draft to copy and post herself.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable

from app.config import get_settings
from app.db import repo
from app.db.models import REVIEWABLE, Draft, DraftStatus, Note, NoteStatus, utcnow
from app.db.session import session_scope
from app.pipeline import autoreview
from app.pipeline.checklist import run_checklist
from app.pipeline.draft import DraftResult, produce_draft
from app.pipeline.gemini import GeminiUnavailable
from app.pipeline.research import NewsAngle, find_news_angle
from app.pipeline.triage import TriageResult, is_publishable, triage_text

log = logging.getLogger(__name__)

# One pipeline run at a time per process: avoids double-drafting a note from bot + dashboard.
_pipeline_lock = threading.Lock()

DraftNotifier = Callable[[int], Awaitable[None]]
_notifiers: list[DraftNotifier] = []


def register_notifier(fn: DraftNotifier) -> None:
    _notifiers.append(fn)


def clear_notifiers() -> None:
    _notifiers.clear()


class NothingToDraft(LookupError):
    pass


# ---------------- triage ----------------

def triage_note(note_id: int) -> Note:
    threshold = get_settings().triage_threshold
    with session_scope() as s:
        note = s.get(Note, note_id)
        if note is None:
            raise LookupError(f"Note {note_id} not found")
        text = note.text
    result: TriageResult = triage_text(text, threshold)
    with session_scope() as s:
        note = s.get(Note, note_id)
        note.score = result.score
        note.publishable = is_publishable(result, threshold)
        note.category = result.category
        note.core_insight = result.core_insight
        note.suggested_hook_type = result.suggested_hook_type
        note.missing_facts = result.missing_facts
        note.reason = result.reason
        note.triaged_at = utcnow()
        if note.status == NoteStatus.new:
            note.status = NoteStatus.triaged
        s.add(note)
        s.commit()
        s.refresh(note)
        log.info("Triaged note %s: score=%s publishable=%s", note.id, note.score, note.publishable)
        return note


def triage_pending() -> list[Note]:
    with session_scope() as s:
        ids = [n.id for n in repo.untriaged(s)]
    if ids:
        get_settings().require_gemini()  # fail loudly on missing config, not "nothing to draft"
    out = []
    for nid in ids:
        try:
            out.append(triage_note(nid))
        except GeminiUnavailable:
            raise  # rate limit / outage affects every note; stop and report it
        except Exception:  # keep going; one malformed note shouldn't stop the batch
            log.exception("Triage failed for note %s", nid)
    return out


# ---------------- drafting ----------------

def _triage_dict(note: Note) -> dict:
    return {
        "score": note.score,
        "category": note.category,
        "core_insight": note.core_insight,
        "suggested_hook_type": note.suggested_hook_type,
        "missing_facts": note.missing_facts or [],
        "reason": note.reason,
    }


def draft_note(note_id: int, instruction: str | None = None, reuse_angle: bool = True) -> Draft:
    """Draft (or redraft) a note. A redraft supersedes the current pending draft."""
    with _pipeline_lock:
        with session_scope() as s:
            note = s.get(Note, note_id)
            if note is None:
                raise LookupError(f"Note {note_id} not found")
        if note.status == NoteStatus.new:
            note = triage_note(note_id)

        with session_scope() as s:
            previous = repo.current_draft(s, note_id)
            recent = [d.body for d in repo.recent_approved_drafts(s, limit=5) if d.note_id != note_id]

        if previous and reuse_angle:
            angle = NewsAngle(
                found=previous.news_found, title=previous.news_title, source=previous.news_source,
                url=previous.news_url, summary=previous.news_summary, note=previous.news_note,
            )
        else:
            angle = find_news_angle(note.text, note.category, note.core_insight)

        requested_by_meera = instruction is not None
        result = produce_draft(
            note.text,
            _triage_dict(note),
            angle,
            recent,
            instruction=instruction,
            previous_body=previous.body if (previous and requested_by_meera) else None,
        )
        result.checklist["note_score"] = note.score
        score, breakdown = autoreview.quality_score(result.checklist)
        decision = _decide(score, result.checklist, requested_by_meera)

        # Below the bar: give it one automatic redraft with the reviewer's feedback before discarding.
        if decision and decision.action == "auto_discarded":
            first_score = score
            retry = produce_draft(
                note.text, _triage_dict(note), angle, recent,
                instruction=_retry_instruction(result),
                previous_body=result.body,
            )
            retry.checklist["note_score"] = note.score
            score, breakdown = autoreview.quality_score(retry.checklist)
            retry.checklist["auto_redraft_of_score"] = first_score
            result = retry
            decision = _decide(score, result.checklist, requested_by_meera)
            log.info("Auto-redraft of note %s: %s -> %s", note_id, first_score, score)
        result.checklist["quality"] = {"score": score, **breakdown}

        with session_scope() as s:
            if previous and previous.status in REVIEWABLE:
                prev = s.get(Draft, previous.id)
                prev.status = DraftStatus.superseded
                s.add(prev)
            draft = Draft(
                note_id=note_id,
                version=(previous.version + 1) if previous else 1,
                body=result.body,
                reviewer_notes=result.reviewer_notes,
                checklist=result.checklist,
                redraft_instruction=instruction,
                news_found=angle.found,
                news_title=angle.title,
                news_source=angle.source,
                news_url=angle.url,
                news_summary=angle.summary,
                news_note=angle.note,
                quality_score=score,
            )
            n = s.get(Note, note_id)
            n.status = NoteStatus.drafted
            _apply_decision(draft, n, decision)
            s.add(draft)
            s.add(n)
            s.commit()
            s.refresh(draft)
            log.info("Drafted note %s -> draft %s v%s (%s words, score %s, %s)", note_id, draft.id, draft.version,
                     result.checklist.get("word_count"), score, draft.decision or "manual review")
            return draft


def _decide(score, checklist: dict, requested_by_meera: bool):
    s = get_settings()
    if not s.auto_review:
        return None
    return autoreview.decide(
        score, checklist,
        approve_min=s.auto_approve_min, discard_below=s.auto_discard_below,
        allow_verify=s.auto_approve_with_verify, requested_by_meera=requested_by_meera,
    )


def _retry_instruction(result: DraftResult) -> str:
    c = result.checklist
    issues = [f"{x['label']} ({x['detail']})" for x in c.get("checks", []) if not x["passed"] and x["severity"] == "error"]
    issues += [f"{r['question']} - {r['note']}" for r in c.get("self_check", []) if r.get("passed") is False]
    review = c.get("review") or {}
    issues = [f"remove invented detail (not in the note or fact sheet): {x}" for x in review.get("invented_claims", [])] + issues
    top = review.get("top_issue")
    if top and top.lower() != "none":
        issues.insert(0, top)
    fixes = "; ".join(issues[:5]) or "make it sound more like her published posts"
    return "Automatic redraft - the previous version scored too low. Fix: " + fixes


def _apply_decision(draft: Draft, note: Note, decision, by: str = "auto") -> None:
    """Set statuses from an auto-review decision. Never publishes anything."""
    if decision is None:
        draft.status, draft.decision, draft.decided_by, draft.decision_reason = DraftStatus.pending, None, None, None
        return
    draft.decision, draft.decision_reason = decision.action, decision.reason
    draft.decided_by = by if decision.action in {"auto_approved", "auto_discarded"} else None
    if decision.action == "auto_approved":
        draft.status, draft.approved_at = DraftStatus.approved, utcnow()
        note.status = NoteStatus.approved
    elif decision.action == "auto_discarded":
        draft.status = DraftStatus.discarded
        note.status = NoteStatus.discarded
    elif decision.action == "needs_facts":
        draft.status = DraftStatus.needs_facts
        note.status = NoteStatus.drafted
    else:
        draft.status = DraftStatus.pending
        note.status = NoteStatus.drafted


def next_best_note_id() -> int | None:
    """Best unused, publishable note. Triage new notes first so they compete fairly."""
    triage_pending()
    with session_scope() as s:
        best = repo.ranked_backlog(s, limit=1, threshold=get_settings().triage_threshold)
        return best[0].id if best else None


def draft_next_best() -> Draft:
    nid = next_best_note_id()
    if nid is None:
        raise NothingToDraft("No publishable notes in the backlog.")
    return draft_note(nid)


def weekly_run(count: int = 3) -> list[Draft]:
    """Monday job: rank untriaged + triaged notes and draft the top `count`."""
    triage_pending()
    with session_scope() as s:
        ids = [n.id for n in repo.ranked_backlog(s, limit=count, threshold=get_settings().triage_threshold)]
    drafts = []
    for nid in ids:
        try:
            drafts.append(draft_note(nid))
        except Exception:
            log.exception("Weekly draft failed for note %s", nid)
    return drafts


# ---------------- review actions (no publishing) ----------------

def set_draft_status(draft_id: int, status: DraftStatus) -> Draft:
    with session_scope() as s:
        draft = s.get(Draft, draft_id)
        if draft is None:
            raise LookupError(f"Draft {draft_id} not found")
        draft.status = status
        draft.updated_at = utcnow()
        draft.decided_by = "meera"
        draft.decision = {DraftStatus.approved: "approved", DraftStatus.discarded: "discarded"}.get(status, draft.decision)
        note = s.get(Note, draft.note_id)
        if status == DraftStatus.approved:
            draft.approved_at = utcnow()
            note.status = NoteStatus.approved
        elif status == DraftStatus.discarded:
            note.status = NoteStatus.discarded
        s.add(draft)
        s.add(note)
        s.commit()
        s.refresh(draft)
        return draft


def _rescore_after_human_change(draft: Draft, note: Note) -> None:
    """Refresh code checks after Meera edits or fills facts. Keeps the model's review.

    A human change can promote a draft (needs facts -> approved) but never auto-discards it.
    """
    old = draft.checklist or {}
    check = run_checklist(draft.body)
    for key in ("self_check", "review", "revised", "auto_redraft_of_score", "note_score"):
        if key in old:
            check[key] = old[key]
    check["edited"] = True
    check["passed"] = check["passed"] and all(r.get("passed") is not False for r in check.get("self_check", []))
    score, breakdown = autoreview.quality_score(check)
    check["quality"] = {"score": score, **breakdown}
    draft.checklist, draft.quality_score = check, score
    if draft.status in REVIEWABLE:
        decision = _decide(score, check, requested_by_meera=True)
        if decision is not None:
            _apply_decision(draft, note, decision)
        elif draft.status == DraftStatus.needs_facts and not check.get("verify_count"):
            draft.status = DraftStatus.pending


def update_draft_body(draft_id: int, body: str) -> Draft:
    with session_scope() as s:
        draft = s.get(Draft, draft_id)
        if draft is None:
            raise LookupError(f"Draft {draft_id} not found")
        note = s.get(Note, draft.note_id)
        draft.body = body.strip()
        _rescore_after_human_change(draft, note)
        draft.updated_at = utcnow()
        s.add(draft)
        s.add(note)
        s.commit()
        s.refresh(draft)
        return draft


def fill_facts(draft_id: int, reply: str) -> tuple[Draft, int, int]:
    """Fill [VERIFY] markers from Meera's reply. Returns (draft, filled, still_missing)."""
    with session_scope() as s:
        draft = s.get(Draft, draft_id)
        if draft is None:
            raise LookupError(f"Draft {draft_id} not found")
        note = s.get(Note, draft.note_id)
        items = autoreview.verify_items(draft.body)
        answers = autoreview.parse_fill_answers(reply, len(items))
        draft.body, filled = autoreview.fill_verify(draft.body, answers)
        if filled:
            _rescore_after_human_change(draft, note)
            draft.updated_at = utcnow()
            s.add(draft)
            s.add(note)
            s.commit()
            s.refresh(draft)
        return draft, filled, len(autoreview.verify_items(draft.body))


def reopen_draft(draft_id: int) -> Draft:
    """Undo an approval or restore a discarded draft back to review."""
    with session_scope() as s:
        draft = s.get(Draft, draft_id)
        if draft is None:
            raise LookupError(f"Draft {draft_id} not found")
        if draft.status == DraftStatus.superseded:
            raise LookupError("That version was replaced by a newer draft.")
        note = s.get(Note, draft.note_id)
        verify = (draft.checklist or {}).get("verify_count")
        draft.status = DraftStatus.needs_facts if verify else DraftStatus.pending
        draft.approved_at = None
        draft.decided_by, draft.decision = "meera", "review"
        draft.decision_reason = "Moved back to review by you."
        draft.updated_at = utcnow()
        note.status = NoteStatus.drafted
        s.add(draft)
        s.add(note)
        s.commit()
        s.refresh(draft)
        return draft


# ---------------- async wrappers ----------------

async def notify(draft_id: int) -> None:
    for fn in list(_notifiers):
        try:
            await fn(draft_id)
        except Exception:
            log.exception("Draft notifier failed for draft %s", draft_id)


async def draft_note_async(note_id: int, instruction: str | None = None, notify_telegram: bool = True) -> Draft:
    draft = await asyncio.to_thread(draft_note, note_id, instruction)
    if notify_telegram:
        await notify(draft.id)
    return draft


async def draft_next_best_async(notify_telegram: bool = True) -> Draft:
    draft = await asyncio.to_thread(draft_next_best)
    if notify_telegram:
        await notify(draft.id)
    return draft


async def weekly_run_async(count: int = 3) -> list[Draft]:
    drafts = await asyncio.to_thread(weekly_run, count)
    for d in drafts:
        await notify(d.id)
    return drafts
