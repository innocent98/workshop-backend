"""First-pass abusive-language filter: matching rules (English, Pidgin, Yoruba, Hausa, Igbo),
obfuscation handling and false-positive guards. Pure string logic, no network."""

import pytest

from app.core.config import settings
from app.services import review_moderation
from app.services.review_moderation import check_review_text, normalise


@pytest.mark.parametrize(
    "text,category",
    [
        ("You are an idiot, never again", "en"),
        ("This guy is a piece of shit", "en"),
        ("FUCK this job!!!", "en"),
        ("sh1t work, total bull$hit", "en"),
        ("f*ck him", "en"),
        ("fuuuuck", "en"),
        ("the man na mumu, he no sabi work", "pcm"),
        ("Yeye man! Ashawo!", "pcm"),
        ("Olodo ni e, agbaya", "yo"),
        ("omo ale", "yo"),
        ("Ọmọ ale", "yo"),  # tone marks / dots under letters are stripped
        ("dan iska ne shi", "ha"),
        ("wawa", "ha"),
        ("onye nzuzu", "ig"),
        ("I will find you and sort this out", "en"),
    ],
)
def test_abusive_text_is_caught(text, category):
    hit = check_review_text(text)
    assert hit is not None, text
    assert category in hit.categories
    assert "abusive language" in hit.reason


@pytest.mark.parametrize(
    "text",
    [
        "Excellent work, very professional and on time.",
        "Fixed my sink quickly. Highly recommend, 5 stars!",
        "He was late by two hours but the work was fine.",
        "Please assemble the class and pass the salad",  # 'ass' inside words must not match
        "Scunthorpe cocktail classic",  # classic substring traps
        "Made egusi soup money well spent, ofe nsala was great",  # Igbo 'ofe' (soup) is fine
        "Ara is a lovely person",  # a name
        "",
        None,
    ],
)
def test_clean_text_is_not_flagged(text):
    assert check_review_text(text) is None


def test_whole_words_only():
    # 'ode' is a listed Pidgin insult but must not fire inside other words
    assert check_review_text("A very modern and codeless approach") is None
    assert check_review_text("you be ode") is not None


def test_normalise_pipeline():
    assert normalise("Ọmọ  ALE!!") == ["omo", "ale"]
    assert normalise("sh1t") == ["shit"]
    assert normalise("fuuuck") == ["fuck"]


def test_multiple_matches_counted_across_languages():
    hit = check_review_text("idiot! mumu! onye nzuzu")
    assert hit.match_count >= 3  # 'onye nzuzu' counts as a phrase and as the word 'nzuzu'
    assert set(hit.categories) == {"en", "pcm", "ig"}


def test_filter_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "REVIEW_ABUSE_FILTER_ENABLED", False)
    assert check_review_text("you idiot") is None


def test_extra_terms_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "REVIEW_ABUSE_EXTRA_TERMS", "Zonko, big liar")
    review_moderation._load_terms.cache_clear()
    try:
        assert check_review_text("what a ZONKO") is not None
        hit = check_review_text("he is a big liar, honestly")
        assert hit is not None and "custom" in hit.categories
        assert check_review_text("a liar") is None  # phrase must match as a whole
    finally:
        monkeypatch.setattr(settings, "REVIEW_ABUSE_EXTRA_TERMS", "")
        review_moderation._load_terms.cache_clear()


def test_broken_list_never_blocks_a_review(monkeypatch):
    review_moderation._load_terms.cache_clear()
    monkeypatch.setattr(
        review_moderation, "TERMS_FILE", review_moderation.TERMS_FILE.parent / "nope"
    )
    try:
        assert check_review_text("you idiot") is None
    finally:
        monkeypatch.undo()
        review_moderation._load_terms.cache_clear()
