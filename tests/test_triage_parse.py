import json

import pytest

from app.pipeline import triage
from app.pipeline.triage import TriageParseError, TriageResult, is_publishable, parse_triage

GOOD = {
    "score": 8,
    "publishable": True,
    "category": "Ingredient Deep-Dive",
    "core_insight": "Azelaic acid percentage says little about delivered dose because of solubility.",
    "suggested_hook_type": "observed anecdote",
    "missing_facts": [],
    "reason": "Specific scene, clear mechanism, fits her label-is-the-start position.",
}


def test_parses_plain_json():
    r = parse_triage(json.dumps(GOOD))
    assert isinstance(r, TriageResult)
    assert r.score == 8 and r.category == "Ingredient Deep-Dive"


def test_parses_fenced_json_with_prose():
    raw = "Here you go:\n```json\n" + json.dumps(GOOD) + "\n```"
    assert parse_triage(raw).publishable is True


def test_rounds_float_and_string_scores():
    assert parse_triage(json.dumps({**GOOD, "score": 7.6})).score == 8
    assert parse_triage(json.dumps({**GOOD, "score": "6"})).score == 6


@pytest.mark.parametrize(
    "bad",
    [
        {**GOOD, "score": 11},
        {**GOOD, "category": "G"},  # must be one of the skill's four pillars
        {**GOOD, "suggested_hook_type": "question"},  # questions are not one of her hooks
        {k: v for k, v in GOOD.items() if k != "reason"},
    ],
)
def test_rejects_invalid_fields(bad):
    with pytest.raises(TriageParseError):
        parse_triage(json.dumps(bad))


def test_rejects_non_json():
    with pytest.raises(TriageParseError):
        parse_triage("I think this note is a 7.")


def test_threshold_gates_publishable():
    r = parse_triage(json.dumps({**GOOD, "score": 6}))
    assert not is_publishable(r, threshold=7)
    assert is_publishable(parse_triage(json.dumps(GOOD)), threshold=7)
    assert not is_publishable(parse_triage(json.dumps({**GOOD, "publishable": False})), threshold=7)


class _Resp:
    def __init__(self, text):
        self.text = text


def test_retries_once_on_parse_failure(monkeypatch):
    replies = iter(["not json", json.dumps(GOOD)])
    calls = []

    def fake_generate(prompt, **kw):
        calls.append(prompt)
        return _Resp(next(replies))

    monkeypatch.setattr(triage.gemini, "generate", fake_generate)
    monkeypatch.setattr(triage, "system_instruction", lambda: "skill")
    assert triage.triage_text("note", threshold=7).score == 8
    assert len(calls) == 2
    assert "not valid JSON" in calls[1]


def test_gives_up_after_one_retry(monkeypatch):
    monkeypatch.setattr(triage.gemini, "generate", lambda prompt, **kw: _Resp("nope"))
    monkeypatch.setattr(triage, "system_instruction", lambda: "skill")
    with pytest.raises(TriageParseError):
        triage.triage_text("note", threshold=7)
