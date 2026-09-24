from app.pipeline.checklist import autofix, run_checklist, word_count

PARA = (
    "Most serums don't list their pH on the label. This is legal. It is also not helpful, because the pH "
    "decides whether the active does anything at all once it is on your skin. I have seen this misunderstood "
    "by customers, by other brands, and by us in our early formulations, so it is worth going through properly."
)


def clean_post(n_paras: int = 7) -> str:
    return "\n\n".join([PARA] * n_paras)


def check(result, cid):
    return next(c for c in result["checks"] if c["id"] == cid)


def test_clean_post_passes():
    text = clean_post()
    r = run_checklist(text)
    assert 400 <= r["word_count"] <= 550, r["word_count"]
    assert r["passed"], r["hard_failures"]


def test_word_count_bounds():
    assert not check(run_checklist(clean_post(2)), "word_count")["passed"]
    assert not check(run_checklist(clean_post(12)), "word_count")["passed"]


def test_catches_emojis():
    r = run_checklist(clean_post() + " 🚀✨")
    assert not check(r, "no_emojis")["passed"]
    assert r["emojis"] == 2


def test_catches_hashtags_but_not_pH_or_numbers():
    r = run_checklist(clean_post() + "\n\n#skincare #SkinstinctScience")
    assert not check(r, "no_hashtags")["passed"]
    assert r["hashtags"] == 2
    assert check(run_checklist(clean_post() + " Batch #3 was fine."), "no_hashtags")["passed"]


def test_catches_bullets_and_numbered_lists():
    for bullet in ("- first point", "• first point", "1. first point", "* first point"):
        r = run_checklist(clean_post() + "\n\n" + bullet + "\n" + bullet)
        assert not check(r, "no_bullets")["passed"], bullet
    # a spaced hyphen mid-sentence is her house style, not a bullet
    assert check(run_checklist(clean_post() + " It is fine - mostly."), "no_bullets")["passed"]


def test_catches_bold_and_headers():
    assert not check(run_checklist("**Big claim**\n\n" + clean_post()), "no_bold_headers")["passed"]
    assert not check(run_checklist("## Title\n\n" + clean_post()), "no_bold_headers")["passed"]


def test_catches_em_dash_and_autofix_repairs_it():
    text = clean_post() + " The label—not the active—fails. pH 5.5–5.8."
    assert not check(run_checklist(text), "spaced_hyphens")["passed"]
    fixed = autofix(text)
    assert "—" not in fixed and "–" not in fixed
    assert "The label - not the active - fails" in fixed
    assert "5.5-5.8" in fixed
    assert check(run_checklist(fixed), "spaced_hyphens")["passed"]


def test_question_hook_flagged():
    r = run_checklist("Have you ever wondered about pH? " + clean_post())
    assert not check(r, "no_question_hook")["passed"]


def test_hype_and_cta_flagged():
    r = run_checklist(clean_post() + " This is a game-changer. Follow me for more.")
    assert not check(r, "no_hype")["passed"]
    assert not check(r, "no_cta")["passed"]


def test_one_line_paragraphs_flagged():
    choppy = "\n\n".join(["This is one line."] * 10)
    assert not check(run_checklist(choppy), "prose_paragraphs")["passed"]


def test_verify_markers_counted_and_listed():
    text = clean_post() + " Returns fell to [VERIFY: humid-city return rate, %] after [VERIFY: month]."
    r = run_checklist(text)
    assert r["verify_count"] == 2
    assert r["verify_items"] == ["humid-city return rate, %", "month"]
    assert r["passed"]  # [VERIFY] is info, not a failure


def test_unmarked_placeholder_warns():
    r = run_checklist(clean_post() + " Returns were [return rate, %].")
    assert not check(r, "placeholders_marked")["passed"]


def test_american_spelling_warns_only():
    r = run_checklist(clean_post() + " It helps to optimize the color.")
    c = check(r, "british_spelling")
    assert not c["passed"] and c["severity"] == "warning"
    assert r["passed"]


def test_word_count_basics():
    assert word_count("pH 5.5-5.8 is fine, isn't it?") == 6
    assert word_count("[VERIFY: a long thing to check] ok") == 2
