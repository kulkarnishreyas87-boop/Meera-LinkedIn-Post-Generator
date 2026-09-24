"""End-to-end pipeline with Gemini stubbed out: import -> triage -> draft -> approve."""

import json

import pytest
from sqlmodel import SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.db import repo, session as db_session
from app.db.models import DraftStatus, NoteStatus
from app.pipeline import draft as draft_mod
from app.pipeline import orchestrator, research, triage
from app.pipeline.draft import self_check_questions
from app.pipeline.skill import load_skill_text, system_instruction

GOOD_POST = "\n\n".join(
    ["In 2021 I was sitting in a stability review meeting and the pH was 3.2. This is legal. It is also not "
     "helpful, because the pH decides whether the active does anything. I have seen this misunderstood by "
     "customers, by other brands, and by us in our early formulations, so it is worth going through properly."] * 8
)


class R:
    def __init__(self, text):
        self.text = text
        self.candidates = []


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db_session.set_engine(engine)
    from app.db import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    yield
    db_session.set_engine(None)


@pytest.fixture
def fake_gemini(monkeypatch):
    def gen(prompt, *, system=None, json_schema=None, google_search=False, temperature=0.7):
        if json_schema is triage.TRIAGE_SCHEMA:
            score = 3 if "lol" in prompt else 8
            return R(json.dumps({
                "score": score, "publishable": score >= 7, "category": "Ingredient Deep-Dive",
                "core_insight": "x", "suggested_hook_type": "dated scene", "missing_facts": [], "reason": "r",
            }))
        if json_schema is draft_mod.REVIEW_SCHEMA:
            return R(json.dumps({"answers": [{"n": i, "passed": True, "note": "ok"} for i in range(1, 9)]}))
        if json_schema is draft_mod.DRAFT_SCHEMA:
            return R(json.dumps({"post": GOOD_POST, "reviewer_notes": "none"}))
        raise AssertionError("unexpected call")

    for mod in (triage.gemini, draft_mod.gemini):
        monkeypatch.setattr(mod, "generate", gen)
    from dataclasses import replace

    settings = replace(orchestrator.get_settings(), gemini_api_key="test-key", triage_threshold=7)
    monkeypatch.setattr(orchestrator, "get_settings", lambda: settings)
    monkeypatch.setattr(orchestrator, "find_news_angle",
                        lambda *a: research.NewsAngle(found=False, note="No news angle used: test"))


def test_skill_loaded_verbatim():
    skill = load_skill_text()
    assert system_instruction().startswith(skill)
    assert "facts-and-positions.md" in system_instruction()
    assert len(self_check_questions()) == 8


def test_full_pipeline(db, fake_gemini):
    with db_session.session_scope() as s:
        repo.import_files(s, [("a.txt", "Pharmacy in Bandra, azelaic acid 10%"), ("b.txt", "crowded lol")])
        repo.import_files(s, [("a2.txt", "Pharmacy in Bandra, azelaic acid 10%")])  # duplicate skipped
        assert repo.status_counts(s)["new"] == 2

    draft = orchestrator.draft_next_best()
    assert draft.checklist["passed"]
    assert draft.news_found is False and "test" in draft.news_note

    with db_session.session_scope() as s:
        counts = repo.status_counts(s)
    assert counts["drafted"] == 1 and counts["not_now"] == 1  # weak note kept, never deleted

    redraft = orchestrator.draft_note(draft.note_id, instruction="shorter")
    assert redraft.version == 2
    with db_session.session_scope() as s:
        assert s.get(type(draft), draft.id).status == DraftStatus.superseded

    orchestrator.set_draft_status(redraft.id, DraftStatus.approved)
    with db_session.session_scope() as s:
        assert len(repo.approved_this_week(s)) == 1
        assert s.get(type(draft), redraft.id).approved_at is not None
        from app.db.models import Note
        assert s.get(Note, draft.note_id).status == NoteStatus.approved


def test_research_rejects_ungrounded_source(monkeypatch):
    fake = R(json.dumps({"found": True, "title": "Made up", "publisher": "Nowhere", "url": "https://fake.example/x"}))
    monkeypatch.setattr(research.gemini, "generate", lambda *a, **k: fake)
    angle = research.find_news_angle("note", "Ingredient Deep-Dive", "x")
    assert angle.found is False


