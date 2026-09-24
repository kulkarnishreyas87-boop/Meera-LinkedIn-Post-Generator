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
from app.db.models import Draft, DraftStatus, Note, NoteStatus, utcnow
from app.db.session import session_scope
from app.pipeline.draft import produce_draft
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

        result = produce_draft(
            note.text,
            _triage_dict(note),
            angle,
            recent,
            instruction=instruction,
            previous_body=previous.body if (previous and instruction is not None) else None,
        )

        with session_scope() as s:
            if previous and previous.status == DraftStatus.pending:
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
            )
            s.add(draft)
            n = s.get(Note, note_id)
            n.status = NoteStatus.drafted
            s.add(n)
            s.commit()
            s.refresh(draft)
            log.info("Drafted note %s -> draft %s v%s (%s words)", note_id, draft.id, draft.version,
                     result.checklist.get("word_count"))
            return draft


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


def update_draft_body(draft_id: int, body: str) -> Draft:
    from app.pipeline.checklist import run_checklist

    with session_scope() as s:
        draft = s.get(Draft, draft_id)
        if draft is None:
            raise LookupError(f"Draft {draft_id} not found")
        draft.body = body.strip()
        # Keep the model's self-check, refresh the deterministic checks.
        self_check = (draft.checklist or {}).get("self_check", [])
        check = run_checklist(draft.body)
        check["self_check"] = self_check
        check["edited"] = True
        check["passed"] = check["passed"] and all(r.get("passed") is not False for r in self_check)
        draft.checklist = check
        draft.updated_at = utcnow()
        s.add(draft)
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
