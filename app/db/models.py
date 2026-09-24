"""SQLite tables for notes and drafts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NoteStatus(str, Enum):
    new = "new"
    triaged = "triaged"
    drafted = "drafted"
    approved = "approved"
    discarded = "discarded"


class DraftStatus(str, Enum):
    pending = "pending"  # waiting for Meera's review
    needs_facts = "needs_facts"  # good enough to approve once its [VERIFY] markers are filled
    approved = "approved"  # approved for Meera to post manually - nothing is published
    discarded = "discarded"
    superseded = "superseded"  # replaced by a redraft


# Content pillars defined in skills/SKILL.md
CATEGORIES = [
    "Ingredient Deep-Dive",
    "Founder Story",
    "India-Specific Context",
    "Industry Transparency",
]


class Note(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    text: str
    telegram_message_id: int | None = Field(default=None, index=True)
    source: str = "telegram"  # telegram | import | upload
    filename: str | None = None
    received_at: datetime = Field(default_factory=utcnow)
    status: NoteStatus = Field(default=NoteStatus.new, index=True)

    # Triage output (AI call #1)
    score: int | None = None
    publishable: bool | None = None
    category: str | None = None
    core_insight: str | None = None
    suggested_hook_type: str | None = None
    missing_facts: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    reason: str | None = None
    triaged_at: datetime | None = None


REVIEWABLE = {DraftStatus.pending, DraftStatus.needs_facts}


class Draft(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    note_id: int = Field(foreign_key="note.id", index=True)
    version: int = 1
    body: str
    status: DraftStatus = Field(default=DraftStatus.pending, index=True)
    redraft_instruction: str | None = None

    # News angle (grounded search). All null when nothing credible was found.
    news_found: bool = False
    news_title: str | None = None
    news_source: str | None = None
    news_url: str | None = None
    news_summary: str | None = None
    news_note: str | None = None  # why it's relevant, or why no angle was used

    checklist: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    reviewer_notes: str | None = None  # placeholders to fill / claims to verify

    # Auto-review: quality score and who made the call. "approved" never publishes anything.
    quality_score: int | None = None
    decision: str | None = None  # auto_approved | auto_discarded | needs_facts | review
    decided_by: str | None = None  # auto | meera
    decision_reason: str | None = None

    telegram_message_id: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    approved_at: datetime | None = None
