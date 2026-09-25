"""Catch notes that repeat one of Meera's already-published posts (skills/references/published-posts.md)."""

from __future__ import annotations

import re
from functools import lru_cache

from app.config import get_settings

SIMILARITY_THRESHOLD = 0.5  # share of the note's word-trigrams found in a published post


def _shingles(text: str, n: int = 3) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


@lru_cache
def published_posts() -> list[tuple[str, str]]:
    """(heading, text) for each published post in the reference file."""
    path = get_settings().skills_dir / "references" / "published-posts.md"
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    parts = re.split(r"^##\s+(.+)$", raw, flags=re.MULTILINE)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def match_published(note_text: str) -> tuple[str, float] | None:
    """Return (post heading, overlap) if the note mostly repeats a published post."""
    note = _shingles(note_text)
    if len(note) < 15:  # too short to judge; short notes are ideas, not copies
        return None
    best: tuple[str, float] | None = None
    for heading, text in published_posts():
        overlap = len(note & _shingles(text)) / len(note)
        if best is None or overlap > best[1]:
            best = (heading, overlap)
    return best if best and best[1] >= SIMILARITY_THRESHOLD else None
