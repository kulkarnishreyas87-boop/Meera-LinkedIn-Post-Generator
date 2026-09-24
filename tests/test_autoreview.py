"""Auto-review: score formula, decision rule, fact filling, and the orchestrator flows."""

import json
from dataclasses import replace

import pytest
from sqlmodel import SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.db import repo
from app.db import session as db_session
from app.db.models import Draft, DraftStatus, Note, NoteStatus
from app.pipeline import autoreview, orchestrator, research, triage
from app.pipeline import draft as draft_mod
from app.pipeline.autoreview import decide, fill_verify, parse_fill_answers, quality_score, verify_items


def checklist(voice=9, passed=8, total=8, hard=(), verify=0, top="none", note=8, invented=()):
    return {
        "review": {"voice_score": voice, "top_issue": top, "invented_claims": list(invented)},
        "self_check": [{"n": i, "passed": i <= passed} for i in range(1, total + 1)],
        "hard_failures": list(hard),
        "verify_count": verify,
        "note_score": note,
    }


# ---------------- score ----------------

def test_score_formula():
    # 0.45 x voice + 0.25 x (10 x self-check rate) + 0.30 x note score
    assert quality_score(checklist(voice=9, passed=8))[0] == 9  # 4.05 + 2.5 + 2.4 = 8.95
    assert quality_score(checklist(voice=8, passed=6))[0] == 8  # 3.6 + 1.875 + 2.4 = 7.875
    assert quality_score(checklist(voice=5, passed=8))[0] == 7  # 2.25 + 2.5 + 2.4 = 7.15
    assert quality_score(checklist(voice=1, passed=8))[0] == 5  # 0.45 + 2.5 + 2.4 = 5.35


def test_thin_note_caps_the_score():
    """A fluent post padded out of a two-word note can't reach auto-approval."""
    assert quality_score(checklist(voice=9, note=2))[0] == 7  # 4.05 + 2.5 + 0.6
    assert decide(7, checklist(voice=9, note=2)).action == "review"


def test_untriaged_note_uses_neutral_substance():
    assert quality_score(checklist(voice=9, note=None))[1]["note_score"] == 7


def test_format_failures_cost_two_points_each():
    assert quality_score(checklist(voice=9, hard=["word_count"]))[0] == 7
    assert quality_score(checklist(voice=9, hard=["word_count", "no_emojis", "no_bullets", "x", "y"]))[0] == 0


def test_invented_claims_cost_three_points_and_block_auto_approval():
    c = checklist(voice=10, note=10, invented=["'last month a manufacturer sent me a catalogue'"])
    assert quality_score(c)[0] == 7  # 4.5 + 2.5 + 3.0 - 3
    d = decide(9, c)  # even if something scored it high, it is never auto-approved
    assert d.action == "review" and "invented" in d.reason


def test_score_unavailable_when_reviewer_failed():
    assert quality_score(checklist(voice=None))[0] is None
    c = checklist()
    c["self_check"] = [{"n": 1, "passed": None}]
    assert quality_score(c)[0] is None


# ---------------- decision rule ----------------

@pytest.mark.parametrize(
    "score, kwargs, expected",
    [
        (9, {}, "auto_approved"),
        (8, {}, "auto_approved"),  # "above 7"
        (7, {}, "review"),  # exactly 7 -> Meera decides
        (6, {}, "auto_discarded"),  # "below 7"
        (0, {}, "auto_discarded"),
        (None, {}, "review"),
        (9, {"verify": 2}, "needs_facts"),
        (9, {"hard": ["word_count"]}, "review"),
        (4, {"verify": 2}, "auto_discarded"),
    ],
)
def test_decision_table(score, kwargs, expected):
    assert decide(score, checklist(**kwargs)).action == expected


def test_verify_can_be_allowed_by_config():
    assert decide(9, checklist(verify=1), allow_verify=True).action == "auto_approved"


def test_meera_requested_drafts_are_never_auto_discarded():
    d = decide(3, checklist(), requested_by_meera=True)
    assert d.action == "review" and "you asked" in d.reason


def test_custom_thresholds():
    assert decide(7, checklist(), approve_min=7).action == "auto_approved"
    assert decide(7, checklist(), discard_below=8).action == "auto_discarded"


def test_discard_reason_includes_top_issue():
    assert "Hook is generic" in decide(4, checklist(top="Hook is generic")).reason


# ---------------- filling facts ----------------

BODY = "We ran a study with [VERIFY: sample size] people over [VERIFY: duration]. Done."


def test_verify_items():
    assert verify_items(BODY) == ["sample size", "duration"]


def test_parse_numbered_and_plain_answers():
    assert parse_fill_answers("1. 25\n2) eight weeks", 2) == {1: "25", 2: "eight weeks"}
    assert parse_fill_answers("25\neight weeks", 2) == {1: "25", 2: "eight weeks"}
    assert parse_fill_answers("2: eight weeks", 2) == {2: "eight weeks"}
    assert parse_fill_answers("skip\neight weeks", 2) == {2: "eight weeks"}
    assert parse_fill_answers("It was our\nearly 2024 serum base", 1) == {1: "It was our early 2024 serum base"}


def test_fill_replaces_verbatim_and_tidies_spacing():
    body, n = fill_verify(BODY, {1: "25", 2: "eight weeks"})
    assert n == 2 and body == "We ran a study with 25 people over eight weeks. Done."
    body, n = fill_verify(BODY, {2: "eight weeks"})
    assert n == 1 and "[VERIFY: sample size]" in body and "eight weeks" in body


# ---------------- orchestrator flows (Gemini stubbed) ----------------

POST = "\n\n".join(
    ["In 2021 I was sitting in a stability review meeting and the pH was 3.2. This is legal. It is also not "
     "helpful, because the pH decides whether the active does anything. I have seen this misunderstood by "
     "customers, by other brands, and by us in our early formulations, so it is worth going through properly."] * 8
)


class R:
    def __init__(self, text):
        self.text = text
        self.candidates = []


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db_session.set_engine(engine)
    from app.db import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    state = {"voices": [9], "post": POST, "draft_calls": 0, "invented": []}

    def gen(prompt, *, system=None, json_schema=None, google_search=False, temperature=0.7):
        if json_schema is triage.TRIAGE_SCHEMA:
            return R(json.dumps({"score": 8, "publishable": True, "category": "Ingredient Deep-Dive", "core_insight": "x",
                                 "suggested_hook_type": "dated scene", "missing_facts": [], "reason": "r"}))
        if json_schema is draft_mod.REVIEW_SCHEMA:
            voice = state["voices"].pop(0) if len(state["voices"]) > 1 else state["voices"][0]
            return R(json.dumps({"answers": [{"n": i, "passed": True, "note": ""} for i in range(1, 9)],
                                 "voice_score": voice, "top_issue": "Hook is generic",
                                 "invented_claims": state["invented"].pop(0) if state["invented"] else []}))
        if json_schema is draft_mod.DRAFT_SCHEMA:
            if prompt.startswith("Revise this draft"):
                state["revisions"] = state.get("revisions", 0) + 1
            else:
                state["draft_calls"] += 1
                state["last_draft_prompt"] = prompt
            return R(json.dumps({"post": state["post"], "reviewer_notes": ""}))
        raise AssertionError("unexpected call")

    for mod in (triage.gemini, draft_mod.gemini):
        monkeypatch.setattr(mod, "generate", gen)
    monkeypatch.setattr(orchestrator, "find_news_angle", lambda *a: research.NewsAngle(found=False, note="none"))
    settings = replace(orchestrator.get_settings(), gemini_api_key="k", triage_threshold=7, auto_review=True,
                       auto_approve_min=8, auto_discard_below=7, auto_approve_with_verify=False)
    monkeypatch.setattr(orchestrator, "get_settings", lambda: settings)
    state["settings"] = settings
    with db_session.session_scope() as s:
        state["note_id"] = repo.create_note(s, "Pharmacy in Bandra, azelaic acid 10%").id
    yield state, monkeypatch
    db_session.set_engine(None)


def _note(nid):
    with db_session.session_scope() as s:
        return s.get(Note, nid)


def test_high_score_is_auto_approved(env):
    state, _ = env
    d = orchestrator.draft_note(state["note_id"])
    assert d.status == DraftStatus.approved and d.decision == "auto_approved" and d.decided_by == "auto"
    assert d.quality_score == 9 and d.approved_at is not None
    assert _note(state["note_id"]).status == NoteStatus.approved
    with db_session.session_scope() as s:
        assert len(repo.approved_this_week(s)) == 1


def test_low_score_gets_one_auto_redraft_then_discards(env):
    state, _ = env
    state["voices"] = [1, 1]  # 0.45 + 2.5 + 2.4 = 5.35 -> 5
    d = orchestrator.draft_note(state["note_id"])
    assert state["draft_calls"] == 2  # original + one automatic redraft
    assert d.status == DraftStatus.discarded and d.decision == "auto_discarded"
    assert d.checklist["auto_redraft_of_score"] == 5
    assert _note(state["note_id"]).status == NoteStatus.discarded  # kept, just discarded


def test_auto_redraft_can_rescue_a_draft(env):
    state, _ = env
    state["voices"] = [1, 9]
    d = orchestrator.draft_note(state["note_id"])
    assert d.status == DraftStatus.approved and d.checklist["auto_redraft_of_score"] == 5


