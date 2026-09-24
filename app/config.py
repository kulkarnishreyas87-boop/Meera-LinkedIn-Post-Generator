"""Settings loaded from .env. No secret is ever hardcoded here."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"  # supports Grounding with Google Search


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: int | None
    gemini_api_key: str
    gemini_model: str
    triage_threshold: int
    database_url: str
    enable_bot: bool
    enable_scheduler: bool
    skills_dir: Path
    web_dist: Path
    # Auto-review of drafts (approve = ready for Meera to post manually; nothing is published)
    auto_review: bool = True
    auto_approve_min: int = 8  # draft quality score at or above this is auto-approved ("above 7")
    auto_discard_below: int = 7  # below this (after one auto-redraft) is auto-discarded
    auto_approve_with_verify: bool = False  # unfilled [VERIFY] markers block auto-approval

    def require_gemini(self) -> None:
        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set. Add it to .env (see .env.example).")

    def require_telegram(self) -> None:
        if not self.telegram_bot_token or self.telegram_chat_id is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env.")


def parse_chat_id(raw: str | None) -> int | None:
    """Parse TELEGRAM_CHAT_ID tolerating stray whitespace (e.g. 'TELEGRAM_CHAT_ID= -100123')."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    return int(raw)


@lru_cache
def get_settings() -> Settings:
    return Settings(
        telegram_bot_token=(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip(),
        telegram_chat_id=parse_chat_id(os.getenv("TELEGRAM_CHAT_ID")),
        gemini_api_key=(os.getenv("GEMINI_API_KEY") or "").strip(),
        gemini_model=(os.getenv("GEMINI_MODEL") or "").strip() or DEFAULT_GEMINI_MODEL,
        triage_threshold=_int("TRIAGE_THRESHOLD", 7),
        database_url=(os.getenv("DATABASE_URL") or "").strip() or f"sqlite:///{ROOT / 'skinstinct.db'}",
        enable_bot=_bool("ENABLE_BOT", True),
        enable_scheduler=_bool("ENABLE_SCHEDULER", True),
        skills_dir=ROOT / "skills",
        web_dist=ROOT / "web" / "dist",
        auto_review=_bool("AUTO_REVIEW", True),
        auto_approve_min=_int("AUTO_APPROVE_MIN", 8),
        auto_discard_below=_int("AUTO_DISCARD_BELOW", 7),
        auto_approve_with_verify=_bool("AUTO_APPROVE_WITH_VERIFY", False),
    )
