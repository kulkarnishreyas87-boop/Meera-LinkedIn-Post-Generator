"""Loads Meera's voice skill verbatim for use as the system instruction.

The skill text is passed in full - never paraphrased or summarised. SKILL.md tells the
writer to read its two reference files, so those are appended verbatim too. The only
app-level addition is a short note on the [VERIFY: ...] marker format the dashboard
highlights; it does not change any rule in the skill.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.config import get_settings

REFERENCE_FILES = ["references/facts-and-positions.md", "references/published-posts.md"]

APP_ADDENDUM = """\
=== Application note (added by the drafting app, not part of the skill) ===
This draft will be reviewed by Meera in a dashboard before she posts it herself.
Wherever the skill asks for a placeholder or for a claim the user should verify, write it
inline in exactly this form: [VERIFY: what needs checking or filling in]. For example:
[VERIFY: return rate in humid cities, %]. Never invent Skinstinct data, study results or
citations; if it is not in the note, the fact sheet or well-established general science,
it must be a [VERIFY: ...] marker.
"""


@lru_cache
def load_skill_text(skills_dir: Path | None = None) -> str:
    """Return SKILL.md exactly as written."""
    skills_dir = skills_dir or get_settings().skills_dir
    return (skills_dir / "SKILL.md").read_text(encoding="utf-8")


@lru_cache
def system_instruction(skills_dir: Path | None = None) -> str:
    """SKILL.md + reference files (verbatim) + the app's [VERIFY] note."""
    skills_dir = skills_dir or get_settings().skills_dir
    parts = [load_skill_text(skills_dir)]
    for rel in REFERENCE_FILES:
        path = skills_dir / rel
        if path.exists():
            parts.append(f"=== File: {rel} ===\n{path.read_text(encoding='utf-8')}")
    parts.append(APP_ADDENDUM)
    return "\n\n".join(parts)
