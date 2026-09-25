"""Instant trigger on new Telegram notes, and the already-published duplicate guard."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest
from sqlmodel import SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.bot import handlers
from app.db import repo
from app.db import session as db_session
from app.db.models import Note, NoteStatus
from app.pipeline import duplicates, orchestrator, triage


# ---------------- duplicate guard ----------------

def test_published_posts_are_loaded_from_the_skill():
    assert len(duplicates.published_posts()) == 4


def test_verbatim_published_post_is_caught():
    heading, text = duplicates.published_posts()[0]
    match = duplicates.match_published("Category: Ingredient Deep-Dive\n" + text)
    assert match and match[0] == heading and match[1] > 0.9


def test_original_notes_are_not_flagged():
    for path in ["samples/01-azelaic-pharmacy-shelf.txt", "samples/02-monsoon-stability.md", "samples/04-clinically-tested-deck.txt"]:
        assert duplicates.match_published(open(path, encoding="utf-8").read()) is None


def test_short_notes_are_never_flagged():
    assert duplicates.match_published("niacinamide converts to niacin at low pH") is None


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db_session.set_engine(engine)
    from app.db import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    yield
    db_session.set_engine(None)


def test_duplicate_note_skips_gemini_and_is_parked(db, monkeypatch):
    monkeypatch.setattr(triage.gemini, "generate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no AI call")))
    _, text = duplicates.published_posts()[0]
    with db_session.session_scope() as s:
        nid = repo.create_note(s, text).id
    note = orchestrator.triage_note(nid)
    assert note.publishable is False and note.score == 0 and note.status == NoteStatus.triaged
    assert "already-published" in note.reason


# ---------------- instant trigger in the bot ----------------

class FakeBot:
    """DraftBot with Telegram I/O replaced by a message list."""

    def __init__(self, settings):
        self.settings = settings
        self.chat_id = settings.telegram_chat_id
        self.sent: list[str] = []

    async def say(self, text, **kw):
        self.sent.append(text)
        return NS(message_id=len(self.sent))


def _settings(**kw):
    base = orchestrator.get_settings()
    return replace(base, telegram_chat_id=-100123, instant_draft=True, **kw)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_publishable_note_is_scored_and_drafted_immediately(monkeypatch):
    bot = FakeBot(_settings())
    note = NS(id=7, score=8, publishable=True, category="Ingredient Deep-Dive", reason="Specific scene.")
    drafted = []
    monkeypatch.setattr(orchestrator, "triage_note", lambda nid: note)

    async def fake_draft(nid, **kw):
        drafted.append(nid)

    monkeypatch.setattr(orchestrator, "draft_note_async", fake_draft)
    run(handlers.DraftBot._process_new_note(bot, 7))
    assert drafted == [7]
    assert "8/10" in bot.sent[0] and "Drafting now" in bot.sent[0] and "Google News" in bot.sent[0]


def test_weak_note_is_acknowledged_but_not_drafted(monkeypatch):
    bot = FakeBot(_settings())
    note = NS(id=8, score=3, publishable=False, category="Industry Transparency", reason="No thesis yet.")
    monkeypatch.setattr(orchestrator, "triage_note", lambda nid: note)

    async def boom(*a, **k):
        raise AssertionError("should not draft")

    monkeypatch.setattr(orchestrator, "draft_note_async", boom)
    run(handlers.DraftBot._process_new_note(bot, 8))
    assert "3/10" in bot.sent[0] and "not now" in bot.sent[0] and "nothing is deleted" in bot.sent[0]


def test_gemini_outage_on_arrival_is_reported_not_crashed(monkeypatch):
    bot = FakeBot(_settings())

    def busy(nid):
        raise handlers.GeminiUnavailable("429")

    monkeypatch.setattr(orchestrator, "triage_note", busy)
    run(handlers.DraftBot._process_new_note(bot, 9))
    assert "Saved note #9" in bot.sent[0] and "busy" in bot.sent[0]
