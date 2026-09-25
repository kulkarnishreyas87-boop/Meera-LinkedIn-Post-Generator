"""REST API for the dashboard. There is deliberately no endpoint that publishes anywhere."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, col, select

from app import scheduler
from app.api.schemas import (
    DraftEdit,
    DraftOut,
    FillIn,
    ImportResult,
    NoteDetail,
    NoteIn,
    NoteOut,
    RedraftIn,
    StatusOut,
    WeekOut,
)
from app.config import get_settings
from app.db import repo
from app.db.models import Draft, DraftStatus, Note, NoteStatus
from app.db.session import get_session
from app.pipeline import orchestrator
from app.pipeline.gemini import GeminiUnavailable
from app.pipeline.sources import first_comment_text

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
runtime = {"bot_running": False}


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def draft_out(d: Draft) -> DraftOut:
    data = d.model_dump()
    for k in ("created_at", "updated_at", "approved_at"):
        data[k] = _utc(data[k])
    data["status"] = d.status.value
    data["checklist"] = d.checklist or {}
    data["sources"] = d.sources or []
    data["first_comment"] = first_comment_text(d.sources or [])
    return DraftOut(**data)


def note_out(n: Note, session: Session, cls=NoteOut, **extra) -> NoteOut:
    current = repo.current_draft(session, n.id)
    data = n.model_dump()
    data["received_at"] = _utc(n.received_at)
    data["triaged_at"] = _utc(n.triaged_at)
    data["status"] = n.status.value
    data["missing_facts"] = n.missing_facts or []
    return cls(
        **data,
        current_draft_id=current.id if current else None,
        current_draft_status=current.status.value if current else None,
        **extra,
    )


def _run(fn, *args, **kwargs):
    """Map pipeline errors to HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except orchestrator.NothingToDraft as exc:
        raise HTTPException(404, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except GeminiUnavailable as exc:
        raise HTTPException(503, "Gemini is unavailable or rate-limited. Try again in a few minutes.") from exc
    except RuntimeError as exc:  # e.g. missing GEMINI_API_KEY
        log.exception("Pipeline error")
        raise HTTPException(400, str(exc)) from exc


async def _arun(coro):
    try:
        return await coro
    except orchestrator.NothingToDraft as exc:
        raise HTTPException(404, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except GeminiUnavailable as exc:
        raise HTTPException(503, "Gemini is unavailable or rate-limited. Try again in a few minutes.") from exc
    except RuntimeError as exc:
        log.exception("Pipeline error")
        raise HTTPException(400, str(exc)) from exc


# ---------------- status ----------------

@router.get("/status", response_model=StatusOut)
def status(session: Session = Depends(get_session)):
    s = get_settings()
    return StatusOut(
        counts=repo.status_counts(session),
        model=s.gemini_model,
        threshold=s.triage_threshold,
        gemini_configured=bool(s.gemini_api_key),
        telegram_configured=bool(s.telegram_bot_token and s.telegram_chat_id is not None),
        bot_running=runtime["bot_running"],
        scheduler_running=scheduler.next_run() is not None,
        auto_review=s.auto_review,
        auto_approve_min=s.auto_approve_min,
        auto_discard_below=s.auto_discard_below,
        auto_counts=repo.auto_decision_counts(session),
    )


# ---------------- notes ----------------

@router.get("/notes", response_model=list[NoteOut])
def list_notes(status: str | None = None, category: str | None = None, session: Session = Depends(get_session)):
    q = select(Note).order_by(col(Note.received_at).desc())
    if status == "not_now":
        q = q.where(Note.status == NoteStatus.triaged, Note.publishable == False)  # noqa: E712
    elif status:
        q = q.where(Note.status == NoteStatus(status))
    if category:
        q = q.where(Note.category == category)
    return [note_out(n, session) for n in session.exec(q).all()]


@router.post("/notes", response_model=NoteOut)
def create_note(body: NoteIn, session: Session = Depends(get_session)):
    note = repo.create_note(session, body.text, source="upload")
    if not note:
        raise HTTPException(409, "Empty or duplicate note.")
    return note_out(note, session)


@router.get("/notes/{note_id}", response_model=NoteDetail)
def get_note(note_id: int, session: Session = Depends(get_session)):
    note = session.get(Note, note_id)
    if not note:
        raise HTTPException(404, "Note not found")
    drafts = session.exec(select(Draft).where(Draft.note_id == note_id).order_by(col(Draft.version).desc())).all()
    return note_out(note, session, cls=NoteDetail, drafts=[draft_out(d) for d in drafts])


@router.post("/notes/import", response_model=ImportResult)
async def import_notes(files: list[UploadFile] = File(...), session: Session = Depends(get_session)):
    pairs = []
    for f in files:
        name = f.filename or "note.txt"
        if not name.lower().endswith((".txt", ".md")):
            continue
        raw = await f.read()
        pairs.append((name.rsplit("/", 1)[-1], raw.decode("utf-8", errors="replace")))
    created = repo.import_files(session, pairs, source="upload")
    return ImportResult(imported=len(created), skipped=len(pairs) - len(created), notes=[note_out(n, session) for n in created])


@router.post("/notes/{note_id}/triage", response_model=NoteOut)
def triage(note_id: int, session: Session = Depends(get_session)):
    note = _run(orchestrator.triage_note, note_id)
    return note_out(session.get(Note, note.id), session)


@router.post("/triage-pending", response_model=list[NoteOut])
def triage_pending(session: Session = Depends(get_session)):
    notes = _run(orchestrator.triage_pending)
    return [note_out(session.get(Note, n.id), session) for n in notes]


@router.post("/notes/{note_id}/draft", response_model=DraftOut)
async def draft_note(note_id: int, body: RedraftIn | None = None):
    instruction = body.instruction if body else None
    return draft_out(await _arun(orchestrator.draft_note_async(note_id, instruction=instruction)))


@router.post("/draft-next", response_model=DraftOut)
async def draft_next():
    return draft_out(await _arun(orchestrator.draft_next_best_async()))


@router.get("/backlog", response_model=list[NoteOut])
def backlog(session: Session = Depends(get_session)):
    ranked = repo.ranked_backlog(session)
    return [note_out(n, session) for n in ranked + repo.untriaged(session)]


# ---------------- drafts ----------------

@router.get("/drafts/{draft_id}", response_model=DraftOut)
def get_draft(draft_id: int, session: Session = Depends(get_session)):
    d = session.get(Draft, draft_id)
    if not d:
        raise HTTPException(404, "Draft not found")
    return draft_out(d)


@router.patch("/drafts/{draft_id}", response_model=DraftOut)
def edit_draft(draft_id: int, body: DraftEdit):
    if not body.body.strip():
        raise HTTPException(422, "Draft cannot be empty.")
    return draft_out(_run(orchestrator.update_draft_body, draft_id, body.body))


@router.post("/drafts/{draft_id}/approve", response_model=DraftOut)
def approve(draft_id: int):
    """Marks the draft approved for Meera to post manually. Publishes nothing."""
    return draft_out(_run(orchestrator.set_draft_status, draft_id, DraftStatus.approved))


@router.post("/drafts/{draft_id}/discard", response_model=DraftOut)
def discard(draft_id: int):
    return draft_out(_run(orchestrator.set_draft_status, draft_id, DraftStatus.discarded))


@router.post("/drafts/{draft_id}/reopen", response_model=DraftOut)
def reopen(draft_id: int):
    """Undo an (auto-)approval or restore an (auto-)discarded draft back to review."""
    return draft_out(_run(orchestrator.reopen_draft, draft_id))


@router.post("/drafts/{draft_id}/fill", response_model=DraftOut)
def fill(draft_id: int, body: FillIn):
    """Fill [VERIFY] markers in order. May auto-approve if the draft then clears the bar."""
    reply = "\n".join(f"{i}. {a.strip() or 'skip'}" for i, a in enumerate(body.answers, 1))
    draft, filled, _ = _run(orchestrator.fill_facts, draft_id, reply)
    if not filled:
        raise HTTPException(422, "No facts were filled.")
    return draft_out(draft)


@router.post("/drafts/{draft_id}/redraft", response_model=DraftOut)
async def redraft(draft_id: int, body: RedraftIn, session: Session = Depends(get_session)):
    d = session.get(Draft, draft_id)
    if not d:
        raise HTTPException(404, "Draft not found")
    return draft_out(await _arun(orchestrator.draft_note_async(d.note_id, instruction=body.instruction or "")))


# ---------------- this week ----------------

@router.get("/week", response_model=WeekOut)
def week(session: Session = Depends(get_session)):
    start, end = repo.week_bounds_ist()
    approved = repo.approved_this_week(session)
    queue = repo.pending_drafts(session)
    notes = {d.note_id: note_out(session.get(Note, d.note_id), session) for d in queue + approved}
    return WeekOut(
        target=3,
        approved_count=len(approved),
        week_start=start,
        week_end=end,
        next_run=scheduler.next_run(),
        approved=[draft_out(d) for d in approved],
        queue=[draft_out(d) for d in queue],
        queue_notes=notes,
    )
