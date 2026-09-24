"""Render drafts as Telegram HTML messages with review buttons."""

from __future__ import annotations

import html
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import Draft, Note

TG_LIMIT = 4096
VERIFY_RE = re.compile(r"\[VERIFY:[^\]]*\]", re.IGNORECASE)


def review_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Approve", callback_data=f"a:{draft_id}"),
            InlineKeyboardButton("✏️ Redraft", callback_data=f"r:{draft_id}"),
            InlineKeyboardButton("🗑️ Discard", callback_data=f"d:{draft_id}"),
        ]]
    )


def redraft_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("↻ Just redraft", callback_data=f"rn:{draft_id}")]])


def highlight_verify(text: str) -> str:
    """HTML-escape the body and underline+bold every [VERIFY: ...] marker."""
    out, last = [], 0
    for m in VERIFY_RE.finditer(text):
        out.append(html.escape(text[last : m.start()]))
        out.append(f"<b><u>{html.escape(m.group(0))}</u></b>")
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def header(draft: Draft, note: Note) -> str:
    c = draft.checklist or {}
    bits = [f"Draft #{draft.id}", f"v{draft.version}"]
    if note.category:
        bits.append(html.escape(note.category))
    bits.append(f"{c.get('word_count', '?')} words")
    if c.get("verify_count"):
        bits.append(f"{c['verify_count']} [VERIFY]")
    return "📝 <b>" + " · ".join(bits) + "</b>"


def footer(draft: Draft) -> str:
    c = draft.checklist or {}
    lines = []
    if draft.news_found and draft.news_url:
        lines.append(f'📰 Angle: <a href="{html.escape(draft.news_url, quote=True)}">{html.escape(draft.news_title or draft.news_source or "source")}</a>'
                     + (f" ({html.escape(draft.news_source)})" if draft.news_source else ""))
    else:
        lines.append("📰 No news angle: " + html.escape(draft.news_note or "nothing credible found"))
    failed = [ch["label"] for ch in c.get("checks", []) if not ch["passed"] and ch["severity"] != "info"]
    failed += [f"Self-check #{r['n']}" for r in c.get("self_check", []) if r.get("passed") is False]
    lines.append("☑️ Checklist: all passed" if not failed else "⚠️ Check: " + html.escape(", ".join(failed)))
    if draft.reviewer_notes:
        lines.append("🔎 " + html.escape(draft.reviewer_notes))
    lines.append("<i>Drafts only - nothing is posted to LinkedIn. Approve = ready for you to copy and post.</i>")
    return "\n".join(lines)


def render_draft_messages(draft: Draft, note: Note) -> list[str]:
    """One message if it fits, else header+body and footer as separate messages."""
    head, body, foot = header(draft, note), highlight_verify(draft.body), footer(draft)
    single = f"{head}\n\n{body}\n\n{foot}"
    if len(single) <= TG_LIMIT:
        return [single]
    parts = [f"{head}\n\n{body}"] if len(head) + len(body) + 2 <= TG_LIMIT else [head, *_chunks(body)]
    return [*parts, foot]


def _chunks(text: str, size: int = TG_LIMIT - 50) -> list[str]:
    chunks, buf = [], ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) + 2 > size and buf:
            chunks.append(buf)
            buf = ""
        buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks
