from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DraftOut(BaseModel):
    id: int
    note_id: int
    version: int
    body: str
    status: str
    redraft_instruction: str | None
    news_found: bool
    news_title: str | None
    news_source: str | None
    news_url: str | None
    news_summary: str | None
    news_note: str | None
    news_published: str | None = None
    news_tier: str | None = None
    news_via: str | None = None
    sources: list[dict[str, Any]] | None = None
    first_comment: str = ""  # ready-to-paste "Sources:" text for LinkedIn's first comment
    checklist: dict[str, Any]
    reviewer_notes: str | None
    quality_score: int | None = None
    decision: str | None = None
    decided_by: str | None = None
    decision_reason: str | None = None
    telegram_message_id: int | None = None
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None


class NoteOut(BaseModel):
    id: int
    text: str
    source: str
    filename: str | None
    telegram_message_id: int | None
    received_at: datetime
    status: str
    score: int | None
    publishable: bool | None
    category: str | None
    core_insight: str | None
    suggested_hook_type: str | None
    missing_facts: list[str]
    reason: str | None
    triaged_at: datetime | None
    current_draft_id: int | None = None
    current_draft_status: str | None = None


class NoteDetail(NoteOut):
    drafts: list[DraftOut] = []


class NoteIn(BaseModel):
    text: str


class DraftEdit(BaseModel):
    body: str


class RedraftIn(BaseModel):
    instruction: str | None = None


class FillIn(BaseModel):
    answers: list[str]  # one per [VERIFY] marker, in order; empty string leaves it


class ImportResult(BaseModel):
    imported: int
    skipped: int
    notes: list[NoteOut]


class WeekOut(BaseModel):
    target: int
    approved_count: int
    week_start: datetime
    week_end: datetime
    next_run: datetime | None
    approved: list[DraftOut]
    queue: list[DraftOut]
    queue_notes: dict[int, NoteOut]


class StatusOut(BaseModel):
    counts: dict[str, int]
    model: str
    threshold: int
    gemini_configured: bool
    telegram_configured: bool
    bot_running: bool
    scheduler_running: bool
    auto_review: bool = False
    auto_approve_min: int = 8
    auto_discard_below: int = 7
    auto_counts: dict[str, int] = {}
