"""
First-pass abusive-language check for reviews. Pure local string matching: no network calls, no
third-party service, safe to run inside the request.

A hit does not reject the review (the reviewer still sees it accepted) and is not a verdict: the
review is hidden from public listings and rating aggregates until an admin looks at it. The list is
deliberately high-precision, see ``app/data/review_abuse_terms.json``.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

from app.core.config import settings
from app.core.logger import logger

TERMS_FILE = Path(__file__).resolve().parent.parent / "data" / "review_abuse_terms.json"

_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)
_REPEATS = re.compile(r"(.)\1+")
_TOKEN = re.compile(r"[a-z*]+")


@dataclass(frozen=True)
class ModerationHit:
    categories: Tuple[str, ...]  # language codes whose terms matched, e.g. ("en", "pcm")
    match_count: int

    @property
    def reason(self) -> str:
        return f"Automatic filter: abusive language ({', '.join(self.categories)})"


def _collapse(word: str) -> str:
    return _REPEATS.sub(r"\1", word)


def normalise(text: str) -> List[str]:
    """Lower-case, strip accents, map leetspeak, split on punctuation, collapse repeated letters."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return [_collapse(t) for t in _TOKEN.findall(stripped.translate(_LEET))]


def _normalise_term(term: str) -> str:
    return " ".join(normalise(term))


@lru_cache(maxsize=1)
def _load_terms(extra: str) -> Dict[str, FrozenSet[str]]:
    with open(TERMS_FILE, encoding="utf-8") as fh:
        raw = json.load(fh)
    terms: Dict[str, FrozenSet[str]] = {}
    for lang, words in raw.items():
        if lang.startswith("_"):
            continue
        terms[lang] = frozenset(t for t in (_normalise_term(w) for w in words) if t)
    extra_terms = frozenset(
        t for t in (_normalise_term(w) for w in extra.split(",") if w.strip()) if t
    )
    if extra_terms:
        terms["custom"] = extra_terms
    return terms


def _token_matches(token: str, single_words: FrozenSet[str]) -> bool:
    if token in single_words:
        return True
    if "*" in token:  # masked: f*ck -> any single character in the masked position
        pattern = re.compile("^" + "".join("." if c == "*" else re.escape(c) for c in token) + "$")
        return any(pattern.match(w) for w in single_words)
    return False


def check_review_text(text: Optional[str]) -> Optional[ModerationHit]:
    """Return a ModerationHit when the text trips the list, else None (also when disabled)."""
    if not text or not settings.REVIEW_ABUSE_FILTER_ENABLED:
        return None
    try:
        terms = _load_terms(settings.REVIEW_ABUSE_EXTRA_TERMS)
    except Exception as exc:  # noqa: BLE001 - a broken list must never block a review
        logger.error(f"review abuse list could not be loaded: {exc}")
        return None
    tokens = normalise(text)
    if not tokens:
        return None
    padded = f" {' '.join(tokens)} "
    categories = []
    matches = 0
    for lang, entries in terms.items():
        single = frozenset(e for e in entries if " " not in e)
        lang_matches = sum(1 for t in tokens if _token_matches(t, single))
        lang_matches += sum(1 for e in entries if " " in e and f" {e} " in padded)
        if lang_matches:
            categories.append(lang)
            matches += lang_matches
    if not matches:
        return None
    return ModerationHit(categories=tuple(categories), match_count=matches)