def _grounded(text, domains):
    from types import SimpleNamespace as NS

    chunks = [NS(web=NS(title=d, uri=f"https://{d}/article")) for d in domains]
    r = R(text)
    r.candidates = [NS(grounding_metadata=NS(grounding_chunks=chunks))]
    return r


def test_research_rejects_source_not_in_grounding(monkeypatch):
    claim = json.dumps({"found": True, "title": "T", "publisher": "Fake Wire", "url": "https://fakewire.example/x"})
    monkeypatch.setattr(research.gemini, "generate", lambda *a, **k: _grounded(claim, ["economictimes.indiatimes.com"]))
    assert research.find_news_angle("note", None, None).found is False


def test_research_accepts_grounded_source(monkeypatch):
    claim = json.dumps({"found": True, "title": "CDSCO tightens cosmetic labelling", "publisher": "The Economic Times",
                        "url": "https://economictimes.indiatimes.com/news/x", "summary": "s", "relevance": "r"})
    monkeypatch.setattr(research.gemini, "generate", lambda *a, **k: _grounded(claim, ["economictimes.indiatimes.com"]))
    angle = research.find_news_angle("note", None, None)
    assert angle.found and angle.url == "https://economictimes.indiatimes.com/news/x"


def test_research_follows_doi_redirect_to_grounded_publisher(monkeypatch):
    claim = json.dumps({"found": True, "title": "Azelaic acid delivery", "publisher": "Pharmaceuticals",
                        "url": "https://doi.org/10.3390/ph18091273", "summary": "s", "relevance": "r"})
    monkeypatch.setattr(research.gemini, "generate", lambda *a, **k: _grounded(claim, ["mdpi.com"]))
    monkeypatch.setattr(research, "follow_url", lambda u: "https://www.mdpi.com/1424-8247/18/9/1273")
    angle = research.find_news_angle("note", None, None)
    assert angle.found and angle.url.startswith("https://www.mdpi.com/")


def test_research_redirect_to_ungrounded_domain_still_rejected(monkeypatch):
    claim = json.dumps({"found": True, "title": "T", "publisher": "P", "url": "https://doi.org/10.1/x"})
    monkeypatch.setattr(research.gemini, "generate", lambda *a, **k: _grounded(claim, ["mdpi.com"]))
    monkeypatch.setattr(research, "follow_url", lambda u: "https://somewhere-else.example/x")
    assert research.find_news_angle("note", None, None).found is False


def test_app_note_forbids_invented_anecdotes():
    si = system_instruction()
    assert "Never invent a Skinstinct" in si
    assert si.index("Never invent a Skinstinct") > len(load_skill_text())  # appended, skill untouched


def test_publisher_name_matching_is_strict():
    srcs = [research.GroundedSource(title="economictimes.indiatimes.com", uri="u1"),
            research.GroundedSource(title="mdpi.com", uri="u2")]
    assert research.match_source(None, "The Economic Times", srcs).uri == "u1"
    assert research.match_source(None, "P", srcs) is None
    assert research.match_source(None, "Times", srcs) is None
    assert research.match_source(None, "Pharma Wire", srcs) is None


def test_research_falls_back_to_google_citation(monkeypatch):
    from types import SimpleNamespace as NS

    claim = json.dumps({"found": True, "title": "Azelaic acid review", "publisher": "Cureus",
                        "url": "https://www.cureus.com/made-up", "summary": "s", "relevance": "r"})
    r = _grounded(claim, ["mdpi.com", "1mg.com"])
    r.candidates[0].grounding_metadata.grounding_supports = [
        NS(grounding_chunk_indices=[0], segment=NS(text='"title": "Azelaic acid review"')),
        NS(grounding_chunk_indices=[1], segment=NS(text="other")),
    ]
    monkeypatch.setattr(research.gemini, "generate", lambda *a, **k: r)
    monkeypatch.setattr(research, "follow_url", lambda u: u)
    angle = research.find_news_angle("note", None, None)
    assert angle.found and angle.url == "https://mdpi.com/article" and angle.source == "mdpi.com"
    assert "cureus" not in angle.url and "check the headline" in angle.note