def test_score_of_seven_goes_to_meera(env):
    state, _ = env
    state["voices"] = [5]  # 2.25 + 2.5 + 2.4 = 7.15 -> 7
    d = orchestrator.draft_note(state["note_id"])
    assert d.status == DraftStatus.pending and d.decision == "review" and d.decided_by is None


def test_meera_redraft_is_never_auto_discarded(env):
    state, _ = env
    state["voices"] = [1]
    d = orchestrator.draft_note(state["note_id"], instruction="shorter")
    assert state["draft_calls"] == 1 and d.status == DraftStatus.pending


def test_verify_markers_wait_for_facts_then_auto_approve(env):
    state, _ = env
    state["post"] = POST + " The panel had [VERIFY: sample size] people."
    d = orchestrator.draft_note(state["note_id"])
    assert d.status == DraftStatus.needs_facts and d.decision == "needs_facts"
    with db_session.session_scope() as s:
        assert d.id in [x.id for x in repo.pending_drafts(s)]  # shows in the review queue

    d2, filled, missing = orchestrator.fill_facts(d.id, "25")
    assert filled == 1 and missing == 0
    assert "25 people" in d2.body and d2.status == DraftStatus.approved and d2.decided_by == "auto"


def test_undo_and_restore(env):
    state, _ = env
    d = orchestrator.draft_note(state["note_id"])
    r = orchestrator.reopen_draft(d.id)
    assert r.status == DraftStatus.pending and r.approved_at is None and r.decided_by == "meera"
    assert _note(state["note_id"]).status == NoteStatus.drafted
    orchestrator.set_draft_status(d.id, DraftStatus.discarded)
    assert orchestrator.reopen_draft(d.id).status == DraftStatus.pending


def test_edits_never_auto_discard(env):
    state, _ = env
    state["voices"] = [5]
    d = orchestrator.draft_note(state["note_id"])
    e = orchestrator.update_draft_body(d.id, "Too short now.")  # word count fails -> score drops
    assert e.status == DraftStatus.pending and e.quality_score < 7


def test_auto_review_off_keeps_everything_manual(env):
    state, mp = env
    off = replace(state["settings"], auto_review=False)
    mp.setattr(orchestrator, "get_settings", lambda: off)
    d = orchestrator.draft_note(state["note_id"])
    assert d.status == DraftStatus.pending and d.decision is None and d.quality_score == 9


def test_migration_adds_new_columns_to_old_database(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE note (id INTEGER PRIMARY KEY, text VARCHAR NOT NULL)")
    con.execute("CREATE TABLE draft (id INTEGER PRIMARY KEY, note_id INTEGER, body VARCHAR)")
    con.commit()
    con.close()
    db_session.set_engine(create_engine(f"sqlite:///{path}"))
    try:
        db_session.init_db()
        cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(draft)")}
        assert {"quality_score", "decision", "decided_by", "decision_reason"} <= cols
    finally:
        db_session.set_engine(None)


def test_autoreview_module_never_mentions_publishing_api():
    import inspect

    assert "linkedin.com" not in inspect.getsource(autoreview).lower()


def test_invented_detail_triggers_redraft_that_must_remove_it(env):
    state, _ = env
    claim = ["'Last month a contract manufacturer sent me their catalogue'"]
    state["invented"] = [claim, claim]  # still invented after the automatic redraft
    d = orchestrator.draft_note(state["note_id"])
    assert state["draft_calls"] == 2
    assert "remove invented detail" in state["last_draft_prompt"]
    assert d.status == DraftStatus.discarded and d.checklist["quality"]["invented"] == 1


def test_redraft_that_drops_the_invented_detail_is_approved(env):
    state, _ = env
    state["invented"] = [["'Last month a manufacturer sent me a catalogue'"], []]
    d = orchestrator.draft_note(state["note_id"])
    assert d.status == DraftStatus.approved and d.checklist["auto_redraft_of_score"] == 6


def test_invented_detail_never_auto_approves_even_when_it_scores_high(env):
    state, _ = env
    state["voices"] = [10]
    state["invented"] = [["a small invented date"]]
    # 4.5 + 2.5 + 2.4 - 3 = 6.4 -> 6 -> retry; the retry is clean, so it can approve on merit
    d = orchestrator.draft_note(state["note_id"])
    assert state["draft_calls"] == 2 and d.checklist["quality"]["invented"] == 0


def test_note_score_is_recorded_on_the_draft(env):
    state, _ = env
    d = orchestrator.draft_note(state["note_id"])
    assert d.checklist["note_score"] == 8 and d.checklist["quality"]["note_score"] == 8
