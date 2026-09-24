"""Query helpers shared by the bot, API, CLI and scheduler."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlmodel import Session, col, select

from app.db.models import Draft, DraftStatus, Note, NoteStatus, utcnow

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
NOTE_EXTENSIONS = {".txt", ".md"}


def create_note(
    session: Session,
    text: str,
    *,
    source: str = "telegram",
    telegram_message_id: int | None = None,
    filename: str | None = None,
) -> Note | None:
    """Store a note. Returns None for empty text or a duplicate."""
    text = text.strip()
    if not text:
        return None
    if telegram_message_id is not None:
        existing = session.exec(select(Note).where(Note.telegram_message_id == telegram_message_id)).first()
        if existing:
            return None
    if session.exec(select(Note).where(Note.text == text)).first():
        log.info("Skipping duplicate note (%s)", filename or telegram_message_id)
        return None
    note = Note(text=text, source=source, telegram_message_id=telegram_message_id, filename=filename)
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def import_files(session: Session, files: list[tuple[str, str]], source: str = "import") -> list[Note]:
    """Import (filename, text) pairs. Duplicates are skipped."""
    created = []
    for name, text in files:
        note = create_note(session, text, source=source, filename=name)
        if note:
            created.append(note)
    return created


def read_notes_folder(folder: Path) -> list[tuple[str, str]]:
    files = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in NOTE_EXTENSIONS)
    return [(p.name, p.read_text(encoding="utf-8", errors="replace")) for p in files]


def status_counts(session: Session) -> dict[str, int]:
    counts = Counter(n.status.value for n in session.exec(select(Note)).all())
    out = {s.value: counts.get(s.value, 0) for s in NoteStatus}
    out["not_now"] = len(
        session.exec(select(Note).where(Note.status == NoteStatus.triaged, Note.publishable == False)).all()  # noqa: E712
    )
    return out


def ranked_backlog(session: Session, limit: int | None = None, threshold: int | None = None) -> list[Note]:
    """Unused triaged notes, best first. If threshold is set, only notes at or above it."""
    q = select(Note).where(Note.status == NoteStatus.triaged)
    if threshold is not None:
        q = q.where(Note.score >= threshold)
    q = q.order_by(col(Note.score).desc(), col(Note.received_at).asc())
    if limit:
        q = q.limit(limit)
    return list(session.exec(q).all())


def untriaged(session: Session) -> list[Note]:
    return list(session.exec(select(Note).where(Note.status == NoteStatus.new).order_by(col(Note.received_at))).all())


def recent_approved_drafts(session: Session, limit: int = 5) -> list[Draft]:
    q = (
        select(Draft)
        .where(Draft.status == DraftStatus.approved)
        .order_by(col(Draft.approved_at).desc())
        .limit(limit)
    )
    return list(session.exec(q).all())


def current_draft(session: Session, note_id: int) -> Draft | None:
    q = (
        select(Draft)
        .where(Draft.note_id == note_id, Draft.status != DraftStatus.superseded)
        .order_by(col(Draft.version).desc())
    )
    return session.exec(q).first()


def week_bounds_ist(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Monday 00:00 IST to next Monday 00:00 IST, returned in UTC."""
    now = (now or utcnow()).astimezone(IST)
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=7)).astimezone(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def approved_this_week(session: Session) -> list[Draft]:
    start, end = week_bounds_ist()
    drafts = session.exec(select(Draft).where(Draft.status == DraftStatus.approved)).all()
    return [d for d in drafts if (a := _aware(d.approved_at)) and start <= a < end]


def pending_drafts(session: Session) -> list[Draft]:
    q = select(Draft).where(Draft.status == DraftStatus.pending).order_by(col(Draft.created_at).desc())
    return list(session.exec(q).all())
